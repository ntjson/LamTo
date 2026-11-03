#!/usr/bin/env bash
# Bring the demo up at the venue, and say when it is safe to hand to the visitor.
#
#   ops/demo/up.sh
#
# In order it:
#   1. refuses to run while the development stack holds the ports, or when the
#      web build is missing or a key fingerprint changed since the reset
#   2. starts the demo's compose services without recreating ClamAV, and waits
#      until ClamAV answers
#   3. starts gunicorn, the worker, Caddy and a Cloudflare quick tunnel
#   4. reads the tunnel's address
#   5. runs the smoke check through that address
#   6. only then shows the address and a terminal QR code for /app/
#
# Ctrl-C (or SIGTERM) stops everything this script started. The containers keep
# running.
#
# Optional environment: CADDY_PORT (8080), GUNICORN_PORT (8000),
# DEMO_CLAMAV_TIMEOUT (300 s), DEMO_TUNNEL_TIMEOUT (60 s),
# DEMO_TUNNEL_URL_PATTERN (a regex for the address in cloudflared's log, for a
# cloudflared that prints it differently).
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
cd "${ROOT_DIR}"

export CADDY_PORT="${CADDY_PORT:-8080}"
export GUNICORN_PORT="${GUNICORN_PORT:-8000}"
RUN_DIR="${DEMO_DIR}/run"
KIT_SITE="${DEMO_DIR}/kit"

PIDS=()
NAMES=()
READY=0
STOPPING=0

# Each process gets its own session, so stopping it stops its children too
# (gunicorn's workers).
start_process() {
  local name="$1"
  shift
  setsid "$@" >"${RUN_DIR}/${name}.log" 2>&1 &
  PIDS+=("$!")
  NAMES+=("${name}")
  printf -v "PID_${name}" '%s' "$!"
}

stop_processes() {
  [[ ${#PIDS[@]} -gt 0 ]] || return 0
  local i pid deadline
  for ((i = ${#PIDS[@]} - 1; i >= 0; i--)); do
    kill -TERM -- "-${PIDS[i]}" 2>/dev/null || true
  done
  deadline=$((SECONDS + 10))
  for pid in "${PIDS[@]}"; do
    while kill -0 -- "-${pid}" 2>/dev/null && ((SECONDS < deadline)); do
      sleep 0.2
    done
    kill -KILL -- "-${pid}" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  PIDS=()
}

on_exit() {
  local status=$?
  # Stopping takes a moment; a second Ctrl-C must not cut it short and leave
  # the (separate-session) processes running.
  trap - EXIT
  trap '' INT TERM
  if [[ ${STOPPING} -eq 0 && ${status} -ne 0 ]]; then
    log "Demo not started (stopped at step: ${STEP})."
  fi
  stop_processes
  if [[ ${READY} -eq 1 && ${status} -eq 0 ]]; then
    log "Stopped gunicorn, the worker, Caddy and cloudflared. The containers are still running."
  fi
}
trap on_exit EXIT
on_signal() {
  STOPPING=1
  log ""
  if [[ ${READY} -eq 1 ]]; then exit 0; else exit 130; fi
}
trap on_signal INT TERM

wait_for_port() {
  local port="$1" seconds="$2" i
  for ((i = 0; i < seconds * 5; i++)); do
    if (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

fail_with_log() {
  local name="$1" message="$2"
  log "---- last lines of ${RUN_DIR}/${name}.log"
  tail -n 15 "${RUN_DIR}/${name}.log" >&2 || true
  die "${message}"
}

# ---------------------------------------------------------------------------
step preflight "Checking the machine"

for tool in docker caddy cloudflared "${PYTHON}"; do
  require_cmd "${tool}"
done
"${PYTHON}" -c 'import gunicorn, qrcode' 2>/dev/null \
  || die "gunicorn and qrcode must be installed in ${PYTHON}'s environment (uv sync)."

refuse_if_dev_stack_up

[[ -f "${DEMO_ENV_FILE}" ]] \
  || die "There is no demo environment file (${DEMO_ENV_FILE}). Run ops/demo/reset.sh at home first."

set -a
# shellcheck disable=SC1090
source "${DEMO_ENV_FILE}"
set +a
# Fixtures are for the seed command alone, never for the servers.
unset PILOT_ALLOW_FIXTURES

for name in CLAMAV_HOST CLAMAV_PORT STATIC_ROOT APP_WEB_ROOT; do
  [[ -n "${!name:-}" ]] || die "${name} is not set in ${DEMO_ENV_FILE}. Delete the file and run ops/demo/reset.sh to have it regenerated."
done

step build "Checking the web build and the key fingerprints"

[[ -f "${APP_WEB_ROOT}/index.html" ]] \
  || die "The web build is missing (no index.html in '${APP_WEB_ROOT}'). Run ops/demo/reset.sh at home."

"${PYTHON}" -I ops/demo/demo_env.py verify-fingerprints "${DEMO_ENV_FILE}" "${DEMO_DIR}/fingerprints" \
  || die "The keys are not the ones the demo data was made with (see above)."

busy="$("${PYTHON}" -I ops/demo/demo_up.py ports-free "${CADDY_PORT}" "${GUNICORN_PORT}" 2>&1)" \
  || die "Port(s) ${busy} are already in use. Is another demo (or something else) running?"

mkdir -p "${RUN_DIR}"

# ---------------------------------------------------------------------------
step services "Starting the compose services (ClamAV is never recreated)"

compose up -d --wait --no-recreate db minio
compose up -d --no-recreate clamav

step clamav "Waiting for ClamAV (it loads its signatures first, which can take minutes)"
"${PYTHON}" -I ops/demo/demo_up.py wait-clamav "${CLAMAV_HOST}:${CLAMAV_PORT}" \
  --timeout "${DEMO_CLAMAV_TIMEOUT:-300}" \
  || die "ClamAV did not answer on ${CLAMAV_HOST}:${CLAMAV_PORT}. Check: docker logs ${DEMO_PROJECT}-clamav-1"
log "ClamAV answers."

# ---------------------------------------------------------------------------
step processes "Starting gunicorn, the worker, Caddy and the tunnel"

"${PYTHON}" -I ops/demo/demo_up.py kit-site ops/demo-kit/files "${KIT_SITE}" >/dev/null

log "Starting gunicorn on 127.0.0.1:${GUNICORN_PORT}"
start_process gunicorn "${PYTHON}" -m gunicorn --config ops/gunicorn.conf.py lamto.config.wsgi:application

log "Starting the worker"
start_process worker "${PYTHON}" manage.py run_worker

log "Starting Caddy on 127.0.0.1:${CADDY_PORT}"
start_process caddy env \
  "XDG_DATA_HOME=${RUN_DIR}/caddy-data" "XDG_CONFIG_HOME=${RUN_DIR}/caddy-config" \
  "CADDY_EXTRA_ROUTES=${ROOT_DIR}/ops/demo/demo-kit.caddy" "DEMO_KIT_ROOT=${KIT_SITE}" \
  caddy run --config ops/Caddyfile --adapter caddyfile

log "Starting the Cloudflare quick tunnel"
start_process cloudflared cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:${CADDY_PORT}"

wait_for_port "${GUNICORN_PORT}" 60 || fail_with_log gunicorn "gunicorn is not answering on port ${GUNICORN_PORT}."
wait_for_port "${CADDY_PORT}" 30 || fail_with_log caddy "Caddy is not answering on port ${CADDY_PORT}."

# ---------------------------------------------------------------------------
step tunnel "Reading the tunnel address"

address="$("${PYTHON}" -I ops/demo/demo_up.py tunnel-address "${RUN_DIR}/cloudflared.log" \
  --timeout "${DEMO_TUNNEL_TIMEOUT:-60}")" \
  || fail_with_log cloudflared "cloudflared did not report a tunnel address."
log "Tunnel address: ${address}"

# ---------------------------------------------------------------------------
step smoke "Running the smoke check through ${address}"

"${PYTHON}" -I ops/demo/demo_up.py smoke "${address}" \
  --app-root "${APP_WEB_ROOT}" --static-root "${STATIC_ROOT}" --kit-dir "${KIT_SITE}" \
  --clamav "${CLAMAV_HOST}:${CLAMAV_PORT}" --worker-pid "${PID_worker}" >&2 \
  || die "The smoke check failed, so the demo is not ready to hand over. Logs: ${RUN_DIR}/"

# ---------------------------------------------------------------------------
step ready "Ready"

# From here a Ctrl-C is a normal end of the visit, not a failed start.
READY=1
"${PYTHON}" -I ops/demo/demo_up.py show-address "${address}"
log ""
log "The demo is ready. Press Ctrl-C to stop it (the containers keep running)."

while true; do
  for i in "${!PIDS[@]}"; do
    if ! kill -0 "${PIDS[i]}" 2>/dev/null; then
      READY=0
      STOPPING=1  # fail_with_log reports it; this is not a failed start
      fail_with_log "${NAMES[i]}" "${NAMES[i]} stopped unexpectedly; stopping the rest."
    fi
  done
  sleep 1
done
