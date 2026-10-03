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
exit $RESULT
