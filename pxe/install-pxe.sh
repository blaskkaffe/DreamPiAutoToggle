#!/bin/bash
# install-pxe.sh - turns this computer into the network boot server for the check-in screens.
# A screen (any PC that can boot from its network card, BIOS or UEFI) then needs no disk and no setup: it loads the
# small Linux image made by build-image.sh and shows the board in Firefox, full screen.
#
#   sudo ./pxe/install-pxe.sh [--interface=eth0] [--board-url=http://192.168.1.20/] [--image=pxe/out] [--http-port=8069]
#   sudo ./pxe/install-pxe.sh --remove
#
# Needs: the image from build-image.sh. Installs dnsmasq-base and ipxe. Runs its own dnsmasq as proxy DHCP, so the router's
# DHCP server keeps handing out addresses (no second DHCP server, nothing else on the network to change), plus TFTP for
# iPXE and a small HTTP server on --http-port for the kernel and the image. Open UDP 67, 69, 4011 and TCP 8069 if a firewall is on.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
DEST=/opt/checkin-board-pxe
SERVICES="checkin-board-pxe checkin-board-pxe-http"
IMAGE=$HERE/out
HTTP_PORT=8069
IFACE=""
BOARD_URL=""

[ "$(id -u)" = 0 ] || { echo "Run as root: sudo $0" >&2; exit 1; }

for arg in "$@"; do
    case "$arg" in
        --interface=*) IFACE="${arg#--interface=}" ;;
        --board-url=*) BOARD_URL="${arg#--board-url=}" ;;
        --image=*) IMAGE="${arg#--image=}" ;;
        --http-port=*) HTTP_PORT="${arg#--http-port=}" ;;
        --remove)
            for s in $SERVICES; do
                systemctl disable --now "$s.service" 2>/dev/null || true
                rm -f "/etc/systemd/system/$s.service"
            done
            systemctl daemon-reload
            rm -rf "$DEST"
            echo "The network boot server is removed (the packages dnsmasq-base and ipxe are left)."
            exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done
case "$HTTP_PORT" in ''|*[!0-9]*) echo "--http-port must be a number" >&2; exit 1 ;; esac

for f in vmlinuz initrd.img filesystem.squashfs; do
    [ -f "$IMAGE/$f" ] || { echo "$IMAGE/$f is missing. Build the image first: sudo $HERE/build-image.sh" >&2; exit 1; }
done

apt-get update && apt-get install -y dnsmasq-base ipxe

# the network the screens are on: the interface of the default route unless one is given
[ -n "$IFACE" ] || IFACE=$(ip -4 route show default | awk '{for (i = 1; i < NF; i++) if ($i == "dev") {print $(i + 1); exit}}')
[ -n "$IFACE" ] || { echo "No network interface found; give --interface=NAME" >&2; exit 1; }
CIDR=$(ip -4 -o addr show dev "$IFACE" scope global | awk '{print $4; exit}')
[ -n "$CIDR" ] || { echo "$IFACE has no IPv4 address" >&2; exit 1; }
IP=${CIDR%/*}
NETWORK=$(python3 -c 'import ipaddress,sys; print(ipaddress.ip_interface(sys.argv[1]).network.network_address)' "$CIDR")
[ -n "$BOARD_URL" ] || BOARD_URL="http://$IP/"

for f in undionly.kpxe ipxe.efi; do
    [ -f "/usr/lib/ipxe/$f" ] || { echo "/usr/lib/ipxe/$f is missing (package ipxe)" >&2; exit 1; }
done

mkdir -p "$DEST/tftp" "$DEST/www/screens"
cp /usr/lib/ipxe/undionly.kpxe /usr/lib/ipxe/ipxe.efi "$DEST/tftp/"
cp "$IMAGE/vmlinuz" "$IMAGE/initrd.img" "$IMAGE/filesystem.squashfs" "$DEST/www/"
cp "$HERE"/screens/*.ipxe "$DEST/www/screens/" 2>/dev/null || true
python3 "$HERE/pxe_config.py" --ip "$IP" --interface "$IFACE" --network "$NETWORK" \
    --board-url "$BOARD_URL" --http-port "$HTTP_PORT" --dest "$DEST"
chmod -R a+rX "$DEST"

cat > /etc/systemd/system/checkin-board-pxe.service <<UNIT
[Unit]
Description=Check-in screens - network boot (proxy DHCP and TFTP)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/sbin/dnsmasq --keep-in-foreground --conf-file=$DEST/dnsmasq.conf
Restart=always
RestartSec=3
ProtectSystem=full
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/checkin-board-pxe-http.service <<UNIT
[Unit]
Description=Check-in screens - kernel and image over HTTP
After=network-online.target
Wants=network-online.target

[Service]
User=nobody
ExecStart=/usr/bin/python3 -m http.server $HTTP_PORT --bind $IP --directory $DEST/www
Restart=always
RestartSec=3
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
for s in $SERVICES; do
    systemctl enable "$s.service"
    systemctl restart "$s.service"
done

echo "The network boot server is running on $IFACE ($IP). Screens show $BOARD_URL"
echo "Set a screen to boot from the network (PXE) in its BIOS/UEFI setup; nothing is installed on it."
echo "Per-building screens: see pxe/screens/README.txt. Do not run a second DHCP server for this."
