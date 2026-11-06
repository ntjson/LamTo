# The LamTo server for the unattended trial and the Codespaces demo: Django under gunicorn, and the
# same image runs the worker. Built on the trial server itself (arm64 on
# Oracle's Ampere VMs), from the repository root:
#
#   docker compose -f ops/trial/compose.yaml build
#
# insightface is left out: it ships only as a source distribution (it would
# need a compiler), it is imported only when a gate face endpoint is used, and
# the gate is never part of the demo. Everything else installs from wheels.

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /srv/lamto
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/srv/lamto/.venv \
    PATH=/srv/lamto/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-install-package insightface

COPY manage.py ./
COPY locale ./locale
COPY src ./src
COPY ops/gunicorn.conf.py ./ops/gunicorn.conf.py
COPY ops/trial/entrypoint.sh ./ops/trial/entrypoint.sh
RUN uv sync --frozen --no-dev --no-install-package insightface

ENTRYPOINT ["/srv/lamto/ops/trial/entrypoint.sh"]
CMD ["web"]
