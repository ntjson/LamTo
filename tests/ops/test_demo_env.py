"""ops/demo/demo_env.py: the demo environment file and the key fingerprints."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "ops" / "demo" / "demo_env.py"
# The publicly known development key shipped in .env.example.
DEV_SIGNER_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"


def run(*args, check=True):
    return subprocess.run(
        [sys.executable, "-I", str(HELPER), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            key, _, value = line.partition("=")
            values[key] = shlex.split(value)[0] if value else ""
    return values


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / ".env.demo"
    run("init-env", str(path), "--static-root", str(tmp_path / "static"), "--app-web-root", str(tmp_path / "app"))
    return path


def test_first_run_writes_a_demo_only_environment(env_file, tmp_path):
    env = read_env(env_file)

    assert env["SECRET_KEY"] and env["EVIDENCE_WRITE_SECRET"]
    assert env["SECRET_KEY"] != env["EVIDENCE_WRITE_SECRET"]
    assert env["PLATFORM_SIGNER_PRIVATE_KEY"].startswith("0x")
    assert env["PLATFORM_SIGNER_PRIVATE_KEY"] != DEV_SIGNER_KEY
    assert env["EVIDENCE_ANCHORING_BACKEND"] == "disabled"
    assert env["AI_TRIAGE_URL"] == "" and env["AI_TRIAGE_TOKEN"] == ""
    assert env["AI_TRIAGE_MODEL"] == ""
    assert env["DEBUG"].lower() in {"", "0", "false", "no"}
    assert env["STATIC_ROOT"] == str(tmp_path / "static")
    assert ".trycloudflare.com" in env["ALLOWED_HOSTS"].split(",")
    assert "localhost" in env["ALLOWED_HOSTS"].split(",")


def test_environment_file_is_private_to_the_user(env_file):
    assert env_file.stat().st_mode & 0o077 == 0


def test_later_runs_reuse_the_file_unchanged(env_file):
    before = env_file.read_bytes()

    result = run("init-env", str(env_file), "--static-root", "/x", "--app-web-root", "/y")

    assert env_file.read_bytes() == before
    assert "kept" in result.stdout.lower()


def test_each_demo_gets_its_own_keys(env_file, tmp_path):
    other = tmp_path / "other.env"
    run("init-env", str(other), "--static-root", str(tmp_path / "static"), "--app-web-root", str(tmp_path / "app"))

    first, second = read_env(env_file), read_env(other)
    for key in ("SECRET_KEY", "EVIDENCE_WRITE_SECRET", "PLATFORM_SIGNER_PRIVATE_KEY"):
        assert first[key] != second[key]


def test_fingerprints_never_contain_the_secrets(env_file):
    env = read_env(env_file)

    out = run("fingerprints", str(env_file)).stdout

    for secret in ("SECRET_KEY", "EVIDENCE_WRITE_SECRET", "PLATFORM_SIGNER_PRIVATE_KEY"):
        assert env[secret] not in out
        assert env[secret].removeprefix("0x") not in out
    lines = dict(line.split("=", 1) for line in out.strip().splitlines())
    assert set(lines) == {"evidence_secret", "signer_address"}
    assert all(len(v) == 16 for v in lines.values())


def test_fingerprints_follow_the_keys(env_file):
    first = run("fingerprints", str(env_file)).stdout
    assert run("fingerprints", str(env_file)).stdout == first

    env = read_env(env_file)
    changed = env_file.read_text().replace(
        env["EVIDENCE_WRITE_SECRET"], "a-different-secret"
    )
    env_file.write_text(changed)
    after = dict(l.split("=") for l in run("fingerprints", str(env_file)).stdout.split())
    before = dict(l.split("=") for l in first.split())
    assert after["evidence_secret"] != before["evidence_secret"]
    assert after["signer_address"] == before["signer_address"]


def test_evidence_secret_falls_back_to_secret_key_like_django(tmp_path):
    path = tmp_path / "env"
    path.write_text(
        "SECRET_KEY=abc\nEVIDENCE_WRITE_SECRET=\n"
        f"PLATFORM_SIGNER_PRIVATE_KEY={DEV_SIGNER_KEY}\n"
    )
    explicit = tmp_path / "explicit"
    explicit.write_text(
        "SECRET_KEY=zzz\nEVIDENCE_WRITE_SECRET=abc\n"
        f"PLATFORM_SIGNER_PRIVATE_KEY={DEV_SIGNER_KEY}\n"
    )

    assert run("fingerprints", str(path)).stdout == run("fingerprints", str(explicit)).stdout


def test_fingerprints_fail_loudly_on_a_missing_signer_key(tmp_path):
    path = tmp_path / "env"
    path.write_text("SECRET_KEY=abc\n")

    result = run("fingerprints", str(path), check=False)

    assert result.returncode != 0
    assert "PLATFORM_SIGNER_PRIVATE_KEY" in result.stderr


class TestVerifyFingerprints:
    @pytest.fixture
    def recorded(self, env_file, tmp_path):
        path = tmp_path / "fingerprints"
        path.write_text(run("fingerprints", str(env_file)).stdout)
        return path

    def test_unchanged_keys_match_what_the_reset_recorded(self, env_file, recorded):
        assert run("verify-fingerprints", str(env_file), str(recorded), check=False).returncode == 0

    def test_a_changed_evidence_secret_is_named(self, env_file, recorded):
        env = read_env(env_file)
        env_file.write_text(
            env_file.read_text().replace(env["EVIDENCE_WRITE_SECRET"], "a-different-secret")
        )

        result = run("verify-fingerprints", str(env_file), str(recorded), check=False)

        assert result.returncode != 0
        assert "evidence secret" in result.stderr.lower()
        assert "signer" not in result.stderr.lower()
        assert "a-different-secret" not in result.stderr

    def test_a_changed_signer_key_is_named(self, env_file, recorded):
        env = read_env(env_file)
        env_file.write_text(
            env_file.read_text().replace(env["PLATFORM_SIGNER_PRIVATE_KEY"], DEV_SIGNER_KEY)
        )

        result = run("verify-fingerprints", str(env_file), str(recorded), check=False)

        assert result.returncode != 0
        assert "signer" in result.stderr.lower()
        assert DEV_SIGNER_KEY not in result.stderr

    def test_no_recorded_fingerprints_means_the_reset_did_not_finish(self, env_file, tmp_path):
        result = run("verify-fingerprints", str(env_file), str(tmp_path / "missing"), check=False)

        assert result.returncode != 0
        assert "reset" in result.stderr.lower()

    def test_a_missing_environment_file_is_refused(self, tmp_path, recorded):
        result = run("verify-fingerprints", str(tmp_path / "nope.env"), str(recorded), check=False)

        assert result.returncode != 0
        assert "reset" in result.stderr.lower()
