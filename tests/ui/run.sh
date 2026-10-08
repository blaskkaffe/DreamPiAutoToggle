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
run audit.js IN=8 FAKEUPDATE=1
run functional.js IN=0 FAKEUPDATE=1
# how the page appears (no pop-in) and the columns of Settings
run boot.js
# the update controls: Check shows the Update now row at once, a finished update reloads the page with Settings open
run update.js FAKEUPDATE=1
# an update from a USB stick that has an update folder
run usb.js FAKEUPDATE=1 USB=1

# the screen layout (max columns, stretch, scale), rearranging the tiles and the PIN lock on Settings
run screen.js
# the Background image module: choose a picture, fit, darken, a big one is shrunk, remove
run imagebg.js IMGBG=1
# a group too long for one column is split over the next ones; No scrolling; the saved order of the boxes
run columns.js PEOPLE=$(pwd)/long.csv
# the Colour palette module: add, edit, rearrange, delete and reset colours; the rest of the page follows at once
run palette.js
# the look: text colour and size, Classic boxes, corners and gaps, theme by the time of day, button sounds, the Snow background
run look.js IN=6
# a tall screen (1080 x 1920) with two columns: 20, 40, 60 and 80 people in groups of 1 to 15 (mostly 6 to 12)
for N in 20 40 60 80; do
    python3 make_people.py $N > /tmp/dpns-people-$N.csv
    export N
    run portrait.js PEOPLE=/tmp/dpns-people-$N.csv
done
exit $RESULT
