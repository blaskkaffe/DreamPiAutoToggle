#!/bin/sh
# DreamPi Netswitch add-on - installer. Changes no DreamPi files.
#
#   sudo ./install.sh              install or update (web page on port 80)
#   sudo ./install.sh 8080         use another port for the web page
#   sudo ./install.sh --https-port=8443   HTTPS on another port (default 443)
#   sudo ./install.sh --no-https   plain HTTP only
#   sudo ./install.sh --led        also show the status on a NeoPixel on GPIO10
#   sudo ./install.sh --no-led     remove the NeoPixel service again
#
# Once --led has been used, later updates keep the LED until --no-led.
set -e
DEST=/opt/dreampi-netswitch
SRC="$(cd "$(dirname "$0")" && pwd)"
PORT=80
HTTPS_PORT=443
LED=keep
for arg in "$@"; do
    case "$arg" in
        --led) LED=on ;;
        --no-led) LED=off ;;
        --https-port=*) HTTPS_PORT="${arg#--https-port=}" ;;
        --no-https) HTTPS_PORT=0 ;;
        [0-9]*) PORT="$arg" ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

if [ "$(id -u)" != "0" ]; then echo "Run with sudo: sudo ./install.sh [port] [--https-port=N|--no-https] [--led|--no-led]"; exit 1; fi

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

# Self-signed certificate for the HTTPS page. Kept on updates, renewed when it
# expires within 30 days. 820 days: Apple devices refuse certificates valid
# for more than 825 days.
if [ -f "$DEST/https.crt" ] && command -v openssl >/dev/null 2>&1 \
        && ! openssl x509 -checkend 2592000 -noout -in "$DEST/https.crt" >/dev/null 2>&1; then
    rm -f "$DEST/https.crt" "$DEST/https.key"
fi
if [ "$HTTPS_PORT" != 0 ] && [ ! -f "$DEST/https.crt" ]; then
    if command -v openssl >/dev/null 2>&1; then
        HOST=$(hostname)
        SAN="DNS:dreampi.local,DNS:$HOST.local,DNS:$HOST,DNS:localhost,IP:127.0.0.1"
        for IP in $(hostname -I 2>/dev/null); do
            case "$IP" in *:*) ;; *) SAN="$SAN,IP:$IP" ;; esac
        done
        CNF=$(mktemp)
        printf '[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n[dn]\nCN=dreampi.local\nO=DreamPi Netswitch\n[ext]\nsubjectAltName=%s\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' "$SAN" > "$CNF"
        if openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 820 \
                -keyout "$DEST/https.key" -out "$DEST/https.crt" -config "$CNF" >/dev/null 2>&1; then
            chmod 600 "$DEST/https.key"
            echo "Created a self-signed HTTPS certificate"
        else
            rm -f "$DEST/https.key" "$DEST/https.crt"
            echo "Could not create an HTTPS certificate, the page stays HTTP only"
        fi
        rm -f "$CNF"
    else
        echo "openssl not found, the page stays HTTP only"
    fi
fi

WEBPY=$(command -v python3 || command -v python)
cat > /etc/systemd/system/dreampi-netswitch.service <<EOF
[Unit]
Description=DreamPi Netswitch web page
After=network.target

[Service]
ExecStart=$WEBPY $DEST/netswitch_web.py $PORT $HTTPS_PORT
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
if [ "$HTTPS_PORT" != 0 ] && [ -f "$DEST/https.crt" ]; then
    echo "      or https://dreampi.local$( [ "$HTTPS_PORT" = 443 ] || echo ":$HTTPS_PORT" )  (accept the certificate warning once)"
fi
if [ "$NEED_REBOOT" = 1 ]; then
    echo "Reboot once (sudo reboot) to switch on SPI for the NeoPixel."
fi
echo "Uninstall any time with: sudo $DEST/uninstall.sh"
