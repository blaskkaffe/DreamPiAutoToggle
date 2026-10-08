#!/bin/bash
# kiosk-browser.sh - starts Chromium full screen on a check-in board, for a screen that is only a display (and a touch input, if it has one).
# The host (the computer that ran install.sh) keeps everything; this machine only opens its address, so every screen is in step.
#
# Usage:
#   ./kiosk-browser.sh                      # the host is this machine
#   ./kiosk-browser.sh 192.168.1.20         # the host is another machine (add :port when it is not 80)
#   ./kiosk-browser.sh 192.168.1.20 "Område A"          # this screen shows only that building
#   ./kiosk-browser.sh 192.168.1.20 "Område A,Område B" # or several buildings (comma, no space after it)
#
# Spell the buildings as on the board's own building buttons. Leave the second argument out to show everybody.
# The browser is restarted whenever it stops. Add the script to the desktop's autostart so the board comes back after a power cut (kiosk/checkin-kiosk-autostart.desktop).

HOST="${1:-localhost}"
BUILDINGS="${2:-}"
URL="http://${HOST}/"
if [ -n "$BUILDINGS" ]; then
  URL="${URL}?location=${BUILDINGS// /+}"
fi

# --disable-pinch and --overscroll-history-navigation=0 stop stray touches from zooming or going back.
# If the browser crashes or is closed it is started again after two seconds (a crash must never leave the screen empty).
BROWSER=$(command -v chromium-browser || command -v chromium)
while true; do
  "$BROWSER" \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --hide-crash-restore-bubble \
    --disable-pinch \
    --overscroll-history-navigation=0 \
    --incognito \
    "$URL"
  sleep 2
done
