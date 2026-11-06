#!/usr/bin/env bash
# When the judge's window opens (postAttachCommand), and any time after:
#
#   bash ops/codespace/show.sh
#
# Waits until the demo answers, makes its port public so a phone can open it
# without a GitHub login, then prints the addresses, the logins and a QR code.
set -uo pipefail
source "$(dirname "$0")/common.sh"

echo "Starting the LamTo demo. The first start takes a few minutes..."
for _ in $(seq 1 180); do
  curl -fsS -o /dev/null http://localhost:80/api/v1/registration/options && break
  sleep 3
done
if ! curl -fsS -o /dev/null http://localhost:80/api/v1/registration/options; then
  echo "The demo did not come up. Logs: docker compose -f ops/trial/compose.yaml logs app" >&2
  exit 1
fi

if ! gh codespace ports visibility 80:public -c "${CODESPACE_NAME:-}" >/dev/null 2>&1; then
  PORT_NOTE="Open the PORTS tab, right-click port 80, choose Port Visibility > Public."
fi

BASE="https://${PUBLIC_HOST}"
"${COMPOSE[@]}" exec -T app python -c "
import qrcode, sys
qr = qrcode.QRCode(border=1)
qr.add_data(sys.argv[1])
qr.print_ascii(invert=True)
" "${BASE}/app/"

cat <<TEXT

  LamTo demo is ready.

  On your phone   scan the QR code above, or open ${BASE}/app/
  On your laptop  Management workspace: ${BASE}/s/
                  Demo kit (quotation, Transfer proof): ${BASE}/demo-kit/

TEXT
"${COMPOSE[@]}" exec -T app sed -n '/Logins/,$p' /srv/static/.logins.txt | sed 's/^/  /'
cat <<TEXT

  ${PORT_NOTE:-}
  Keep this browser tab open: GitHub stops a Codespace after 30 minutes
  without activity in this window. Run "bash ops/codespace/show.sh" to see
  this again.
TEXT
