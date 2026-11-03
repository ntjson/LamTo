# Shared by the demo scripts (reset.sh, up.sh). Source it; do not run it.
#
# Everything the scripts keep on this machine lives in one place:
#   .env.demo   the demo environment file (gitignored)
#   .demo/      archive/ of previous visits, the web build, collected static
#               files and the key fingerprints (gitignored)
# Each can be moved with the variables below.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# The demo is its own compose project. compose.yaml sets no project name, so the
# development stack runs as the default project and owns the default volumes
# (<directory>_postgres-data and so on). Every compose call here names this
# project, so none of them can reach the development stack's data.
DEMO_PROJECT="lamto-demo"
DEMO_DIR="${DEMO_DIR:-${ROOT_DIR}/.demo}"
DEMO_ENV_FILE="${DEMO_ENV_FILE:-${ROOT_DIR}/.env.demo}"
APP_DIR="${APP_DIR:-${ROOT_DIR}/app}"
PYTHON="${PYTHON:-.venv/bin/python}"

# compose.yaml publishes these on the host: Postgres, MinIO (API, console), ClamAV.
DEMO_PORTS=(5432 9000 9001 3310)

STEP="starting"

step() { STEP="$1"; log "==> $2"; }
log() { printf '%s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

compose() {
  docker compose -f "${ROOT_DIR}/compose.yaml" -p "${DEMO_PROJECT}" "$@"
}

# compose.yaml binds fixed host ports, so the development stack and the demo
# cannot run together. Refuse, rather than stop or touch the other stack.
refuse_if_dev_stack_up() {
  local port holders holder
  for port in "${DEMO_PORTS[@]}"; do
    holders="$(docker ps --filter "publish=${port}" \
      --format '{{with .Label "com.docker.compose.project"}}{{.}}{{else}}{{$.Names}}{{end}}')"
    while IFS= read -r holder; do
      if [[ -n "${holder}" && "${holder}" != "${DEMO_PROJECT}" ]]; then
        die "The development stack is up ('${holder}' publishes port ${port}); the demo needs the same ports. Stop it first (docker compose stop in the repository); its data is kept."
      fi
    done <<<"${holders}"
  done
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found on PATH: $1"
}
