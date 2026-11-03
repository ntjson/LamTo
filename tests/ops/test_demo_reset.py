"""ops/demo/reset.sh, run for real against stand-ins for docker, flutter and manage.py.

The stand-ins keep a ledger of every call they get, and the fake docker keeps
named volumes as files, so these tests can show what the reset removed, what it
left alone, and in what order it worked.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RESET = REPO_ROOT / "ops" / "demo" / "reset.sh"
PROJECT = "lamto-demo"
DEV_PROJECT = "lamto"

FAKE_DOCKER = r'''#!__PYTHON__
import json, os, sys
from pathlib import Path

state = Path(os.environ["FAKE_STATE"])
args = sys.argv[1:]
with open(state / "calls.log", "a") as log:
    log.write(json.dumps({"tool": "docker", "args": args}) + "\n")
vol = state / "volumes"
vol.mkdir(exist_ok=True)

def fail_if(word):
    if os.environ.get("FAKE_DOCKER_FAIL") == word:
        print(f"fake docker: {word} failed", file=sys.stderr)
        sys.exit(1)

if args[0] == "ps":
    if (state / "dev_up").exists():
        print("lamto")
    sys.exit(0)
if args[:2] == ["volume", "inspect"]:
    sys.exit(0 if (vol / args[2]).exists() else 1)
if args[:2] == ["volume", "rm"]:
    for name in args[2:]:
        (vol / name).unlink()
    sys.exit(0)
if args[0] == "compose":
    assert "--volumes" not in args and "-v" not in args, "compose down must never drop volumes"
    project = args[args.index("-p") + 1]
    rest = args[args.index(project) + 1:]
    verb = next(a for a in rest if a in {"up", "run", "rm", "exec", "stop", "down"})
    fail_if(verb)
    if verb in {"up", "run"}:
        for name in ("postgres-data", "minio-data", "clamav-data"):
            if f"{project}_{name}" not in os.listdir(vol):
                if name == "clamav-data" and "clamav" not in rest and verb == "up":
                    continue
                (vol / f"{project}_{name}").write_text("fresh")
    if verb == "exec":
        if "pg_dump" in rest:
            fail_if("pg_dump")
            sys.stdout.write("DUMP:" + (vol / f"{project}_postgres-data").read_text())
    sys.exit(0)
sys.exit(2)
'''

FAKE_FLUTTER = r'''#!__PYTHON__
import json, os, sys
from pathlib import Path

state = Path(os.environ["FAKE_STATE"])
with open(state / "calls.log", "a") as log:
    log.write(json.dumps({"tool": "flutter", "args": sys.argv[1:], "cwd": os.getcwd()}) + "\n")
if os.environ.get("FAKE_FLUTTER_FAIL"):
    print("fake flutter: build failed", file=sys.stderr)
    sys.exit(1)
out = Path("build/web")
out.mkdir(parents=True, exist_ok=True)
(out / "index.html").write_text("<html>" + "resident app " * 50 + "</html>")
(out / "main.dart.js").write_text("console.log('app');" * 200)
(out / "canvaskit.wasm").write_bytes(b"\0asm" + b"\0" * 400)
(out / "logo.png").write_bytes(b"\x89PNG" + bytes(range(256)))
'''

# Stands in for the project's python: manage.py is recorded, anything else runs for real.
FAKE_PYTHON = r'''#!__PYTHON__
import json, os, subprocess, sys
from pathlib import Path

state = Path(os.environ["FAKE_STATE"])
args = sys.argv[1:]
if args[:1] != ["manage.py"]:
    os.execv("__PYTHON__", ["__PYTHON__", *args])
command = args[1]
keys = ("POSTGRES_USER", "PILOT_ALLOW_FIXTURES", "DEBUG", "STATIC_ROOT", "ALLOWED_HOSTS", "SECRET_KEY")
with open(state / "calls.log", "a") as log:
    log.write(json.dumps({"tool": "manage", "args": args[1:], "env": {k: os.environ.get(k) for k in keys}}) + "\n")
if os.environ.get("FAKE_MANAGE_FAIL") == command:
    print(f"fake manage.py: {command} failed", file=sys.stderr)
    sys.exit(1)
if command == "collectstatic":
    root = Path(os.environ["STATIC_ROOT"])
    (root / "web").mkdir(parents=True, exist_ok=True)
    (root / "web" / "staff.css").write_text("body{}")
if command == "seed_demo":
    print("Resident (phone):   0912345678")
    print("Password (both):    demo-password")
'''


@pytest.fixture
def world(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (
        ("docker", FAKE_DOCKER),
        ("flutter", FAKE_FLUTTER),
        ("python", FAKE_PYTHON),
    ):
        path = bin_dir / name
        path.write_text(body.replace("__PYTHON__", sys.executable))
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    state = tmp_path / "state"
    state.mkdir()
    (tmp_path / "app").mkdir()
    return World(tmp_path, bin_dir, state)


class World:
    def __init__(self, root, bin_dir, state):
        self.root, self.bin_dir, self.state = root, bin_dir, state
        self.demo_dir = root / "demo"
        self.env_file = root / "env.demo"

    def run(self, **extra_env):
        env = {
            **os.environ,
            "PATH": f"{self.bin_dir}:{os.environ['PATH']}",
            "FAKE_STATE": str(self.state),
            "PYTHON": str(self.bin_dir / "python"),
            "DEMO_DIR": str(self.demo_dir),
            "DEMO_ENV_FILE": str(self.env_file),
            "APP_DIR": str(self.root / "app"),
            **extra_env,
        }
        return subprocess.run(
            ["bash", str(RESET)], env=env, capture_output=True, text=True, cwd=REPO_ROOT
        )

    # --- the fake machine ---
    def volume(self, name):
        return self.state / "volumes" / name

    def put_volume(self, name, content):
        self.volume(name).parent.mkdir(exist_ok=True)
        self.volume(name).write_text(content)

    def volumes(self):
        folder = self.state / "volumes"
        return {p.name: p.read_text() for p in folder.iterdir()} if folder.exists() else {}

    def calls(self):
        log = self.state / "calls.log"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text().splitlines()]

    def manage(self, command):
        return [c for c in self.calls() if c["tool"] == "manage" and c["args"][0] == command]

    def archives(self):
        folder = self.demo_dir / "archive"
        return sorted(folder.iterdir()) if folder.exists() else []


def test_first_run_prepares_everything_the_venue_needs(world):
    result = world.run()

    assert result.returncode == 0, result.stderr
    assert world.env_file.exists()
    assert (world.demo_dir / "app" / "index.html").exists()
    assert (world.demo_dir / "static" / "web" / "staff.css").exists()
    assert (world.demo_dir / "fingerprints").exists()
    assert "demo-password" in result.stdout  # the logins are printed


def test_steps_run_in_the_documented_order(world):
    world.put_volume(f"{PROJECT}_postgres-data", "visit-1")

    assert world.run().returncode == 0

    events = []
    for call in world.calls():
        if call["tool"] == "docker" and "pg_dump" in call["args"]:
            events.append("archive")
        elif call["tool"] == "docker" and call["args"][:2] == ["volume", "rm"]:
            events.append("wipe")
        elif call["tool"] == "manage" and call["args"][0] in {"migrate", "seed_demo", "collectstatic"}:
            events.append(call["args"][0])
        elif call["tool"] == "flutter":
            events.append("build")
    assert events == ["archive", "wipe", "migrate", "seed_demo", "build", "collectstatic"]
    assert (world.demo_dir / "fingerprints").exists()


def test_there_is_nothing_to_archive_on_the_first_run(world):
    assert world.run().returncode == 0

    assert world.archives() == []
    assert not any("pg_dump" in c["args"] for c in world.calls() if c["tool"] == "docker")


def test_the_previous_visit_is_archived_by_date_and_time_before_the_wipe(world):
    world.put_volume(f"{PROJECT}_postgres-data", "visit-1")

    assert world.run().returncode == 0

    (archive,) = world.archives()
    assert re.fullmatch(r"lamto-\d{8}-\d{6}\.dump", archive.name)
    assert archive.read_text() == "DUMP:visit-1"
    assert world.volumes()[f"{PROJECT}_postgres-data"] == "fresh"


def test_a_failed_archive_stops_before_anything_is_wiped(world):
    world.put_volume(f"{PROJECT}_postgres-data", "visit-1")

    result = world.run(FAKE_DOCKER_FAIL="pg_dump")

    assert result.returncode != 0
    assert "archive" in result.stderr.lower()
    assert world.volumes()[f"{PROJECT}_postgres-data"] == "visit-1"
    assert world.archives() == []


def test_only_the_demo_postgres_and_minio_volumes_are_wiped(world):
    for name in ("postgres-data", "minio-data", "clamav-data"):
        world.put_volume(f"{PROJECT}_{name}", "visit-1")

    assert world.run().returncode == 0

    volumes = world.volumes()
    assert volumes[f"{PROJECT}_postgres-data"] == "fresh"
    assert volumes[f"{PROJECT}_minio-data"] == "fresh"
    assert volumes[f"{PROJECT}_clamav-data"] == "visit-1"  # signatures survive
    removed = [c["args"][2:] for c in world.calls() if c["args"][:2] == ["volume", "rm"]]
    assert removed == [[f"{PROJECT}_postgres-data", f"{PROJECT}_minio-data"]]


def test_the_development_stacks_data_survives_a_reset(world):
    for name in ("postgres-data", "minio-data", "clamav-data"):
        world.put_volume(f"{DEV_PROJECT}_{name}", "dev-data")
        world.put_volume(f"{PROJECT}_{name}", "visit-1")

    assert world.run().returncode == 0

    volumes = world.volumes()
    for name in ("postgres-data", "minio-data", "clamav-data"):
        assert volumes[f"{DEV_PROJECT}_{name}"] == "dev-data"
    # Every compose call names the demo project, so none can fall to the default one.
    for call in world.calls():
        if call["tool"] == "docker" and call["args"][0] == "compose":
            assert call["args"][call["args"].index("-p") + 1] == PROJECT


def test_it_refuses_while_the_development_stack_is_up(world):
    (world.state / "dev_up").write_text("")
    world.put_volume(f"{PROJECT}_postgres-data", "visit-1")

    result = world.run()

    assert result.returncode != 0
    assert "development stack" in result.stderr
    assert world.volumes() == {f"{PROJECT}_postgres-data": "visit-1"}
    assert not world.env_file.exists()
    assert [c for c in world.calls() if c["tool"] != "docker"] == []


def test_the_environment_file_is_made_once_and_reused(world):
    assert world.run().returncode == 0
    first = world.env_file.read_bytes()

    assert world.run().returncode == 0

    assert world.env_file.read_bytes() == first


def test_the_servers_run_with_the_demo_environment_and_fixtures_only_for_the_seed(world):
    assert world.run().returncode == 0

    migrate, = world.manage("migrate")
    seed, = world.manage("seed_demo")
    collect, = world.manage("collectstatic")
    assert migrate["env"]["POSTGRES_USER"] == "lamto_owner"
    assert seed["env"]["PILOT_ALLOW_FIXTURES"] == "1"
    assert migrate["env"]["PILOT_ALLOW_FIXTURES"] in (None, "")
    assert collect["env"]["PILOT_ALLOW_FIXTURES"] in (None, "")
    assert collect["env"]["DEBUG"] == "false"
    assert collect["env"]["STATIC_ROOT"] == str(world.demo_dir / "static")


def test_the_web_app_is_built_under_app_and_precompressed(world):
    assert world.run().returncode == 0

    (build,) = [c for c in world.calls() if c["tool"] == "flutter"]
    assert build["args"] == ["build", "web", "--release", "--base-href", "/app/"]
    assert build["cwd"] == str(world.root / "app")
    served = world.demo_dir / "app"
    for name in ("index.html", "main.dart.js", "canvaskit.wasm"):
        original = (served / name).read_bytes()
        assert gzip.decompress((served / f"{name}.gz").read_bytes()) == original
        brotli = subprocess.run(
            ["brotli", "-dc", str(served / f"{name}.br")], capture_output=True, check=True
        )
        assert brotli.stdout == original
    assert not (served / "logo.png.gz").exists()  # already compressed


def test_a_rebuilt_app_replaces_the_old_one(world):
    assert world.run().returncode == 0
    stale = world.demo_dir / "app" / "left-over.js"
    stale.write_text("old")

    assert world.run().returncode == 0

    assert not stale.exists()


def test_fingerprints_are_recorded_and_the_secrets_are_not(world):
    assert world.run().returncode == 0

    text = (world.demo_dir / "fingerprints").read_text()
    names = [line.split("=")[0] for line in text.splitlines()]
    assert names == ["evidence_secret", "signer_address"]
    env = world.env_file.read_text()
    for line in env.splitlines():
        key, _, value = line.partition("=")
        if key in {"SECRET_KEY", "EVIDENCE_WRITE_SECRET", "PLATFORM_SIGNER_PRIVATE_KEY"}:
            assert value.strip("'").removeprefix("0x") not in text


def test_a_rerun_after_a_reset_yields_the_same_fingerprints(world):
    assert world.run().returncode == 0
    first = (world.demo_dir / "fingerprints").read_text()

    assert world.run().returncode == 0

    assert (world.demo_dir / "fingerprints").read_text() == first


@pytest.mark.parametrize(
    "failure, step, later_tool",
    [
        ({"FAKE_MANAGE_FAIL": "migrate"}, "migrate", "seed_demo"),
        ({"FAKE_MANAGE_FAIL": "seed_demo"}, "seed", "flutter"),
        ({"FAKE_FLUTTER_FAIL": "1"}, "build", "collectstatic"),
        ({"FAKE_MANAGE_FAIL": "collectstatic"}, "static", None),
    ],
)
def test_it_stops_at_the_first_failing_step_and_says_which(world, failure, step, later_tool):
    # A fingerprint file from an earlier reset must not outlive a reset that failed.
    (world.demo_dir).mkdir()
    (world.demo_dir / "fingerprints").write_text("evidence_secret=old\n")

    result = world.run(**failure)

    assert result.returncode != 0
    assert f"Reset stopped at step: {step}" in result.stderr
    assert not (world.demo_dir / "fingerprints").exists()
    if later_tool:
        names = [c["args"][0] if c["tool"] == "manage" else c["tool"] for c in world.calls()]
        assert later_tool not in names


def test_a_failed_reset_can_simply_be_run_again(world):
    assert world.run(FAKE_MANAGE_FAIL="migrate").returncode != 0

    assert world.run().returncode == 0

    assert (world.demo_dir / "fingerprints").exists()
    assert len(world.archives()) == 1  # the half-made database was archived, not lost


@pytest.mark.parametrize("missing", ["docker", "flutter", "brotli", "gzip"])
def test_it_names_a_missing_tool_before_touching_anything(world, missing):
    (world.state / "calls.log").touch()
    # A PATH holding only the fake tools we want, plus coreutils.
    keep = world.root / "keep-bin"
    keep.mkdir()
    for tool in ("bash", "env", "dirname", "basename", "date", "mkdir", "rm", "cp", "mv",
                 "find", "cat", "sleep", "mktemp", "tr", "sed", "grep", "head", "cmp", "chmod"):
        found = shutil.which(tool)
        if found:
            (keep / tool).symlink_to(found)
    for tool in ("docker", "flutter", "brotli", "gzip"):
        if tool == missing:
            continue
        source = world.bin_dir / tool if (world.bin_dir / tool).exists() else shutil.which(tool)
        (keep / tool).symlink_to(source)
    (keep / "python").symlink_to(world.bin_dir / "python")

    env = {
        "PATH": str(keep),
        "FAKE_STATE": str(world.state),
        "PYTHON": str(keep / "python"),
        "DEMO_DIR": str(world.demo_dir),
        "DEMO_ENV_FILE": str(world.env_file),
        "APP_DIR": str(world.root / "app"),
    }
    result = subprocess.run(
        [shutil.which("bash"), str(RESET)], env=env, capture_output=True, text=True, cwd=REPO_ROOT
    )

    assert result.returncode != 0
    assert missing in result.stderr
    assert not world.env_file.exists()
    assert world.volumes() == {}


def test_the_archive_is_private_to_the_user(world):
    world.put_volume(f"{PROJECT}_postgres-data", "visit-1")

    assert world.run().returncode == 0

    (archive,) = world.archives()
    assert archive.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("name", ["APP_WEB_ROOT", "STATIC_ROOT"])
@pytest.mark.parametrize(
    "bad",
    ["/", "{home}", "{root}", "{demo}", "{demo}/../elsewhere", "relative/path", "{demo}//x"],
)
def test_a_build_or_static_root_outside_the_demo_directory_stops_the_reset_before_the_wipe(
    world, name, bad
):
    assert world.run().returncode == 0
    (world.state / "calls.log").unlink()
    text = world.env_file.read_text()
    value = bad.format(home=os.environ["HOME"], root=REPO_ROOT, demo=world.demo_dir)
    world.env_file.write_text(
        "\n".join(
            f"{name}={value}" if line.startswith(f"{name}=") else line
            for line in text.splitlines()
        )
        + "\n"
    )

    result = world.run()

    assert result.returncode != 0
    assert name in result.stderr
    assert world.volumes()[f"{PROJECT}_postgres-data"] == "fresh"
    assert not any(c["args"][:2] == ["volume", "rm"] for c in world.calls() if c["tool"] == "docker")
    assert world.archives() == []
