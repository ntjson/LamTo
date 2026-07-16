#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
./tool/generate_api.sh
if ! git diff --quiet -- packages/lamto_api; then
  echo "ERROR: packages/lamto_api is stale. Run app/tool/generate_api.sh and commit." >&2
  git --no-pager diff --stat -- packages/lamto_api >&2
  exit 1
fi
echo "OK: generated API client matches the committed schema."
