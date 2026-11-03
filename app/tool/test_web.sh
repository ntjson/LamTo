#!/usr/bin/env bash
# Runs the widget tests whose behaviour differs on the web (ADR 0009) on the
# Chrome test platform. Those test files carry `@Tags(['web'])`; the rest of
# the suite only runs on the Dart VM (`flutter test`).
#
# Usage: from app/  ./tool/test_web.sh [extra flutter test args]
# Uses $CHROME_EXECUTABLE when set, else the machine's Chromium.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${CHROME_EXECUTABLE:-}" ]; then
  for candidate in chromium chromium-browser google-chrome; do
    if command -v "$candidate" >/dev/null 2>&1; then
      CHROME_EXECUTABLE="$(command -v "$candidate")"
      break
    fi
  done
fi
if [ -z "${CHROME_EXECUTABLE:-}" ]; then
  echo "No Chromium or Chrome found; set CHROME_EXECUTABLE." >&2
  exit 1
fi
export CHROME_EXECUTABLE

mapfile -t files < <(grep -rlF "@Tags(['web'])" test | sort)
if [ "${#files[@]}" -eq 0 ]; then
  echo "No test file is tagged @Tags(['web'])." >&2
  exit 1
fi

# GATE_READER_MODE is on so the web run proves the kiosk build mode stays off
# on the web whatever the build asks for.
flutter test --platform chrome --dart-define=GATE_READER_MODE=true \
  "$@" "${files[@]}"
