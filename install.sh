#!/bin/sh
# DreamPi Netswitch add-on - installer. Changes no DreamPi files.
#
#   sudo ./install.sh              install or update (web page on port 80)
#   sudo ./install.sh 8080         use another port for the web page
#   sudo ./install.sh --led        also show the status on a NeoPixel on GPIO10
#   sudo ./install.sh --no-led     remove the NeoPixel service again
#
# Once --led has been used, later updates keep the LED until --no-led.
set -e
DEST=/opt/dreampi-netswitch
SRC="$(cd "$(dirname "$0")" && pwd)"
PORT=80
LED=keep
for arg in "$@"; do
    case "$arg" in
        --led) LED=on ;;
        --no-led) LED=off ;;
        [0-9]*) PORT="$arg" ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

if [ "$(id -u)" != "0" ]; then echo "Run with sudo: sudo ./install.sh [port] [--led|--no-led]"; exit 1; fi

mkdir -p "$DEST"
cp "$SRC/netswitch_hook.py" "$SRC/netswitch_web.py" "$SRC/netswitch_led.py" "$SRC/uninstall.sh" "$DEST/"
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

# ---------------------------------------------------------------- NeoPixel
if [ "$LED" = keep ] && [ -f "$DEST/led_enabled" ]; then LED=on; fi
NEED_REBOOT=0
if [ "$LED" = on ]; then
    touch "$DEST/led_enabled"
    # SPI drives the NeoPixel on GPIO10 (MOSI)
    CONFIG=/boot/config.txt
    [ -f /boot/firmware/config.txt ] && CONFIG=/boot/firmware/config.txt
    if ! grep -q "^dtparam=spi=on" "$CONFIG"; then
        echo "dtparam=spi=on  # added by dreampi-netswitch" >> "$CONFIG"
        echo "$CONFIG" > "$DEST/spi_added"
        echo "Enabled SPI in $CONFIG"
    fi
    [ -e /dev/spidev0.0 ] || NEED_REBOOT=1
    cat > /etc/systemd/system/dreampi-netswitch-led.service <<EOF
[Unit]
Description=DreamPi Netswitch status NeoPixel (GPIO10)
After=network.target

[Service]
Environment=NETSWITCH_LED_BRIGHTNESS=0.15
ExecStart=$(command -v python3) $DEST/netswitch_led.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
elif [ "$LED" = off ]; then
    systemctl disable --now dreampi-netswitch-led.service 2>/dev/null || true
    rm -f /etc/systemd/system/dreampi-netswitch-led.service "$DEST/led_enabled"
    echo "NeoPixel service removed (SPI stays enabled)."
fi

systemctl daemon-reload
systemctl enable dreampi-netswitch.service >/dev/null 2>&1
systemctl restart dreampi-netswitch.service
if [ -f "$DEST/led_enabled" ]; then
    systemctl enable dreampi-netswitch-led.service >/dev/null 2>&1
    systemctl restart dreampi-netswitch-led.service
fi
systemctl restart dreampi.service 2>/dev/null || echo "Could not restart DreamPi, please reboot."

echo
echo "Installed. Open http://dreampi.local$( [ "$PORT" = 80 ] || echo ":$PORT" )"
if [ "$NEED_REBOOT" = 1 ]; then
    echo "Reboot once (sudo reboot) to switch on SPI for the NeoPixel."
fi
echo "Uninstall any time with: sudo $DEST/uninstall.sh"
