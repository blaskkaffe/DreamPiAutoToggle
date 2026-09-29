#!/bin/sh
# DreamPi Netswitch add-on - installer. Changes no DreamPi files.
#
#   sudo ./install.sh              install or update (web page on port 80)
#   sudo ./install.sh 8080         use another port for the web page
#   sudo ./install.sh --https-port=8443   HTTPS on another port (default 443)
#   sudo ./install.sh --no-https   plain HTTP only
#   sudo ./install.sh --led        also show the status on a NeoPixel on GPIO18
#   sudo ./install.sh --leds=30    the same with several NeoPixels / a strip (30 LEDs)
#   sudo ./install.sh --no-led     remove the NeoPixel service again
#   sudo ./install.sh --wifi-button=17   a button on GPIO17: hold 3 s to set up Wi-Fi
#   sudo ./install.sh --no-wifi-button   remove the Wi-Fi setup button/service again
#
# Once --led or --wifi-button has been used, later updates keep it until --no-led / --no-wifi-button.
set -e
DEST=/opt/dreampi-netswitch
SRC="$(cd "$(dirname "$0")" && pwd)"
PORT=80
HTTPS_PORT=443
LED=keep
LED_COUNT=
WIFI_BTN=keep
WIFI_BTN_GPIO=
for arg in "$@"; do
    case "$arg" in
        --led) LED=on; LED_COUNT=1 ;;
        --leds=*) LED=on; LED_COUNT="${arg#--leds=}"
                  case "$LED_COUNT" in ''|*[!0-9]*) echo "--leds needs a number, e.g. --leds=30"; exit 1 ;; esac
                  if [ "$LED_COUNT" -lt 1 ] || [ "$LED_COUNT" -gt 300 ]; then echo "--leds must be 1 to 300"; exit 1; fi ;;
        --no-led) LED=off ;;
        --wifi-button=*) WIFI_BTN=on; WIFI_BTN_GPIO="${arg#--wifi-button=}"
                  case "$WIFI_BTN_GPIO" in ''|*[!0-9]*) echo "--wifi-button needs a GPIO number, e.g. --wifi-button=17"; exit 1 ;; esac
                  if [ "$WIFI_BTN_GPIO" -gt 53 ]; then echo "--wifi-button must be a valid GPIO number (0 to 53)"; exit 1; fi ;;
        --no-wifi-button) WIFI_BTN=off ;;
        --https-port=*) HTTPS_PORT="${arg#--https-port=}" ;;
        --no-https) HTTPS_PORT=0 ;;
        [0-9]*) PORT="$arg" ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

if [ "$(id -u)" != "0" ]; then echo "Run with sudo: sudo ./install.sh [port] [--https-port=N|--no-https] [--led|--leds=N|--no-led] [--wifi-button=N|--no-wifi-button]"; exit 1; fi

mkdir -p "$DEST"
cp "$SRC/netswitch_hook.py" "$SRC/netswitch_web.py" "$SRC/netswitch_led.py" "$SRC/netswitch_gpio.py" "$SRC/netswitch_wifi.py" \
   "$SRC/uninstall.sh" "$SRC/wifi-powersave-off.sh" "$DEST/"
mkdir -p "$DEST/static"
cp "$SRC/static/three.min.js" "$SRC/static/dc-background.js" "$SRC/static/LICENSES.txt" "$SRC"/static/*.png "$DEST/static/"
chmod +x "$DEST/uninstall.sh"
# Add-on version for the settings page: date and commit of this checkout
if command -v git >/dev/null 2>&1 && git -C "$SRC" rev-parse >/dev/null 2>&1; then
    git -c safe.directory="$SRC" -C "$SRC" log -1 --format='%cd (%h)' --date=format:'%Y-%m-%d %H:%M' > "$DEST/version" 2>/dev/null || echo unknown > "$DEST/version"
else
    echo unknown > "$DEST/version"
fi

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
# never give up restarting (the default stops after 5 quick failures)
StartLimitIntervalSec=0

[Service]
# Wi-Fi power saving makes a Pi drop off the network now and then (see the script)
ExecStartPre=-/bin/sh $DEST/wifi-powersave-off.sh
ExecStart=$WEBPY $DEST/netswitch_web.py $PORT $HTTPS_PORT
Restart=always
RestartSec=3
Nice=-5

[Install]
WantedBy=multi-user.target
EOF

# ---------------------------------------------------------------- NeoPixel
if [ "$LED" = keep ] && [ -f "$DEST/led_enabled" ]; then LED=on; fi
if [ "$LED" = on ]; then
    touch "$DEST/led_enabled"
    if [ -n "$LED_COUNT" ]; then echo "$LED_COUNT" > "$DEST/led_count"; fi
    [ -f "$DEST/led_count" ] || echo 1 > "$DEST/led_count"
    echo "NeoPixel output on GPIO18: $(cat "$DEST/led_count") LED(s)"
    # The LED uses GPIO18's PWM directly. Older versions used SPI on GPIO10:
    # take back the SPI line they added, it isn't needed any more.
    if [ -f "$DEST/spi_added" ]; then
        sed -i '/^dtparam=spi=on  # added by dreampi-netswitch$/d' "$(cat "$DEST/spi_added")"
        rm -f "$DEST/spi_added"
        echo "Removed the SPI setting added by an older version (not needed any more)."
    fi
    cat > /etc/systemd/system/dreampi-netswitch-led.service <<EOF
[Unit]
Description=DreamPi Netswitch status NeoPixel (GPIO18)
After=network.target
StartLimitIntervalSec=0

[Service]
ExecStart=$(command -v python3) $DEST/netswitch_led.py
Restart=always
RestartSec=10
# the LED animation must never slow down the web page or DreamPi
Nice=10

[Install]
WantedBy=multi-user.target
EOF
elif [ "$LED" = off ]; then
    systemctl disable --now dreampi-netswitch-led.service 2>/dev/null || true
    rm -f /etc/systemd/system/dreampi-netswitch-led.service "$DEST/led_enabled" "$DEST/led_count"
    echo "NeoPixel service removed."
fi

# ----------------------------------------------------------- Wi-Fi setup button
if [ "$WIFI_BTN" = keep ] && [ -f "$DEST/wifi_button_enabled" ]; then WIFI_BTN=on; fi
if [ "$WIFI_BTN" = on ]; then
    touch "$DEST/wifi_button_enabled"
    if [ -n "$WIFI_BTN_GPIO" ]; then echo "$WIFI_BTN_GPIO" > "$DEST/wifi_button_gpio"; fi
    echo "Wi-Fi setup button on GPIO$(cat "$DEST/wifi_button_gpio" 2>/dev/null || echo '?')"
    # The Wi-Fi setup access point needs hostapd and dnsmasq. Install them if
    # missing, and make sure their own systemd units stay off: this add-on
    # starts and stops them itself (dreampi-netswitch-wifi.service), so a
    # default dnsmasq listening on every interface would conflict with it.
    if ! command -v hostapd >/dev/null 2>&1 || ! command -v dnsmasq >/dev/null 2>&1; then
        if command -v apt-get >/dev/null 2>&1; then
            echo "Installing hostapd and dnsmasq (needed to host the Wi-Fi setup access point)..."
            apt-get update -q && apt-get install -y -q hostapd dnsmasq \
                || echo "Could not install hostapd/dnsmasq automatically; install them yourself, then re-run this."
        else
            echo "hostapd and/or dnsmasq not found and apt-get isn't available; install them yourself for Wi-Fi setup to work."
        fi
    fi
    systemctl disable --now hostapd.service 2>/dev/null || true
    systemctl disable --now dnsmasq.service 2>/dev/null || true
    cat > /etc/systemd/system/dreampi-netswitch-wifi.service <<EOF
[Unit]
Description=DreamPi Netswitch Wi-Fi setup button
After=network.target
StartLimitIntervalSec=0

[Service]
ExecStart=$(command -v python3) $DEST/netswitch_wifi.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
elif [ "$WIFI_BTN" = off ]; then
    systemctl disable --now dreampi-netswitch-wifi.service 2>/dev/null || true
    rm -f /etc/systemd/system/dreampi-netswitch-wifi.service "$DEST/wifi_button_enabled" "$DEST/wifi_button_gpio" \
          "$DEST/wifi_hostapd.conf" "$DEST/wifi_dnsmasq.conf"
    echo "Wi-Fi setup button service removed."
fi

systemctl daemon-reload
systemctl enable dreampi-netswitch.service >/dev/null 2>&1
systemctl restart dreampi-netswitch.service
if [ -f "$DEST/led_enabled" ]; then
    systemctl enable dreampi-netswitch-led.service >/dev/null 2>&1
    systemctl restart dreampi-netswitch-led.service
fi
if [ -f "$DEST/wifi_button_enabled" ]; then
    systemctl enable dreampi-netswitch-wifi.service >/dev/null 2>&1
    systemctl restart dreampi-netswitch-wifi.service
fi
systemctl restart dreampi.service 2>/dev/null || echo "Could not restart DreamPi, please reboot."

echo
echo "Installed. Open http://dreampi.local$( [ "$PORT" = 80 ] || echo ":$PORT" )"
if [ "$HTTPS_PORT" != 0 ] && [ -f "$DEST/https.crt" ]; then
    echo "      or https://dreampi.local$( [ "$HTTPS_PORT" = 443 ] || echo ":$HTTPS_PORT" )  (accept the certificate warning once)"
fi
echo "Uninstall any time with: sudo $DEST/uninstall.sh"
