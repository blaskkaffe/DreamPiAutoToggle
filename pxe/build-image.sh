#!/bin/bash
# build-image.sh - builds the small diskless Linux image the check-in screens boot over the network:
# a Debian root file system (squashfs) with Xorg, Openbox and Firefox that opens the board full screen, plus its kernel and initrd.
#
#   sudo ./pxe/build-image.sh [output folder]        (default: pxe/out)
#
# Run it on any Debian or Ubuntu computer with internet access (it needs debootstrap and squashfs-tools, installed if missing).
# It takes a few minutes and produces vmlinuz, initrd.img and filesystem.squashfs (about 500-700 MB; /boot stays inside the squashfs because the
# local install copies the system, kernel included, to the disk).
# Then sudo ./pxe/install-pxe.sh serves them. Environment: SUITE (default bookworm; trixie = Debian 13 also works), MIRROR, EXTRA_PACKAGES (e.g. more firmware).
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
PACKAGES="$PACKAGES,xinit,x11-xserver-utils,openbox,feh,firefox-esr,chromium,mpv,fonts-noto-color-emoji,avahi-daemon,libnss-mdns,fonts-dejavu-core,fonts-liberation"
PACKAGES="$PACKAGES,firmware-realtek,firmware-misc-nonfree,firmware-amd-graphics"
# the local-install wizard (checkin-install) and a usable shell
PACKAGES="$PACKAGES,whiptail,parted,dosfstools,e2fsprogs,rsync,grub2-common,grub-pc-bin,grub-efi-amd64-bin,nano,pciutils,iputils-ping,less,bash"
[ -z "$EXTRA_PACKAGES" ] || PACKAGES="$PACKAGES,$EXTRA_PACKAGES"

# Take the system's /dev /proc /sys out of a build folder (they are mounted in it while it is built). Returns 1 while something is still mounted.
unmount_build() {
    umount -R "$1/root" 2>/dev/null || true
    for m in dev/pts dev sys proc; do umount "$1/root/$m" 2>/dev/null || true; done
    ! grep -q " $1/" /proc/mounts
}
# Never delete a folder that still has the computer's own /dev /proc /sys mounted in it (rm -rf would reach into them).
remove_build() {
    if unmount_build "$1"; then rm -rf "$1"; else echo "Left $1 alone: something is still mounted in it (reboot, then remove it)." >&2; fi
}
# folders of earlier builds that failed
for old in /var/tmp/checkin-pxe-build.*; do
    [ -d "$old" ] && remove_build "$old"
done

WORK=$(mktemp -d /var/tmp/checkin-pxe-build.XXXXXX)
ROOT=$WORK/root
cleanup() { remove_build "$WORK"; }
trap cleanup EXIT

# Two steps: debootstrap only builds the minimal base; the kernel, initramfs-tools and everything else are installed with apt inside the
# chroot afterwards, with /proc, /sys and /dev mounted (the kernel's and live-boot's package scripts build the initramfs and fail without
# them: "Failure while configuring base packages" after "Configuring initramfs-tools"), and with the real error shown if something fails.
show_log() {
    echo >&2
    echo "The build failed. The last lines of the debootstrap log:" >&2
    tail -n 30 "$ROOT/debootstrap/debootstrap.log" 2>/dev/null >&2 || true
}
trap 'show_log' ERR

echo "== debootstrap $SUITE (the minimal base)"
debootstrap --arch=amd64 --variant=minbase --components=main,non-free-firmware "$SUITE" "$ROOT" "$MIRROR"

echo "== mounting /dev /proc /sys in the new system"
mount --bind /dev "$ROOT/dev"; mount -t devpts devpts "$ROOT/dev/pts"
mount -t proc proc "$ROOT/proc"; mount -t sysfs sysfs "$ROOT/sys"

echo "== installing the packages (this downloads about 1 GB)"
rm -f "$ROOT/etc/apt/sources.list.d/debian.sources"
echo "deb $MIRROR $SUITE main non-free-firmware" > "$ROOT/etc/apt/sources.list"
mkdir -p "$ROOT/etc/initramfs-tools/conf.d"
echo "RESUME=none" > "$ROOT/etc/initramfs-tools/conf.d/resume"        # no swap partition to resume from: a diskless system
printf '#!/bin/sh\nexit 101\n' > "$ROOT/usr/sbin/policy-rc.d"; chmod +x "$ROOT/usr/sbin/policy-rc.d"      # no services start inside the chroot
chroot "$ROOT" /usr/bin/env DEBIAN_FRONTEND=noninteractive LC_ALL=C /bin/sh -e -c \
    "apt-get update && apt-get install -y --no-install-recommends $(echo "$PACKAGES" | tr ',' ' ')"
rm -f "$ROOT/usr/sbin/policy-rc.d"

echo "== configuring"
cp -a "$HERE/image/." "$ROOT/"
mkdir -p "$ROOT/usr/lib/firefox-esr/distribution"
cp "$HERE/image/etc/firefox/policies/policies.json" "$ROOT/usr/lib/firefox-esr/distribution/policies.json"
echo checkin-screen > "$ROOT/etc/hostname"
chroot "$ROOT" /bin/sh -e <<'CHROOT'
useradd --create-home --shell /usr/sbin/nologin --groups video,audio,input,render kiosk || true
passwd -l root
ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
systemctl enable systemd-networkd.service systemd-resolved.service kiosk.service checkin-install.service checkin-shell.service   # which one runs: the kernel command line (see their Condition lines)
systemctl mask getty@tty1.service
systemctl set-default graphical.target
# the root file system lives in memory: nothing is written back, a reboot is a fresh start
update-initramfs -u -k all
apt-get clean
rm -f /etc/machine-id
rm -rf /var/lib/apt/lists/* /usr/share/doc/* /usr/share/man/* /var/cache/debconf/*-old
CHROOT

# the system's /dev /proc /sys must not be inside the image: mksquashfs would try to read them ("failed to read file")
unmount_build "$WORK" || { echo "Could not unmount /dev /proc /sys from $ROOT" >&2; exit 1; }

echo "== writing $OUT"
mkdir -p "$OUT"
cp -L "$ROOT"/boot/vmlinuz-* "$OUT/vmlinuz"
cp -L "$ROOT"/boot/initrd.img-* "$OUT/initrd.img"
rm -f "$OUT/filesystem.squashfs"
mksquashfs "$ROOT" "$OUT/filesystem.squashfs" -comp xz -noappend
chmod 644 "$OUT"/vmlinuz "$OUT"/initrd.img "$OUT"/filesystem.squashfs
ls -lh "$OUT"
echo "Done. Next: sudo $HERE/install-pxe.sh"
