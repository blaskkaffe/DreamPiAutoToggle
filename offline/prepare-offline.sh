#!/bin/bash
# prepare-offline.sh - run on a computer WITH internet. Collects everything a computer without internet needs into one folder (the bundle):
# the packages from offline/packages.txt with all they depend on (as a small local apt repository), a copy of this repository, and
# optionally the network boot image. Carry the folder over on a USB disk and run install-offline.sh in it.
#
#   sudo ./offline/prepare-offline.sh [--with-image] [--out=DIR]
#
#   --with-image   also build the network boot image (pxe/build-image.sh: needs debootstrap and about 1 GB of downloads, takes a few minutes)
#   --no-snaps     on Ubuntu: leave Firefox and Chromium (snaps) out of the bundle
#   --out=DIR      where the bundle is made (default: offline/bundle)
#
# The online computer must run the SAME distribution, release and CPU type as the offline one (Debian 12 on both, say): the packages are
# the ones of the release it runs. On Ubuntu Firefox and Chromium are snaps: they are fetched with "snap download" instead.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(dirname "$HERE")
OUT=$HERE/bundle
WITH_IMAGE=no
NO_SNAPS=no
for arg in "$@"; do
    case "$arg" in
        --with-image) WITH_IMAGE=yes ;;
        --no-snaps) NO_SNAPS=yes ;;
        --out=*) OUT="${arg#--out=}" ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done
[ "$(id -u)" = 0 ] || { echo "Run as root: sudo $0" >&2; exit 1; }
. /etc/os-release
ARCH=$(dpkg --print-architecture)

PKGS=$(sed -e 's/#.*//' -e '/^[[:space:]]*$/d' "${PACKAGES_FILE:-$HERE/packages.txt}" | tr -s ' \n' ' ')
SNAPS=""
if [ "${ID:-}" = ubuntu ]; then
    # firefox and chromium are only stubs for snaps in Ubuntu's own archive
    PKGS=$(echo "$PKGS" | tr ' ' '\n' | grep -vxE 'firefox-esr|chromium' | tr '\n' ' ')
    SNAPS="firefox chromium"
    [ "$NO_SNAPS" = no ] || SNAPS=""
fi

echo "== $PRETTY_NAME ($ARCH): updating the package lists"
apt-get update
apt-get install -y apt-utils dpkg-dev
[ -z "$SNAPS" ] || command -v snap >/dev/null || { echo "snap is needed to fetch $SNAPS" >&2; exit 1; }

mkdir -p "$OUT/debs"
rm -f "$OUT"/debs/*.deb
echo "== working out what $PKGS needs"
# every package they depend on, recursively (also what this computer has already: the offline one may not)
ALL=$(apt-cache depends --recurse --no-recommends --no-suggests --no-conflicts --no-breaks --no-replaces --no-enhances $PKGS | grep '^[a-z0-9]' | sort -u)
echo "== downloading $(echo "$ALL" | wc -l) packages"
cd "$OUT/debs"
skipped=0
for p in $ALL; do
    # a name with no download (a virtual package) is skipped; a real package that fails stops the whole thing
    cand=$(apt-cache policy "$p" 2>/dev/null | awk '/Candidate:/ {print $2}')
    if [ -z "$cand" ] || [ "$cand" = "(none)" ]; then skipped=$((skipped + 1)); continue; fi
    apt-get -o APT::Sandbox::User=root download "$p" >/dev/null || { echo "Download of $p failed" >&2; exit 1; }
done
echo "(skipped $skipped virtual package names)"
dpkg-scanpackages -m . /dev/null 2>/dev/null | gzip -9 > Packages.gz
cd "$HERE"

if [ -n "$SNAPS" ]; then
    echo "== snaps: $SNAPS"
    mkdir -p "$OUT/snaps"
    (cd "$OUT/snaps" && for s in $SNAPS; do snap download "$s"; done)
fi

echo "== copying the repository"
rm -rf "$OUT/repo"
mkdir -p "$OUT/repo"
(cd "$REPO" && tar --exclude=__pycache__ --exclude='offline/bundle' --exclude='pxe/out' -cf - .) | tar -xf - -C "$OUT/repo"

if [ "$WITH_IMAGE" = yes ]; then
    echo "== building the network boot image"
    "$REPO/pxe/build-image.sh" "$OUT/image"
fi

cp "$HERE/install-offline.sh" "${PACKAGES_FILE:-$HERE/packages.txt}" "$OUT/"
[ -z "${PACKAGES_FILE:-}" ] || mv "$OUT/$(basename "$PACKAGES_FILE")" "$OUT/packages.txt"
chmod +x "$OUT/install-offline.sh"
{
    echo "Offline bundle for the check-in board."
    echo "Made: $(date -u '+%Y-%m-%d %H:%M UTC') on $PRETTY_NAME ($ARCH)."
    echo "Install on a computer with the same release and CPU type:   sudo ./install-offline.sh --board [--pxe]"
} > "$OUT/README.txt"
du -sh "$OUT"
echo "Done. Copy $OUT to the offline computer and run: sudo ./install-offline.sh --board"
