#!/bin/sh
# DreamPi Netswitch add-on - removes everything the installer added.
DEST=/opt/dreampi-netswitch

if [ "$(id -u)" != "0" ]; then echo "Run with sudo: sudo $0"; exit 1; fi

for SERVICE in dreampi-netswitch dreampi-netswitch-led dreampi-netswitch-buttons dreampi-netswitch-wifi; do
    systemctl disable --now "$SERVICE.service" 2>/dev/null
    rm -f "/etc/systemd/system/$SERVICE.service"
done
systemctl daemon-reload

if [ -f "$DEST/pth_locations" ]; then
    while read -r PTH; do rm -f "$PTH"; done < "$DEST/pth_locations"
fi
for PY in python python2 python3; do
    command -v "$PY" >/dev/null 2>&1 || continue
    SITE=$("$PY" -c "import site; print(site.getsitepackages()[0])" 2>/dev/null) || continue
    rm -f "$SITE/dreampi_netswitch.pth"
done

# Undo SPI only if the installer switched it on
if [ -f "$DEST/spi_added" ]; then
    CONFIG=$(cat "$DEST/spi_added")
    sed -i '/^dtparam=spi=on  # added by dreampi-netswitch$/d' "$CONFIG"
    echo "Removed the SPI setting from $CONFIG (takes effect after a reboot)."
fi

rm -rf "$DEST" /tmp/dreampi-netswitch.active /tmp/dreampi-netswitch.state /tmp/dreampi-netswitch-dtmf.log /tmp/dreampi-netswitch.modem /tmp/dreampi-netswitch.net /tmp/dreampi-netswitch.port /tmp/dreampi-netswitch.wbtest /tmp/dreampi-netswitch.wifi
systemctl restart dreampi.service 2>/dev/null || echo "Could not restart DreamPi, please reboot."
echo "Uninstalled. DreamPi is back to its original behavior."
