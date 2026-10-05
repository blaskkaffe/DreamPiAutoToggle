#!/bin/sh
# Optional UI check (needs node + the playwright module + Chromium; not part of tests/run.sh):
#   sh tests/ui/run.sh          audit at four screen widths and a functional check of the widgets, against the demo server
# Findings print as "<kind> | <state>: <element>"; screenshots go to /tmp/dpns-audit-*.png.
cd "$(dirname "$0")" || exit 1
PORT=${PORT:-8791}
export PORT
FAKEPLAYERS=1 FAKEUPDATE=1 WIFIDEMO=1 python3 demo_server.py > /tmp/dpns-demo-server.log 2>&1 &
SERVER=$!
sleep 3
NODE_PATH=${NODE_PATH:-/opt/node22/lib/node_modules} node audit.js
RESULT=$?
NODE_PATH=${NODE_PATH:-/opt/node22/lib/node_modules} node functional.js || RESULT=1
kill $SERVER 2>/dev/null
# the clock module has its own demo server (it is off in the one above so that the box counts stay as they are)
CLOCK=1 PORT=8735 python3 demo_server.py > /tmp/dpns-demo-clock.log 2>&1 &
SERVER=$!
sleep 3
PORT=8735 NODE_PATH=${NODE_PATH:-/opt/node22/lib/node_modules} node clock.js || RESULT=1
kill $SERVER 2>/dev/null
# the DC99 events module and the highlight: the sample events and one reminded event 5 minutes ahead
CLOCK=1 EVENTS=1 EVENTSOON=1 PORT=8736 python3 demo_server.py > /tmp/dpns-demo-events.log 2>&1 &
SERVER=$!
sleep 3
PORT=8736 NODE_PATH=${NODE_PATH:-/opt/node22/lib/node_modules} node events.js || RESULT=1
kill $SERVER 2>/dev/null
# the online players while the list is fetched again (slow downloads: the box keeps its state, a spinner shows)
FAKEPLAYERS=1 PLAYERSFAST=1 PORT=8737 python3 demo_server.py > /tmp/dpns-demo-players.log 2>&1 &
SERVER=$!
sleep 3
PORT=8737 NODE_PATH=${NODE_PATH:-/opt/node22/lib/node_modules} node players.js || RESULT=1
kill $SERVER 2>/dev/null
# the Dreamcast background covers the window in portrait, landscape and after turning
BG=1 PORT=8738 python3 demo_server.py > /tmp/dpns-demo-bg.log 2>&1 &
SERVER=$!
sleep 3
PORT=8738 NODE_PATH=${NODE_PATH:-/opt/node22/lib/node_modules} node background.js || RESULT=1
kill $SERVER 2>/dev/null
# the update controls: Check shows the Update now row at once, a finished update reloads the page with Settings open
FAKEUPDATE=1 PORT=8739 python3 demo_server.py > /tmp/dpns-demo-update.log 2>&1 &
SERVER=$!
sleep 3
PORT=8739 NODE_PATH=${NODE_PATH:-/opt/node22/lib/node_modules} node update.js || RESULT=1
kill $SERVER 2>/dev/null
# the openMenu link box: the card's games with a search, the players to join, the events, Start asking first
OPENMENU=1 FAKEPLAYERS=1 PORT=8740 python3 demo_server.py > /tmp/dpns-demo-openmenu.log 2>&1 &
SERVER=$!
sleep 3
PORT=8740 NODE_PATH=${NODE_PATH:-/opt/node22/lib/node_modules} node openmenu.js || RESULT=1
kill $SERVER 2>/dev/null
exit $RESULT
