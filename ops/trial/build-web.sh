#!/usr/bin/env bash
# Build the Resident app for the web from the last commit (HEAD), never the
# working tree, into ops/trial/site/app, with .br and .gz copies for Caddy.
#
#   ops/trial/build-web.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="${ROOT}/ops/trial/site/app"
WT="$(mktemp -d)"
trap 'git -C "${ROOT}" worktree remove --force "${WT}" >/dev/null 2>&1 || true' EXIT

echo "Building the Resident app for the web from $(git -C "${ROOT}" rev-parse --short HEAD)"
git -C "${ROOT}" worktree add --detach "${WT}" HEAD >/dev/null
(cd "${WT}/app" && flutter pub get >/dev/null && flutter build web --release --base-href /app/)

rm -rf "${DEST}"
mkdir -p "${DEST}"
cp -a "${WT}/app/build/web/." "${DEST}/"
find "${DEST}" -type f \
  \( -name '*.js' -o -name '*.mjs' -o -name '*.wasm' -o -name '*.json' -o -name '*.html' \
  -o -name '*.css' -o -name '*.svg' -o -name '*.ttf' -o -name '*.otf' -o -name '*.bin' \
  -o -name '*.txt' -o -name '*.map' \) \
  -exec gzip -9 -kf {} + \
  -exec brotli -fk -q 11 {} +
git -C "${ROOT}" rev-parse HEAD >"${DEST}/.built-from"
