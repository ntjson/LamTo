"""ops/demo/demo_up.py smoke: the checks `up.sh` runs through the tunnel address.

A stand-in front door (a small HTTP server that behaves like Caddy and Django
should) and a stand-in ClamAV let each test break exactly one thing and see the
check that names it.
"""

from __future__ import annotations

import gzip
import json
import os
import socket
import struct
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "ops" / "demo" / "demo_up.py"
KIT_FILES = REPO_ROOT / "ops" / "demo-kit" / "files"
EICAR = rb"X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class FrontDoor(BaseHTTPRequestHandler):
    """Serves what a healthy demo serves; `broken` names what to get wrong."""

    site: "Site"

    def log_message(self, *args):
        pass

    def _send(self, status, body=b"", content_type="text/html", extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        site = self.site
        path = self.path
        if path == "/app/":
            return self._send(200, b"<html>stale build</html>" if "stale-index" in site.broken
                              else (site.app_root / "index.html").read_bytes())
        if path.startswith("/app/") and path.endswith(".wasm"):
            kind = "application/octet-stream" if "wasm-type" in site.broken else "application/wasm"
            extra = {} if "wasm-plain" in site.broken else {"Content-Encoding": "br"}
            return self._send(200, b"WASM", kind, extra)
        if path.startswith("/static/"):
            file = site.static_root / path[len("/static/"):]
            if "static-missing" in site.broken or not file.is_file():
                return self._send(404, b"nope")
            return self._send(200, file.read_bytes(), "text/css")
        if path == "/demo-kit/":
            return self._send(200, "".join(f'<a href="{n}">{n}</a>' for n in site.kit_names).encode())
        if path.startswith("/demo-kit/"):
            name = path[len("/demo-kit/"):]
            if "kit-missing" in site.broken and name.startswith("bao-gia"):
                return self._send(404, b"nope")
            file = site.kit_dir / name
            if not file.is_file():
                return self._send(404, b"nope")
            return self._send(200, file.read_bytes(), "application/pdf")
        if path == "/s/":
            if "no-login" in site.broken:
                return self._send(200, b"<html>welcome</html>")
            return self._send(302, b"", extra={"Location": "/accounts/login/?next=/s/"})
        if path.startswith("/accounts/login/"):
            return self._send(200, b'<form method="post"><input type="password" name="password"></form>')
        if path == "/api/v1/registration/options":
            if "api-down" in site.broken:
                return self._send(502, b"bad gateway")
            return self._send(200, json.dumps([{"id": 1, "name": "x", "units": []}]).encode(),
                              "application/json")
        self._send(404, b"nope")


class Site:
    def __init__(self, root: Path):
        self.app_root = root / "app"
        self.static_root = root / "static"
        self.kit_dir = root / "kit"
        self.broken: set[str] = set()
        (self.app_root).mkdir()
        (self.app_root / "index.html").write_text("<html>resident app</html>")
        (self.app_root / "canvaskit.wasm").write_bytes(b"\0asm")
        (self.app_root / "canvaskit.wasm.br").write_bytes(b"BR")
        (self.static_root / "web").mkdir(parents=True)
        (self.static_root / "web" / "staff.css").write_text("body{}")
        self.kit_dir.mkdir()
        for pdf in KIT_FILES.glob("*.pdf"):
            (self.kit_dir / pdf.name).write_bytes(pdf.read_bytes())
        self.kit_names = sorted(p.name for p in self.kit_dir.iterdir())


class FakeClamAV(threading.Thread):
    """Answers PING and INSTREAM like clamd; a payload holding EICAR is infected."""

    def __init__(self):
        super().__init__(daemon=True)
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(8)
        self.port = self.server.getsockname()[1]
        self.scans = 0

    def run(self):
        while True:
            try:
                connection, _ = self.server.accept()
            except OSError:
                return
            with connection:
                self._serve(connection)

    def _serve(self, connection):
        command = b""
        while not command.endswith(b"\0") and not command.endswith(b"\n"):
            chunk = connection.recv(1)
            if not chunk:
                return
            command += chunk
        if command.startswith(b"zPING") or command.startswith(b"PING"):
            connection.sendall(b"PONG\0")
            return
        payload = b""
        while True:
            (size,) = struct.unpack("!I", connection.recv(4, socket.MSG_WAITALL))
            if size == 0:
                break
            payload += connection.recv(size, socket.MSG_WAITALL)
        self.scans += 1
        if EICAR in payload:
            connection.sendall(b"stream: Eicar-Signature FOUND\0")
        else:
            connection.sendall(b"stream: OK\0")


@pytest.fixture
def world(tmp_path):
    site = Site(tmp_path)
    FrontDoor.site = site
    server = ThreadingHTTPServer(("127.0.0.1", 0), FrontDoor)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    clamav = FakeClamAV()
    clamav.start()
    worker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    site.url = f"http://127.0.0.1:{server.server_port}"
    site.clamav = clamav
    site.worker = worker
    yield site
    worker.kill()
    worker.wait()
    server.shutdown()
    clamav.server.close()


def smoke(site, **overrides):
    args = {
        "--app-root": site.app_root,
        "--static-root": site.static_root,
        "--kit-dir": site.kit_dir,
        "--clamav": f"127.0.0.1:{site.clamav.port}",
        "--worker-pid": site.worker.pid,
    }
    args.update(overrides)
    command = [sys.executable, "-I", str(HELPER), "smoke", site.url]
    for flag, value in args.items():
        command += [flag, str(value)]
    return subprocess.run(command, capture_output=True, text=True, timeout=60)


def test_a_healthy_demo_passes_every_check(world):
    result = smoke(world)

    assert result.returncode == 0, result.stderr
    for name in ("app", "wasm", "static", "kit", "login", "api", "worker", "clamav"):
        assert f"ok  {name}" in result.stdout


@pytest.mark.parametrize(
    ("broken", "check"),
    [
        ("stale-index", "app"),
        ("wasm-type", "wasm"),
        ("wasm-plain", "wasm"),
        ("static-missing", "static"),
        ("kit-missing", "kit"),
        ("no-login", "login"),
        ("api-down", "api"),
    ],
)
def test_each_broken_thing_fails_the_check_that_names_it(world, broken, check):
    world.broken.add(broken)

    result = smoke(world)

    assert result.returncode != 0
    assert f"FAIL  {check}" in result.stderr


def test_a_dead_worker_fails(world):
    world.worker.kill()
    world.worker.wait()

    result = smoke(world)

    assert result.returncode != 0
    assert "FAIL  worker" in result.stderr


def test_clamav_scans_both_kit_pdfs_and_the_notice(world):
    assert smoke(world).returncode == 0

    assert world.clamav.scans == 3


def test_a_file_clamav_flags_fails(world):
    (world.kit_dir / "bao-gia-sua-thang-may-mau.pdf").write_bytes(EICAR)

    result = smoke(world)

    assert result.returncode != 0
    assert "FAIL  clamav" in result.stderr
    assert "bao-gia-sua-thang-may-mau.pdf" in result.stderr


def test_an_unreachable_clamav_fails_rather_than_passes(world):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]

    result = smoke(world, **{"--clamav": f"127.0.0.1:{dead_port}"})

    assert result.returncode != 0
    assert "FAIL  clamav" in result.stderr


def test_a_build_with_no_wasm_file_fails(world):
    (world.app_root / "canvaskit.wasm").unlink()
    (world.app_root / "canvaskit.wasm.br").unlink()

    result = smoke(world)

    assert result.returncode != 0
    assert "FAIL  wasm" in result.stderr


def test_the_checks_all_run_even_after_one_fails(world):
    world.broken.update({"static-missing", "api-down"})

    result = smoke(world)

    assert "FAIL  static" in result.stderr
    assert "FAIL  api" in result.stderr
    assert "ok  app" in result.stdout
