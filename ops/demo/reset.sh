#!/usr/bin/env bash
# Put the demo back into a clean state and prepare everything the venue needs.
# Run at home, before a visit:
#
#   ops/demo/reset.sh
#
# In order it:
#   1. creates the demo environment file (first run only)
#   2. archives the previous visit's database
#   3. wipes the demo's Postgres and MinIO volumes, and only those
#   4. migrates and seeds the demo building
#   5. builds the Resident app for the web and pre-compresses it
#   6. collects static files
#   7. records the key fingerprints that `up.sh` checks
#
# It is safe to run again, and it stops at the first step that fails.
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
cd "${ROOT_DIR}"

trap 'status=$?; [[ ${status} -eq 0 ]] || log "Reset stopped at step: ${STEP}"' EXIT

# ---------------------------------------------------------------------------
step preflight "Checking the machine"

for tool in docker flutter gzip brotli "${PYTHON}"; do
  require_cmd "${tool}"
done

refuse_if_dev_stack_up

# ---------------------------------------------------------------------------
step env "Demo environment file"

"${PYTHON}" -I ops/demo/demo_env.py init-env "${DEMO_ENV_FILE}" \
  --static-root "${DEMO_DIR}/static" --app-web-root "${DEMO_DIR}/app"

set -a
# shellcheck disable=SC1090
source "${DEMO_ENV_FILE}"
set +a
# Fixtures are switched on for the seed command alone, never for the servers.
unset PILOT_ALLOW_FIXTURES

# Both are deleted and refilled below, and they come from an editable file:
# insist they sit strictly inside the demo directory, before anything is wiped.
for name in APP_WEB_ROOT STATIC_ROOT; do
  path="${!name:-}"
  case "${path}" in
    "${DEMO_DIR}"/* ) ;;
    *) die "${name} in ${DEMO_ENV_FILE} is '${path}', outside ${DEMO_DIR}. Delete the file to have it regenerated." ;;
  esac
  case "${path}/" in
    */../* | */./* | *//*) die "${name} in ${DEMO_ENV_FILE} is '${path}'; it must be a plain absolute path." ;;
  esac
done

# ---------------------------------------------------------------------------
step archive "Archiving the previous visit's database"

if docker volume inspect "${DEMO_PROJECT}_postgres-data" >/dev/null 2>&1; then
  mkdir -p "${DEMO_DIR}/archive"
  compose up -d --wait db
  partial="${DEMO_DIR}/archive/.partial-$$"
  # The dump holds real data: readable by this user only.
  if ! (umask 077; compose exec -T db pg_dump -U lamto_bootstrap -d lamto -Fc >"${partial}"); then
    rm -f "${partial}"
    die "Could not dump the previous visit's database; nothing was wiped."
  fi
  archive="${DEMO_DIR}/archive/lamto-$(date +%Y%m%d-%H%M%S).dump"
  mv "${partial}" "${archive}"
  log "Saved ${archive}"
else
  log "No demo database yet; nothing to archive."
fi

# ---------------------------------------------------------------------------
step wipe "Wiping the demo's Postgres and MinIO volumes"

# From here the old key fingerprints no longer describe what is on disk.
rm -f "${DEMO_DIR}/fingerprints"

compose rm -sf db minio minio-init
wiped=()
for volume in postgres-data minio-data; do
  if docker volume inspect "${DEMO_PROJECT}_${volume}" >/dev/null 2>&1; then
    wiped+=("${DEMO_PROJECT}_${volume}")
  fi
done
# The ClamAV volume, with its downloaded signatures, is deliberately not listed.
if [[ ${#wiped[@]} -gt 0 ]]; then
  docker volume rm "${wiped[@]}"
fi

step services "Starting Postgres, MinIO and ClamAV"
compose up -d --wait db
compose run --rm -T minio-init
compose up -d --no-recreate clamav

# ---------------------------------------------------------------------------
step migrate "Migrating"
POSTGRES_USER=lamto_owner POSTGRES_PASSWORD=lamto-owner \
  "${PYTHON}" manage.py migrate --noinput

step seed "Seeding the demo building"
PILOT_ALLOW_FIXTURES=1 "${PYTHON}" manage.py seed_demo

# ---------------------------------------------------------------------------
step build "Building the Resident app for the web"

(cd "${APP_DIR}" && flutter build web --release --base-href /app/)
[[ -f "${APP_DIR}/build/web/index.html" ]] || die "The web build left no index.html."

rm -rf "${APP_WEB_ROOT}"
mkdir -p "${APP_WEB_ROOT}"
cp -a "${APP_DIR}/build/web/." "${APP_WEB_ROOT}/"

# Caddy serves these .gz and .br copies when the client accepts them. Images
# and the like are already compressed and are left out.
find "${APP_WEB_ROOT}" -type f \
  \( -name '*.js' -o -name '*.mjs' -o -name '*.wasm' -o -name '*.json' -o -name '*.html' \
  -o -name '*.css' -o -name '*.svg' -o -name '*.ttf' -o -name '*.otf' -o -name '*.bin' \
  -o -name '*.txt' -o -name '*.map' \) \
  -exec gzip -9 -kf {} + \
  -exec brotli -fk -q 11 {} +

# ---------------------------------------------------------------------------
step static "Collecting static files"
"${PYTHON}" manage.py collectstatic --noinput --clear

# ---------------------------------------------------------------------------
step fingerprints "Recording key fingerprints"

mkdir -p "${DEMO_DIR}"
"${PYTHON}" -I ops/demo/demo_env.py fingerprints "${DEMO_ENV_FILE}" >"${DEMO_DIR}/fingerprints.partial"
mv "${DEMO_DIR}/fingerprints.partial" "${DEMO_DIR}/fingerprints"

STEP="done"
log ""
log "Demo reset. Logins are printed above (from the seed). At the venue: ops/demo/up.sh"
