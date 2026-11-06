#!/usr/bin/env bash
# Codespace creation (postCreateCommand): fetch the pre-built Resident app,
# build the demo kit page, write the settings once, build the image.
set -euo pipefail
source "$(dirname "$0")/common.sh"

echo "== Downloading the Resident app (web build)"
rm -rf ops/trial/site/app
mkdir -p ops/trial/site/app
curl -fsSL "${WEB_RELEASE_URL}" | tar -xz -C ops/trial/site/app

echo "== Building the demo kit page"
python3 -I ops/demo/demo_up.py kit-site ops/demo-kit/files ops/trial/site/demo-kit >/dev/null

echo "== Writing settings for ${PUBLIC_HOST}"
python3 -I ops/trial/make_env.py ops/trial/trial.env "${PUBLIC_HOST}"

echo "== Building the server image"
"${COMPOSE[@]}" build
"${COMPOSE[@]}" pull --quiet db minio minio-init caddy
