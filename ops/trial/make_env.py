"""Write ops/trial/trial.env once, on the trial server. Standard library only.

    python3 -I ops/trial/make_env.py ENV_FILE TRIAL_HOST

Never overwrites an existing file: the evidence secret and the signer key sign
everything the trial records, so changing them mid-trial breaks it. The keys
are minted here, on the server, and exist nowhere else.
"""

from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path


def render(host: str) -> str:
    password = "lamto" + "".join(secrets.choice("0123456789") for _ in range(4))
    return f"""\
# Unattended trial settings. Generated once on this server; never commit it.
TRIAL_HOST={host}
TRIAL_PASSWORD={password}

SECRET_KEY={secrets.token_urlsafe(64)}
EVIDENCE_WRITE_SECRET={secrets.token_urlsafe(48)}
PLATFORM_SIGNER_PRIVATE_KEY=0x{secrets.token_hex(32)}
EVIDENCE_ANCHORING_BACKEND=disabled
DOCUMENT_SCAN_BACKEND=none
CLAMAV_HOST=
CLAMAV_PORT=0
AI_TRIAGE_URL=
AI_TRIAGE_TOKEN=
AI_TRIAGE_MODEL=
FIREBASE_CREDENTIALS=
PUSH_ENABLED=
DEBUG=false
ALLOWED_HOSTS={host}
CSRF_TRUSTED_ORIGINS=https://{host}
GUNICORN_WORKERS=3

POSTGRES_DB=lamto
POSTGRES_USER=lamto_writer
POSTGRES_PASSWORD=lamto-writer
POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_SERVICE_ROLE=lamto_service
POSTGRES_APPLICATION_ROLE=lamto_app
POSTGRES_EXECUTOR_ROLE=lamto_writer
PRIVATE_STORAGE_ENDPOINT_URL=http://minio:9000
PRIVATE_STORAGE_BUCKET=lamto-documents
PRIVATE_STORAGE_ACCESS_KEY=lamto-local
PRIVATE_STORAGE_SECRET_KEY=lamto-local-secret
"""


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    env_file, host = Path(argv[0]), argv[1]
    if env_file.exists():
        print(f"Kept unchanged: {env_file}")
        return 0
    fd = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(render(host))
    print(f"Created: {env_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
