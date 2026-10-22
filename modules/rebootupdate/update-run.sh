#!/bin/sh
# Check-in add-on - the updater. Started as root by systemd (checkin-board-update@git.service / @usb.service, written by this module's
# install.sh); the web service is an ordinary user and may only ask systemd to start that unit. So nothing the web service writes is trusted here:
# the checkout, its origin and the ports come from files only root can write (install.sh records them), and the USB stick is looked for here.
#   update-run.sh git   fast-forward the recorded checkout from its recorded GitHub origin and run its install.sh
#   update-run.sh usb   copy the "update" folder of a USB stick away and run its install.sh
# Progress is written to $RUN/state.update ("running", "ok", "failed") and $RUN/state.update.log, which the page shows.
# The variables CHECKIN_* are for the tests; a unit started by systemd has none of them.
CODE=${CHECKIN_INSTALL_DIR:-/opt/checkin-board}
RUN=${CHECKIN_UPDATE_DIR:-/run/checkin-board-update}
MODE=${1:-}
PROTOCOLS=${CHECKIN_GIT_PROTOCOLS:-https:ssh}
ORIGIN_RE=${CHECKIN_ORIGIN_RE:-'^(https://github\.com/|git@github\.com:|ssh://git@github\.com/)[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(\.git)?/?$'}
umask 022
mkdir -p "$RUN"
L="$RUN/state.update.log"; ST="$RUN/state.update"
rm -f "$L" "$ST"; set -C                      # never write through a link someone left in the folder
exec >"$L" 2>&1
echo running > "$ST"
fail() { echo "$*"; echo failed >| "$ST"; exit 1; }

PORTS=""
if [ -f "$CODE/install_ports" ]; then
    read -r HTTP HTTPS < "$CODE/install_ports"
    case "$HTTP$HTTPS" in ''|*[!0-9]*) ;; *) PORTS="$HTTP --https-port=$HTTPS" ;; esac
fi

case "$MODE" in
git)
    S=$(cat "$CODE/src_dir" 2>/dev/null); O=$(cat "$CODE/update_origin" 2>/dev/null)
    printf '%s' "$S" | grep -Eq '^/[A-Za-z0-9._/+@=-]+$' && [ -d "$S" ] && [ -f "$S/install.sh" ] || fail "No usable checkout is recorded"
    case "$S" in *..*) fail "Unsafe checkout folder" ;; esac
    printf '%s' "$O" | grep -Eq "$ORIGIN_RE" || fail "The recorded update address is not a GitHub address"
    OWNER=$(stat -c %U "$S")
    if [ "$OWNER" != root ] && [ "$(id -u)" = 0 ]; then G="runuser -u $OWNER -- env GIT_ALLOW_PROTOCOL=$PROTOCOLS git"; else G="env GIT_ALLOW_PROTOCOL=$PROTOCOLS git"; fi
    G="$G -c safe.directory=$S -C $S"
    NOW=$($G config --get remote.origin.url) || fail "Could not read the checkout's git origin"
    [ "$NOW" = "$O" ] || fail "The checkout's git origin changed since the add-on was installed (run install.sh by hand to accept it)"
    B=$($G rev-parse --abbrev-ref HEAD 2>/dev/null)
    printf '%s' "$B" | grep -Eq '^[A-Za-z0-9._/][A-Za-z0-9._/-]*$' && [ "$B" != HEAD ] && case "$B" in *..*|*/) false ;; *) true ;; esac || B=main
    echo "Updating $S from origin/$B"
    $G fetch "$O" "$B" && $G merge --ff-only FETCH_HEAD || fail "Could not fetch and merge"
    cd "$S" && sh "$S/install.sh" $PORTS && echo ok >| "$ST" || fail "The installer failed"
    ;;
usb)
    BEST=""
    scan() {      # the folders called "update" that look like the add-on; the newest install.sh wins. (Names may have spaces: the patterns are expanded by the caller.)
        for D in "$@"; do
            [ -d "$D" ] && [ ! -L "$D" ] && [ -f "$D/install.sh" ] && [ ! -L "$D/install.sh" ] && [ -f "$D/base/base_web.py" ] && [ -d "$D/modules" ] || continue
            if [ -z "$BEST" ] || [ "$D/install.sh" -nt "$BEST/install.sh" ]; then BEST="$D"; fi
        done
    }
    if [ -n "${CHECKIN_USB_ROOT:-}" ]; then scan "$CHECKIN_USB_ROOT"/*/update
    else scan /media/*/update /media/*/*/update /run/media/*/*/update /mnt/*/update /mnt/*/*/update; fi
    [ -n "$BEST" ] || fail "No USB stick with an update folder was found"
    STAMP=$(date -d "@$(stat -c %Y "$BEST/install.sh")" '+%Y-%m-%d %H:%M' 2>/dev/null || date '+%Y-%m-%d %H:%M')
    W="$CODE/usb_src"
    echo "Copying the update from $BEST"
    rm -rf "$W.new" && cp -r "$BEST" "$W.new" && [ -f "$W.new/install.sh" ] && rm -rf "$W" && mv "$W.new" "$W" || fail "Could not copy the update"
    cd "$W" && NS_KEEP_SRC=1 NS_VERSION="USB update $STAMP" sh "$W/install.sh" $PORTS && echo ok >| "$ST" || fail "The installer failed"
    ;;
*)
    fail "Usage: update-run.sh git|usb"
    ;;
esac
