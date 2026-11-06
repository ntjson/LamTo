#!/usr/bin/env bash
# Deploy the unattended trial to a server you can SSH into.
#
#   ops/trial/deploy.sh ubuntu@203.0.113.7 [--key ~/.ssh/oracle] [--skip-web]
#
# 1. builds the Resident app for the web from the last commit (HEAD), not the
#    working tree, so unfinished app work is never shipped
# 2. copies the server code, the web build and the demo kit to ~/lamto
# 3. on the server: writes ops/trial/trial.env once (keys minted there),
#    builds the image and starts everything with `docker compose up -d`
# 4. prints the address and the demo logins
#
# Run ops/trial/server-setup.sh on the server once before the first deploy.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TARGET="${1:?usage: deploy.sh user@host [--key FILE] [--skip-web]}"
shift
SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
SKIP_WEB=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --key) SSH_OPTS+=(-i "$2"); shift 2 ;;
    --skip-web) SKIP_WEB=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
HOST_IP="${TARGET#*@}"
TRIAL_HOST="${TRIAL_HOST:-${HOST_IP//./-}.sslip.io}"
SITE="${ROOT}/ops/trial/site"

log() { printf '\n== %s\n' "$*"; }

if [[ "${SKIP_WEB}" == 0 ]]; then
  log "Building the Resident app for the web"
  "${ROOT}/ops/trial/build-web.sh"
fi
[[ -f "${SITE}/app/index.html" ]] || { echo "No web build in ${SITE}/app; drop --skip-web." >&2; exit 1; }

log "Building the demo kit page"
python3 -I "${ROOT}/ops/demo/demo_up.py" kit-site \
  "${ROOT}/ops/demo-kit/files" "${SITE}/demo-kit" >/dev/null

log "Copying to ${TARGET}:~/lamto"
rsync -az --delete -e "ssh ${SSH_OPTS[*]}" \
  --exclude '.git/' --exclude '.venv/' --exclude 'node_modules/' --exclude '.demo/' \
  --exclude '.worktrees/' --exclude '.scratch/' --exclude '__pycache__/' \
  --exclude '.pytest_cache/' --exclude '.playwright-mcp/' --exclude '.env*' \
  --exclude '/app/' --exclude '/chain/' --exclude '/tests/' --exclude '/docs/' \
  --exclude 'ops/trial/trial.env' \
  "${ROOT}/" "${TARGET}:lamto/"

log "Starting the stack on the server (the first build takes several minutes)"
# shellcheck disable=SC2029
ssh "${SSH_OPTS[@]}" "${TARGET}" "TRIAL_HOST='${TRIAL_HOST}' bash -s" <<'REMOTE'
set -euo pipefail
cd ~/lamto
python3 -I ops/trial/make_env.py ops/trial/trial.env "${TRIAL_HOST}"
docker compose -f ops/trial/compose.yaml up -d --build --remove-orphans
for _ in $(seq 1 120); do
  docker compose -f ops/trial/compose.yaml exec -T app test -f /srv/static/.logins.txt 2>/dev/null && break
  sleep 5
done
HOST="$(grep '^TRIAL_HOST=' ops/trial/trial.env | cut -d= -f2)"
for _ in $(seq 1 60); do
  curl -fsS -o /dev/null "https://${HOST}/api/v1/registration/options" && break
  sleep 5
done
echo
docker compose -f ops/trial/compose.yaml ps --format 'table {{.Service}}\t{{.Status}}'
echo
echo "Resident app:          https://${HOST}/app/"
echo "Management workspace:  https://${HOST}/s/"
echo "Demo kit:              https://${HOST}/demo-kit/"
echo
docker compose -f ops/trial/compose.yaml exec -T app cat /srv/static/.logins.txt
REMOTE
