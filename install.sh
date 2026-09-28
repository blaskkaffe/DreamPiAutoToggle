#!/bin/sh
# DreamPi Netswitch add-on - installer. Changes no DreamPi files.
set -e
PORT="${1:-80}"
DEST=/opt/dreampi-netswitch
SRC="$(cd "$(dirname "$0")" && pwd)"

if [ "$(id -u)" != "0" ]; then echo "Run with sudo: sudo ./install.sh [port]"; exit 1; fi

mkdir -p "$DEST"
cp "$SRC/netswitch_hook.py" "$SRC/netswitch_web.py" "$SRC/uninstall.sh" "$DEST/"
chmod +x "$DEST/uninstall.sh"

# Tell every installed Python to load the hook at startup (.pth file)
: > "$DEST/pth_locations"
for PY in python python2 python3; do
    command -v "$PY" >/dev/null 2>&1 || continue
    SITE=$("$PY" -c "import site; print(site.getsitepackages()[0])" 2>/dev/null) || continue
    [ -n "$SITE" ] || continue
    mkdir -p "$SITE"
    printf '%s\nimport netswitch_hook\n' "$DEST" > "$SITE/dreampi_netswitch.pth"
    grep -qx "$SITE/dreampi_netswitch.pth" "$DEST/pth_locations" || echo "$SITE/dreampi_netswitch.pth" >> "$DEST/pth_locations"
    echo "Hook registered for $PY ($SITE)"
done

WEBPY=$(command -v python3 || command -v python)
cat > /etc/systemd/system/dreampi-netswitch.service <<EOF
[Unit]
Description=DreamPi Netswitch web page
After=network.target

[Service]
ExecStart=$WEBPY $DEST/netswitch_web.py $PORT
Restart=always

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now dreampi-netswitch.service
systemctl restart dreampi.service 2>/dev/null || echo "Could not restart DreamPi, please reboot."

echo
echo "Installed. Open http://dreampi.local$( [ "$PORT" = 80 ] || echo ":$PORT" )"
echo "Uninstall any time with: sudo $DEST/uninstall.sh"
