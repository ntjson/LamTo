# Shared by the Codespaces demo scripts. Sourced, not run.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"
COMPOSE=(docker compose -f ops/trial/compose.yaml -f ops/codespace/compose.yaml)
PUBLIC_HOST="${CODESPACE_NAME:-localhost}-80.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
REPO="${GITHUB_REPOSITORY:-ntjson/LamTo}"
WEB_RELEASE_URL="${WEB_RELEASE_URL:-https://github.com/${REPO}/releases/download/demo-web/lamto-web.tar.gz}"
