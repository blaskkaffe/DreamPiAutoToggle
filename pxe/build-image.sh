#!/bin/bash
# build-image.sh - builds the small diskless Linux image the check-in screens boot over the network:
# a Debian root file system (squashfs) with Xorg, Openbox and Firefox that opens the board full screen, plus its kernel and initrd.
#
#   sudo ./pxe/build-image.sh [output folder]        (default: pxe/out)
#
# Run it on any Debian or Ubuntu computer with internet access (it needs debootstrap and squashfs-tools, installed if missing).
# It takes a few minutes and produces vmlinuz, initrd.img and filesystem.squashfs (about 400-600 MB).
# Then sudo ./pxe/install-pxe.sh serves them. Environment: SUITE (default bookworm), MIRROR, EXTRA_PACKAGES (e.g. more firmware).
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${1:-$HERE/out}
SUITE=${SUITE:-bookworm}
MIRROR=${MIRROR:-http://deb.debian.org/debian}
EXTRA_PACKAGES=${EXTRA_PACKAGES:-}

[ "$(id -u)" = 0 ] || { echo "Run as root: sudo $0" >&2; exit 1; }
if ! command -v debootstrap >/dev/null || ! command -v mksquashfs >/dev/null; then
    apt-get update && apt-get install -y debootstrap squashfs-tools
fi

PACKAGES="linux-image-amd64,live-boot,initramfs-tools,systemd-sysv,systemd-resolved,udev,dbus,libpam-systemd,curl,ca-certificates,iproute2"
PACKAGES="$PACKAGES,xserver-xorg-core,xserver-xorg-legacy,xserver-xorg-input-libinput,xserver-xorg-video-fbdev,xserver-xorg-video-vesa"
PACKAGES="$PACKAGES,xinit,x11-xserver-utils,openbox,firefox-esr,fonts-dejavu-core,fonts-liberation"
PACKAGES="$PACKAGES,firmware-realtek,firmware-misc-nonfree,firmware-amd-graphics"
[ -z "$EXTRA_PACKAGES" ] || PACKAGES="$PACKAGES,$EXTRA_PACKAGES"

WORK=$(mktemp -d /var/tmp/checkin-pxe-build.XXXXXX)
ROOT=$WORK/root
cleanup() {
    for m in dev/pts dev sys proc; do umount "$ROOT/$m" 2>/dev/null || true; done
    rm -rf "$WORK"
}
trap cleanup EXIT

echo "== debootstrap $SUITE (this downloads about 1 GB)"
debootstrap --arch=amd64 --variant=minbase --components=main,non-free-firmware \
    --include="$PACKAGES" "$SUITE" "$ROOT" "$MIRROR"

echo "== configuring"
cp -a "$HERE/image/." "$ROOT/"
mount --bind /dev "$ROOT/dev"; mount -t devpts devpts "$ROOT/dev/pts"
mount -t proc proc "$ROOT/proc"; mount -t sysfs sysfs "$ROOT/sys"
mkdir -p "$ROOT/usr/lib/firefox-esr/distribution"
cp "$HERE/image/etc/firefox/policies/policies.json" "$ROOT/usr/lib/firefox-esr/distribution/policies.json"
echo checkin-screen > "$ROOT/etc/hostname"
chroot "$ROOT" /bin/sh -e <<'CHROOT'
useradd --create-home --shell /usr/sbin/nologin --groups video,audio,input,render kiosk || true
passwd -l root
ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
systemctl enable systemd-networkd.service systemd-resolved.service kiosk.service
systemctl mask getty@tty1.service
systemctl set-default graphical.target
# the root file system lives in memory: nothing is written back, a reboot is a fresh start
update-initramfs -u -k all
apt-get clean
rm -rf /var/lib/apt/lists/* /usr/share/doc/* /usr/share/man/* /var/cache/debconf/*-old
CHROOT

echo "== writing $OUT"
mkdir -p "$OUT"
cp -L "$ROOT"/boot/vmlinuz-* "$OUT/vmlinuz"
cp -L "$ROOT"/boot/initrd.img-* "$OUT/initrd.img"
rm -f "$OUT/filesystem.squashfs"
mksquashfs "$ROOT" "$OUT/filesystem.squashfs" -comp xz -e boot -noappend
chmod 644 "$OUT"/vmlinuz "$OUT"/initrd.img "$OUT"/filesystem.squashfs
ls -lh "$OUT"
echo "Done. Next: sudo $HERE/install-pxe.sh"
