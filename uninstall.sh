#!/bin/sh
# DreamPi Netswitch add-on - removes everything the installer added.
DEST=/opt/dreampi-netswitch

if [ "$(id -u)" != "0" ]; then echo "Run with sudo: sudo $0"; exit 1; fi

systemctl disable --now dreampi-netswitch.service 2>/dev/null
rm -f /etc/systemd/system/dreampi-netswitch.service
systemctl daemon-reload

if [ -f "$DEST/pth_locations" ]; then
    while read -r PTH; do rm -f "$PTH"; done < "$DEST/pth_locations"
fi
for PY in python python2 python3; do
    command -v "$PY" >/dev/null 2>&1 || continue
    SITE=$("$PY" -c "import site; print(site.getsitepackages()[0])" 2>/dev/null) || continue
    rm -f "$SITE/dreampi_netswitch.pth"
done

rm -rf "$DEST" /tmp/dreampi-netswitch.active
systemctl restart dreampi.service 2>/dev/null || echo "Could not restart DreamPi, please reboot."
echo "Uninstalled. DreamPi is back to its original behavior."
