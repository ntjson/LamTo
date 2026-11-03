"""The demo environment file and the key fingerprints (see ops/demo/reset.sh).

    python -I ops/demo/demo_env.py init-env ENV_FILE --static-root DIR --app-web-root DIR
    python -I ops/demo/demo_env.py fingerprints ENV_FILE
    python -I ops/demo/demo_env.py verify-fingerprints ENV_FILE RECORDED_FILE

``init-env`` writes ENV_FILE on the first run only and never touches an
existing file. ``fingerprints`` prints one ``name=value`` line each for the
evidence secret and the signer address, derived from the file. It never prints
a secret. The signer key is used only to find its address.

``verify-fingerprints`` compares them with the ones the reset recorded and exits
non-zero, naming what changed, when they differ or were never recorded.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import shlex
import sys
from pathlib import Path

DEMO_ALLOWED_HOSTS = "localhost,127.0.0.1,.trycloudflare.com"
FINGERPRINT_LENGTH = 16


def _template(*, secret_key, evidence_secret, signer_key, static_root, app_web_root):
    return f"""\
# Demo environment, generated once by ops/demo/reset.sh and reused by every
# later run. Local to this machine; never commit it. Deleting it makes the next
# reset mint new keys (and `up` then refuses until a reset records them).
SECRET_KEY={shlex.quote(secret_key)}
EVIDENCE_WRITE_SECRET={shlex.quote(evidence_secret)}
PLATFORM_SIGNER_PRIVATE_KEY={signer_key}
EVIDENCE_ANCHORING_BACKEND=disabled
AI_TRIAGE_URL=
AI_TRIAGE_TOKEN=
AI_TRIAGE_MODEL=
DEBUG=false
STATIC_ROOT={shlex.quote(static_root)}
APP_WEB_ROOT={shlex.quote(app_web_root)}
# The quick tunnel's name is random, so every trycloudflare.com host is allowed.
ALLOWED_HOSTS={DEMO_ALLOWED_HOSTS}

POSTGRES_DB=lamto
POSTGRES_USER=lamto_writer
POSTGRES_PASSWORD=lamto-writer
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_SERVICE_ROLE=lamto_service
POSTGRES_APPLICATION_ROLE=lamto_app
POSTGRES_EXECUTOR_ROLE=lamto_writer
PRIVATE_STORAGE_ENDPOINT_URL=http://127.0.0.1:9000
PRIVATE_STORAGE_BUCKET=lamto-documents
PRIVATE_STORAGE_ACCESS_KEY=lamto-local
PRIVATE_STORAGE_SECRET_KEY=lamto-local-secret
CLAMAV_HOST=127.0.0.1
CLAMAV_PORT=3310
FIREBASE_CREDENTIALS=
PUSH_ENABLED=
"""


def init_env(env_file: Path, static_root: Path, app_web_root: Path) -> str:
    if env_file.exists():
        return f"Demo environment file kept unchanged: {env_file}"
    text = _template(
        secret_key=secrets.token_urlsafe(64),
        evidence_secret=secrets.token_urlsafe(48),
        signer_key="0x" + secrets.token_hex(32),
        static_root=str(static_root),
        app_web_root=str(app_web_root),
    )
    env_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    return f"Demo environment file created: {env_file}"


def read_env(env_file: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in env_file.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition("=")
        parts = shlex.split(value)
        values[key.strip()] = parts[0] if parts else ""
    return values


def _fingerprint(label: str, value: str) -> str:
    digest = hashlib.sha256(f"lamto-demo-{label}:{value}".encode()).hexdigest()
    return digest[:FINGERPRINT_LENGTH]


def fingerprints(env_file: Path) -> dict[str, str]:
    env = read_env(env_file)
    # Same rule as settings.py: the evidence secret falls back to SECRET_KEY.
    evidence_secret = env.get("EVIDENCE_WRITE_SECRET") or env.get("SECRET_KEY") or ""
    signer_key = env.get("PLATFORM_SIGNER_PRIVATE_KEY", "")
    if not evidence_secret:
        raise SystemExit("Neither EVIDENCE_WRITE_SECRET nor SECRET_KEY is set.")
    if not signer_key:
        raise SystemExit("PLATFORM_SIGNER_PRIVATE_KEY is not set.")
    from eth_account import Account

    address = Account.from_key(signer_key).address
    return {
        "evidence_secret": _fingerprint("evidence-secret", evidence_secret),
        "signer_address": _fingerprint("signer-address", address),
    }


FINGERPRINT_LABELS = {
    "evidence_secret": "the evidence secret",
    "signer_address": "the platform signer key",
}


def verify_fingerprints(env_file: Path, recorded_file: Path) -> list[str]:
    """What is wrong, in words; empty when the keys are the ones the reset recorded."""
    if not env_file.exists():
        return [f"The demo environment file {env_file} is missing. Run ops/demo/reset.sh."]
    if not recorded_file.exists():
        return [
            f"No key fingerprints are recorded ({recorded_file}): the last reset did not "
            "finish. Run ops/demo/reset.sh."
        ]
    recorded = dict(
        line.split("=", 1) for line in recorded_file.read_text().split() if "=" in line
    )
    now = fingerprints(env_file)
    return [
        f"{label.capitalize()} is not the one the data was made with. Its fingerprint "
        "changed since the last reset. Restore the old key in the demo environment "
        "file, or run ops/demo/reset.sh."
        for name, label in FINGERPRINT_LABELS.items()
        if recorded.get(name) != now[name]
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-env")
    init.add_argument("env_file", type=Path)
    init.add_argument("--static-root", type=Path, required=True)
    init.add_argument("--app-web-root", type=Path, required=True)
    show = commands.add_parser("fingerprints")
    show.add_argument("env_file", type=Path)
    verify = commands.add_parser("verify-fingerprints")
    verify.add_argument("env_file", type=Path)
    verify.add_argument("recorded_file", type=Path)
    args = parser.parse_args(argv)

    if args.command == "init-env":
        print(init_env(args.env_file, args.static_root, args.app_web_root))
    elif args.command == "verify-fingerprints":
        problems = verify_fingerprints(args.env_file, args.recorded_file)
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0
    else:
        for name, value in fingerprints(args.env_file).items():
            print(f"{name}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
