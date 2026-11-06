#!/usr/bin/env bash
# Publish the Resident app's web build as the `demo-web` release asset the
# Codespaces demo downloads (ops/codespace/prepare.sh). Run after any change
# to the app that should reach the demo:
#
#   ops/codespace/publish-web.sh [--skip-build]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
[[ "${1:-}" == "--skip-build" ]] || "${ROOT}/ops/trial/build-web.sh"
SITE="${ROOT}/ops/trial/site/app"
OUT="$(mktemp -d)/lamto-web.tar.gz"
tar -czf "${OUT}" -C "${SITE}" .
SHA="$(cat "${SITE}/.built-from" 2>/dev/null || git -C "${ROOT}" rev-parse HEAD)"
NOTES="Pre-built Resident app (web) for the Codespaces demo, built from ${SHA}."
if gh release view demo-web >/dev/null 2>&1; then
  gh release upload demo-web "${OUT}" --clobber
  gh release edit demo-web --notes "${NOTES}"
else
  gh release create demo-web "${OUT}" --prerelease --title "Demo web build" --notes "${NOTES}"
fi
echo "Published lamto-web.tar.gz (${SHA:0:7})."
