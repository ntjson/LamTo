"""gunicorn settings for the single-origin deployment (see ops/Caddyfile).

Run from the repository root with the Django settings in the environment:

    gunicorn --config ops/gunicorn.conf.py lamto.config.wsgi:application

gunicorn is only ever reached through Caddy, so it binds loopback and nothing
else. Never bind it to 0.0.0.0.
"""

import os

bind = f"127.0.0.1:{os.getenv('GUNICORN_PORT', '8000')}"
workers = int(os.getenv("GUNICORN_WORKERS", "3"))

# A document upload is virus-scanned inside its request (ClamAV's connection
# timeout is lamto.documents.scanner.SCAN_TIMEOUT_SECONDS), then written to
# object storage. The request timeout has to leave room for both.
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))

pythonpath = "src"

accesslog = "-"
errorlog = "-"
