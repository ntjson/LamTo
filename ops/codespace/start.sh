#!/usr/bin/env bash
# Every Codespace start (postStartCommand): bring the stack up in the
# background. ops/codespace/show.sh waits for it and prints the addresses.
set -euo pipefail
source "$(dirname "$0")/common.sh"
"${COMPOSE[@]}" up -d
