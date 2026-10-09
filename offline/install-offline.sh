#!/bin/bash
# install-offline.sh - run on the computer WITHOUT internet, in the bundle folder made by prepare-offline.sh.
#
#   sudo ./install-offline.sh [--packages-only] [--board] [--pxe]
#
#   (nothing)         install the packages of packages.txt from the bundle's local repository (python3, openssl, git, Firefox, Chromium, mpv, dnsmasq-base, ipxe ...)
#   --board           then install the check-in board (repo/install.sh; pass its options after --, e.g. --board -- --pin)
#   --pxe             then set up the network boot server (repo/pxe/install-pxe.sh) with the bundle's image (needs the bundle made with --with-image)
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
BOARD=no
PXE=no
BOARD_ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --packages-only) ;;
        --board) BOARD=yes ;;
        --pxe) PXE=yes ;;
        --) shift; BOARD_ARGS=("$@"); break ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
    shift
done
[ "$(id -u)" = 0 ] || { echo "Run as root: sudo $0" >&2; exit 1; }
[ -f "$HERE/debs/Packages.gz" ] || { echo "$HERE/debs/Packages.gz is missing: run this inside the bundle folder" >&2; exit 1; }

PKGS=$(sed -e 's/#.*//' -e '/^[[:space:]]*$/d' "$HERE/packages.txt" | tr -s ' \n' ' ')
. /etc/os-release
if [ "${ID:-}" = ubuntu ]; then
    PKGS=$(echo "$PKGS" | tr ' ' '\n' | grep -vxE 'firefox-esr|chromium' | tr '\n' ' ')
fi

# apt reads only the bundle: its own sources list, and its lists kept in a temporary folder
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/lists/partial" "$TMP/sources.d"
echo "deb [trusted=yes] file:$HERE/debs ./" > "$TMP/sources.list"
APT=(apt-get -o "Dir::Etc::sourcelist=$TMP/sources.list" -o "Dir::Etc::sourceparts=$TMP/sources.d" -o "Dir::State::lists=$TMP/lists" -o "APT::Get::List-Cleanup=0")

echo "== installing the packages from the bundle"
"${APT[@]}" update
"${APT[@]}" install -y --no-install-recommends $PKGS

if [ -d "$HERE/snaps" ]; then
    echo "== snaps"
    for f in "$HERE"/snaps/*.assert; do [ -f "$f" ] && snap ack "$f"; done
    for f in "$HERE"/snaps/*.snap; do [ -f "$f" ] && snap install "$f"; done
fi

if [ "$BOARD" = yes ]; then
    echo "== the check-in board"
    (cd "$HERE/repo" && ./install.sh ${BOARD_ARGS[@]+"${BOARD_ARGS[@]}"})
fi
if [ "$PXE" = yes ]; then
    [ -f "$HERE/image/filesystem.squashfs" ] || { echo "The bundle has no image (prepare-offline.sh --with-image)" >&2; exit 1; }
    echo "== the network boot server"
    "$HERE/repo/pxe/install-pxe.sh" --image="$HERE/image"
fi
echo "Done."
