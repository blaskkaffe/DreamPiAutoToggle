#!/bin/sh
# Optional UI check (needs node + the playwright module + Chromium; not part of tests/run.sh):
#   sh tests/ui/run.sh          audit at four screen widths  and a functional check of the page, against the demo server
# Findings print as "<kind> | <state>: <element>"; screenshots go to /tmp/dpns-audit-*.png.
cd "$(dirname "$0")" || exit 1
export NODE_PATH=${NODE_PATH:-/opt/node22/lib/node_modules}
RESULT=0
run() {     # run <node script> <env...>: a demo server with that environment, the script against it
    script=$1; shift
    env "$@" PORT=8791 python3 demo_server.py > /tmp/dpns-demo-server.log 2>&1 &
    SERVER=$!
    sleep 3
    PORT=8791 node "$script" || RESULT=1
    kill $SERVER 2>/dev/null
    wait $SERVER 2>/dev/null
}
run audit.js IN=8 WIFIDEMO=1 FAKEUPDATE=1
run functional.js IN=0 WIFIDEMO=1 FAKEUPDATE=1
# the clock module has its own demo server (it is off in the one above so that the box counts stay as they are)
run clock.js CLOCK=1
# how the page appears (no pop-in) and the columns of Settings
run boot.js CLOCK=1
# the update controls: Check shows the Update now row at once, a finished update reloads the page with Settings open
run update.js FAKEUPDATE=1

# the screen layout (max columns, stretch, scale), rearranging the tiles and the PIN lock on Settings
run screen.js CLOCK=1
# the Background image module: choose a picture, fit, darken, a big one is shrunk, remove
run imagebg.js IMGBG=1
exit $RESULT
