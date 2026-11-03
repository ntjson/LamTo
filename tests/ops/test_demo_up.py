"""ops/demo/up.sh, run for real against stand-ins for docker, gunicorn, the worker,
Caddy and cloudflared, with a stand-in ClamAV.

The stand-ins write down every call and every process they start, so these tests
can show what `up` started, in what order, what it refused to do, and that
stopping it stops every process it started and nothing else.
"""

from __future__ import annotations

import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.ops.test_demo_smoke import FakeClamAV

REPO_ROOT = Path(__file__).resolve().parents[2]
UP = REPO_ROOT / "ops" / "demo" / "up.sh"
ENV_HELPER = REPO_ROOT / "ops" / "demo" / "demo_env.py"
PROJECT = "lamto-demo"
TUNNEL = "http://127.0.0.1:{port}"  # stands in for https://<name>.trycloudflare.com
TUNNEL_PATTERN = r"http://127\.0\.0\.1:\d+"

FAKE_DOCKER = r'''#!__PYTHON__
import json, os, sys
from pathlib import Path

state = Path(os.environ["FAKE_STATE"])
args = sys.argv[1:]
with open(state / "calls.log", "a") as log:
    log.write(json.dumps({"tool": "docker", "args": args}) + "\n")
if args[0] == "ps":
    if (state / "dev_up").exists():
        print("lamto")
    sys.exit(0)
if args[0] == "compose":
    if os.environ.get("FAKE_DOCKER_FAIL") and os.environ["FAKE_DOCKER_FAIL"] in args:
        sys.exit(1)
    sys.exit(0)
sys.exit(2)
'''

# Python for the demo: gunicorn and the worker are stand-in processes; anything
# else (the helpers) runs for real.
FAKE_PYTHON = r'''#!__PYTHON__
import json, os, sys, time
from pathlib import Path

state = Path(os.environ["FAKE_STATE"])
args = sys.argv[1:]


def started(name):
    (state / "pids").mkdir(exist_ok=True)
    (state / "pids" / name).write_text(str(os.getpid()))
    keys = ("DEBUG", "ALLOWED_HOSTS", "PILOT_ALLOW_FIXTURES", "STATIC_ROOT", "SECRET_KEY", "POSTGRES_USER")
    (state / "pids" / f"{name}.env").write_text(json.dumps({k: os.environ.get(k) for k in keys}))
    with open(state / "calls.log", "a") as log:
        log.write(json.dumps({"tool": name, "args": args}) + "\n")


if args[:2] == ["-m", "gunicorn"]:
    started("gunicorn")
    os.execv("__PYTHON__", ["__PYTHON__", "__SERVERS__", "gunicorn"])
if args[:2] == ["manage.py", "run_worker"]:
    started("worker")
    time.sleep(600)
    sys.exit(0)
if args[:1] == ["manage.py"]:
    print("unexpected manage.py call", args, file=sys.stderr)
    sys.exit(3)
os.execv("__PYTHON__", ["__PYTHON__", *args])
'''

FAKE_CADDY = r'''#!__PYTHON__
import json, os, sys
from pathlib import Path

state = Path(os.environ["FAKE_STATE"])
(state / "pids").mkdir(exist_ok=True)
(state / "pids" / "caddy").write_text(str(os.getpid()))
(state / "pids" / "caddy.env").write_text(json.dumps({k: os.environ.get(k) for k in (
    "CADDY_PORT", "GUNICORN_PORT", "STATIC_ROOT", "APP_WEB_ROOT", "CADDY_EXTRA_ROUTES", "DEMO_KIT_ROOT")}))
with open(state / "calls.log", "a") as log:
    log.write(json.dumps({"tool": "caddy", "args": sys.argv[1:]}) + "\n")
os.execv("__PYTHON__", ["__PYTHON__", "__SERVERS__", "caddy"])
'''

FAKE_CLOUDFLARED = r'''#!__PYTHON__
import json, os, sys, time
from pathlib import Path

state = Path(os.environ["FAKE_STATE"])
(state / "pids").mkdir(exist_ok=True)
(state / "pids" / "cloudflared").write_text(str(os.getpid()))
with open(state / "calls.log", "a") as log:
    log.write(json.dumps({"tool": "cloudflared", "args": sys.argv[1:]}) + "\n")
print("INF Requesting new quick Tunnel on trycloudflare.com...", file=sys.stderr, flush=True)
time.sleep(float(os.environ.get("FAKE_TUNNEL_DELAY", "0")))
if os.environ.get("FAKE_TUNNEL_NEVER"):
    time.sleep(600)
print("INF |  " + os.environ["FAKE_TUNNEL_URL"] + "  |", file=sys.stderr, flush=True)
time.sleep(600)
'''

# The servers behind the stand-ins. `gunicorn` answers like Django; `caddy` serves
# the roots it is given and proxies the rest, like ops/Caddyfile.
SERVERS = r'''
import json, os, sys, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

role = sys.argv[1]
broken = set(filter(None, os.environ.get("FAKE_BROKEN", "").split(",")))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, status, body=b"", kind="text/html", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        getattr(self, role)()

    def gunicorn(self):
        if self.path == "/s/":
            return self.send(302, extra={"Location": "/accounts/login/"})
        if self.path.startswith("/accounts/login/"):
            return self.send(200, b'<input type="password">')
        if self.path == "/api/v1/registration/options":
            if "api" in broken:
                return self.send(500, b"boom")
            return self.send(200, b'[{"id": 1, "name": "Mau", "units": []}]', "application/json")
        self.send(404, b"nope")

    def caddy(self):
        app = Path(os.environ["APP_WEB_ROOT"])
        static = Path(os.environ["STATIC_ROOT"])
        extra = os.environ.get("CADDY_EXTRA_ROUTES")
        kit = Path(os.environ["DEMO_KIT_ROOT"]) if extra and os.environ.get("DEMO_KIT_ROOT") else None
        path = self.path
        if path == "/app/":
            return self.send(200, (app / "index.html").read_bytes())
        if path.startswith("/app/") and path.endswith(".wasm"):
            return self.send(200, b"W", "application/wasm", {"Content-Encoding": "br"})
        if path.startswith("/static/"):
            file = static / path[len("/static/"):]
            return self.send(200, file.read_bytes(), "text/css") if file.is_file() else self.send(404)
        if kit is not None and path.startswith("/demo-kit/"):
            name = path[len("/demo-kit/"):] or "index.html"
            file = kit / name
            return self.send(200, file.read_bytes(), "application/pdf") if file.is_file() else self.send(404)
        url = f"http://127.0.0.1:{os.environ['GUNICORN_PORT']}{path}"
        try:
            with urllib.request.urlopen(url) as upstream:
                self.send(upstream.status, upstream.read(), upstream.headers["Content-Type"] or "text/html")
        except urllib.error.HTTPError as error:
            if error.code in (301, 302):
                self.send(error.code, extra={"Location": error.headers["Location"]})
            else:
                self.send(error.code, error.read())


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


urllib.request.install_opener(urllib.request.build_opener(NoRedirect))
port = int(os.environ["GUNICORN_PORT" if role == "gunicorn" else "CADDY_PORT"])
ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
'''


def free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Up:
    def __init__(self, root: Path):
        self.root = root
        self.bin_dir = root / "bin"
        self.state = root / "state"
        self.demo_dir = root / "demo"
        self.env_file = root / "env.demo"
        self.bin_dir.mkdir()
        self.state.mkdir()
        servers = root / "servers.py"
        servers.write_text(SERVERS)
        for name, body in (
            ("docker", FAKE_DOCKER),
            ("python", FAKE_PYTHON),
            ("caddy", FAKE_CADDY),
            ("cloudflared", FAKE_CLOUDFLARED),
        ):
            path = self.bin_dir / name
            path.write_text(body.replace("__PYTHON__", sys.executable).replace("__SERVERS__", str(servers)))
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        self.clamav = FakeClamAV()
        self.clamav.start()
        self.caddy_port = free_port()
        self.gunicorn_port = free_port()
        self.procs: list[subprocess.Popen] = []
        self.prepare_visit()

    # --- what a finished reset leaves behind ---
    def prepare_visit(self):
        subprocess.run(
            [sys.executable, "-I", str(ENV_HELPER), "init-env", str(self.env_file),
             "--static-root", str(self.demo_dir / "static"), "--app-web-root", str(self.demo_dir / "app")],
            check=True, capture_output=True,
        )
        text = self.env_file.read_text().replace("CLAMAV_PORT=3310", f"CLAMAV_PORT={self.clamav.port}")
        self.env_file.write_text(text)
        (self.demo_dir / "app").mkdir(parents=True)
        (self.demo_dir / "app" / "index.html").write_text("<html>resident app</html>")
        (self.demo_dir / "app" / "canvaskit.wasm").write_bytes(b"\0asm")
        (self.demo_dir / "static" / "web").mkdir(parents=True)
        (self.demo_dir / "static" / "web" / "staff.css").write_text("body{}")
        self.record_fingerprints()

    def record_fingerprints(self):
        out = subprocess.run(
            [sys.executable, "-I", str(ENV_HELPER), "fingerprints", str(self.env_file)],
            check=True, capture_output=True, text=True,
        ).stdout
        (self.demo_dir / "fingerprints").write_text(out)

    # --- running it ---
    def env(self, **extra):
        return {
            **os.environ,
            "PATH": f"{self.bin_dir}:{os.environ['PATH']}",
            "FAKE_STATE": str(self.state),
            "PYTHON": str(self.bin_dir / "python"),
            "DEMO_DIR": str(self.demo_dir),
            "DEMO_ENV_FILE": str(self.env_file),
            "CADDY_PORT": str(self.caddy_port),
            "GUNICORN_PORT": str(self.gunicorn_port),
            "DEMO_CLAMAV_TIMEOUT": "3",
            "DEMO_TUNNEL_TIMEOUT": "5",
            "DEMO_TUNNEL_URL_PATTERN": TUNNEL_PATTERN,
            "FAKE_TUNNEL_URL": TUNNEL.format(port=self.caddy_port),
            "PILOT_ALLOW_FIXTURES": "1",  # the demo must not pass this on
            **extra,
        }

    def start(self, **extra) -> subprocess.Popen:
        proc = subprocess.Popen(
            ["bash", str(UP)], env=self.env(**extra), cwd=REPO_ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        self.procs.append(proc)
        return proc

    def run_to_end(self, **extra):
        proc = self.start(**extra)
        out, _ = proc.communicate(timeout=90)
        return proc.returncode, out

    def run_until_ready(self, **extra):
        """Start `up` and read its output until the address is shown (or it ends)."""
        proc = self.start(**extra)
        lines = []
        for line in proc.stdout:
            lines.append(line)
            if "/app/" in line and "Zalo" in line:
                break
        return proc, "".join(lines)

    def stop(self, proc, sig=signal.SIGINT):
        proc.send_signal(sig)
        out, _ = proc.communicate(timeout=30)
        return out

    # --- what happened ---
    def calls(self):
        log = self.state / "calls.log"
        return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []

    def compose_calls(self):
        return [c["args"] for c in self.calls() if c["tool"] == "docker" and c["args"][0] == "compose"]

    def started(self):
        folder = self.state / "pids"
        if not folder.exists():
            return {}
        return {p.name: int(p.read_text()) for p in folder.iterdir() if not p.name.endswith(".env")}

    def seen_env(self, name):
        return json.loads((self.state / "pids" / f"{name}.env").read_text())

    def alive(self, pid):
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        try:
            return Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[0] != "Z"
        except OSError:
            return False

    def close(self):
        for proc in self.procs:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        for pid in self.started().values():
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
        self.clamav.server.close()


@pytest.fixture
def up(tmp_path):
    world = Up(tmp_path)
    yield world
    world.close()


def test_it_shows_the_address_and_a_qr_code_only_after_the_smoke_check_passes(up):
    proc, out = up.run_until_ready()
    try:
        address = TUNNEL.format(port=up.caddy_port)
        assert f"{address}/app/" in out
        assert any(ch in out for ch in "█▀▄")  # the QR code
        assert out.rindex("ok  clamav") < out.index(f"{address}/app/")
        for check in ("app", "wasm", "static", "kit", "login", "api", "worker", "clamav"):
            assert f"ok  {check}" in out
    finally:
        up.stop(proc)


def test_the_steps_run_in_the_documented_order(up):
    proc, out = up.run_until_ready()
    up.stop(proc)

    marks = [
        out.index("Starting the compose services"),
        out.index("ClamAV answers"),
        out.index("Starting gunicorn"),
        out.index("Tunnel address"),
        out.index("ok  app"),
        out.index("/app/", out.index("ok  clamav")),
    ]
    assert marks == sorted(marks)


def test_clamav_is_never_recreated_and_the_demo_project_is_used(up):
    proc, _ = up.run_until_ready()
    up.stop(proc)

    calls = up.compose_calls()
    assert calls
    clamav_up = [c for c in calls if "up" in c and "clamav" in c]
    assert clamav_up and all("--no-recreate" in c for c in clamav_up)
    for call in calls:
        assert call[call.index("-p") + 1] == PROJECT
        assert "--force-recreate" not in call and "--build" not in call
        assert not {"down", "rm", "stop", "kill", "restart", "run"} & set(call)


def test_it_starts_gunicorn_the_worker_caddy_and_a_quick_tunnel(up):
    proc, _ = up.run_until_ready()
    try:
        assert set(up.started()) == {"gunicorn", "worker", "caddy", "cloudflared"}
        tunnel = next(c for c in up.calls() if c["tool"] == "cloudflared")
        assert f"http://127.0.0.1:{up.caddy_port}" in tunnel["args"]
        assert next(c for c in up.calls() if c["tool"] == "gunicorn")["args"][:2] == ["-m", "gunicorn"]
    finally:
        up.stop(proc)


def test_the_processes_get_the_demo_environment_and_no_fixtures_flag(up):
    proc, _ = up.run_until_ready()
    try:
        for name in ("gunicorn", "worker"):
            env = up.seen_env(name)
            assert env["DEBUG"] == "false"
            assert ".trycloudflare.com" in env["ALLOWED_HOSTS"]
            assert env["PILOT_ALLOW_FIXTURES"] is None
            assert env["SECRET_KEY"]
        assert up.seen_env("gunicorn")["POSTGRES_USER"] == "lamto_writer"
    finally:
        up.stop(proc)


def test_the_kit_is_served_only_through_the_demo_routes(up):
    proc, _ = up.run_until_ready()
    try:
        env = up.seen_env("caddy")
        assert Path(env["CADDY_EXTRA_ROUTES"]).name == "demo-kit.caddy"
        assert Path(env["CADDY_EXTRA_ROUTES"]).is_file()
        kit = Path(env["DEMO_KIT_ROOT"])
        assert (kit / "index.html").is_file()
        assert len(list(kit.glob("*.pdf"))) == 3
        assert env["APP_WEB_ROOT"] == str(up.demo_dir / "app")
        assert env["STATIC_ROOT"] == str(up.demo_dir / "static")
    finally:
        up.stop(proc)


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_stopping_it_stops_every_process_it_started_and_leaves_the_containers(up, sig):
    proc, _ = up.run_until_ready()
    pids = up.started()
    assert all(up.alive(pid) for pid in pids.values())
    containers_before = up.compose_calls()

    up.stop(proc, sig)

    time.sleep(0.3)
    assert [name for name, pid in pids.items() if up.alive(pid)] == []
    assert up.compose_calls() == containers_before  # nothing was stopped or removed
    assert proc.returncode == 0


def test_a_failing_smoke_check_shows_no_address_and_stops_everything(up):
    code, out = up.run_to_end(FAKE_BROKEN="api")

    assert code != 0
    assert "FAIL  api" in out
    assert f"{TUNNEL.format(port=up.caddy_port)}/app/" not in out
    assert not any(ch in out for ch in "█▀▄")
    time.sleep(0.3)
    assert [n for n, pid in up.started().items() if up.alive(pid)] == []


def test_clamav_that_never_answers_stops_it_before_anything_is_started(up):
    up.env_file.write_text(
        up.env_file.read_text().replace(f"CLAMAV_PORT={up.clamav.port}", f"CLAMAV_PORT={free_port()}")
    )

    code, out = up.run_to_end()

    assert code != 0
    assert "ClamAV" in out
    assert up.started() == {}


def test_it_refuses_while_the_development_stack_holds_the_ports(up):
    (up.state / "dev_up").write_text("")

    code, out = up.run_to_end()

    assert code != 0
    assert "development stack" in out
    assert up.compose_calls() == []
    assert up.started() == {}


def test_it_refuses_when_the_web_build_is_missing(up):
    (up.demo_dir / "app" / "index.html").unlink()

    code, out = up.run_to_end()

    assert code != 0
    assert "web build" in out.lower() and "reset.sh" in out
    assert up.compose_calls() == []
    assert up.started() == {}


def test_it_refuses_when_the_signer_key_fingerprint_has_changed(up):
    text = up.env_file.read_text()
    key = re.search(r"PLATFORM_SIGNER_PRIVATE_KEY=(\S+)", text).group(1)
    up.env_file.write_text(text.replace(key, "0x" + "ab" * 32))

    code, out = up.run_to_end()

    assert code != 0
    assert "signer" in out.lower()
    assert up.started() == {}
    assert up.compose_calls() == []


def test_it_refuses_when_the_evidence_secret_fingerprint_has_changed(up):
    text = up.env_file.read_text()
    secret = re.search(r"EVIDENCE_WRITE_SECRET=(\S+)", text).group(1)
    up.env_file.write_text(text.replace(secret, "another-secret"))

    code, out = up.run_to_end()

    assert code != 0
    assert "evidence secret" in out.lower()
    assert up.started() == {}


def test_it_refuses_when_the_reset_never_recorded_fingerprints(up):
    (up.demo_dir / "fingerprints").unlink()

    code, out = up.run_to_end()

    assert code != 0
    assert "reset.sh" in out
    assert up.started() == {}


def test_it_refuses_without_a_demo_environment_file(up):
    up.env_file.unlink()

    code, out = up.run_to_end()

    assert code != 0
    assert "reset.sh" in out


def test_it_names_a_missing_tool(up):
    (up.bin_dir / "cloudflared").unlink()
    env = up.env(PATH=f"{up.bin_dir}:/usr/bin:/bin")

    proc = subprocess.run(["bash", str(UP)], env=env, cwd=REPO_ROOT, capture_output=True, text=True)

    assert proc.returncode != 0
    assert "cloudflared" in proc.stdout + proc.stderr
    assert up.compose_calls() == []


def test_it_refuses_when_a_port_it_needs_is_taken(up):
    import socket

    with socket.socket() as taken:
        taken.bind(("127.0.0.1", up.caddy_port))
        taken.listen(1)
        code, out = up.run_to_end()

    assert code != 0
    assert str(up.caddy_port) in out
    assert up.started() == {}


def test_no_tunnel_address_in_time_stops_everything(up):
    code, out = up.run_to_end(FAKE_TUNNEL_NEVER="1", DEMO_TUNNEL_TIMEOUT="2")

    assert code != 0
    assert "tunnel" in out.lower()
    assert f"/app/" not in out.split("Tunnel")[-1]
    time.sleep(0.3)
    assert [n for n, pid in up.started().items() if up.alive(pid)] == []


def test_a_process_dying_while_it_runs_stops_the_rest(up):
    proc, _ = up.run_until_ready()
    pids = up.started()

    os.kill(pids["worker"], signal.SIGKILL)
    proc.communicate(timeout=30)

    assert proc.returncode != 0
    time.sleep(0.3)
    assert [n for n, pid in pids.items() if up.alive(pid)] == []
