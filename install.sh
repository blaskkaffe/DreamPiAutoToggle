#!/bin/sh
# DreamPi Netswitch add-on - installer. Changes no DreamPi files.
#
#   sudo ./install.sh              install or update (web page on port 80)
#   sudo ./install.sh 8080         use another port for the web page
#   sudo ./install.sh --https-port=8443   HTTPS on another port (default 443)
#   sudo ./install.sh --no-https   plain HTTP only
#   sudo ./install.sh --led        also show the status on a NeoPixel on GPIO18 (1 LED, or the
#                                  count already set)
#   sudo ./install.sh --led=30     the same with several NeoPixels / a strip (starting count: 30)
#   sudo ./install.sh --led-gpio=21   use GPIO10, 12, 18 (default) or 21 instead
#   sudo ./install.sh --no-led     remove the NeoPixel service again
#   sudo ./install.sh --wifi       add Wi-Fi setup (a temporary access point for joining a network
#                                  without a keyboard; installs hostapd + dnsmasq): its page controls
#                                  and the button hold that starts it
#   sudo ./install.sh --no-wifi    remove Wi-Fi setup again
#
# The two GPIO buttons (GPIO17/pin11 toggles the network, GPIO4/pin7 is off by
# default) are always installed; their pins and functions are editable from the
# page's Settings > GPIO. Once --led or --wifi has been used, later updates keep
# it until --no-led / --no-wifi. The LED count, output pin, wire order and white
# balance can all be changed later from the page's Settings, without
# --led=N/--led-gpio=N or a reinstall - except switching to GPIO10, which needs
# SPI enabled first (this installer does that for --led-gpio=10, but it needs a
# reboot).
set -e
DEST=/opt/dreampi-netswitch
SRC="$(cd "$(dirname "$0")" && pwd)"
PORT=80
HTTPS_PORT=443
LED=keep
LED_COUNT=
LED_GPIO=
WIFI=keep
BUTTON1_GPIO_DEFAULT=17   # GPIO17 / physical pin 11; editable later from the page's Settings > GPIO
BUTTON2_GPIO_DEFAULT=4    # GPIO4 / physical pin 7
for arg in "$@"; do
    case "$arg" in
        --led) LED=on ;;
        --led=*) LED=on; LED_COUNT="${arg#--led=}"
                  case "$LED_COUNT" in ''|*[!0-9]*) echo "--led needs a number, e.g. --led=30"; exit 1 ;; esac
                  if [ "$LED_COUNT" -lt 1 ] || [ "$LED_COUNT" -gt 300 ]; then echo "--led must be 1 to 300"; exit 1; fi ;;
        --led-gpio=*) LED=on; LED_GPIO="${arg#--led-gpio=}"
                  case "$LED_GPIO" in 10|12|18|21) ;; *) echo "--led-gpio must be 10, 12, 18 or 21"; exit 1 ;; esac ;;
        --no-led) LED=off ;;
        --wifi) WIFI=on ;;
        --no-wifi) WIFI=off ;;
        --https-port=*) HTTPS_PORT="${arg#--https-port=}" ;;
        --no-https) HTTPS_PORT=0 ;;
        [0-9]*) PORT="$arg" ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

if [ "$(id -u)" != "0" ]; then echo "Run with sudo: sudo ./install.sh [port] [--https-port=N|--no-https] [--led[=N]|--led-gpio=N|--no-led] [--wifi|--no-wifi]"; exit 1; fi

mkdir -p "$DEST"
cp "$SRC/netswitch_hook.py" "$SRC/netswitch_web.py" "$SRC/netswitch_led.py" "$SRC/netswitch_gpio.py" "$SRC/netswitch_buttons.py" \
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
    if [ -n "$LED_GPIO" ]; then echo "$LED_GPIO" > "$DEST/led_gpio"; fi
    [ -f "$DEST/led_gpio" ] || echo 18 > "$DEST/led_gpio"
    GPIO=$(cat "$DEST/led_gpio")
    echo "NeoPixel output on GPIO$GPIO: $(cat "$DEST/led_count") LED(s)"
    # GPIO10 needs the kernel's SPI driver; GPIO12/18/21 use /dev/mem directly
    # and don't. Track what we changed in spi_added, so switching away from
    # GPIO10 later (here or from the page) takes the setting back out again.
    CONFIG_TXT=
    for candidate in /boot/firmware/config.txt /boot/config.txt; do
        [ -f "$candidate" ] && CONFIG_TXT="$candidate" && break
    done
    if [ "$GPIO" = 10 ]; then
        if [ -n "$CONFIG_TXT" ] && ! grep -q '^dtparam=spi=on' "$CONFIG_TXT"; then
            printf '\ndtparam=spi=on  # added by dreampi-netswitch\n' >> "$CONFIG_TXT"
            echo "$CONFIG_TXT" > "$DEST/spi_added"
            echo "Enabled SPI in $CONFIG_TXT for GPIO10; reboot before the LEDs will work on it."
        elif [ -z "$CONFIG_TXT" ]; then
            echo "Could not find config.txt to enable SPI for GPIO10 - add dtparam=spi=on yourself and reboot."
        fi
    elif [ -f "$DEST/spi_added" ]; then
        sed -i '/^dtparam=spi=on  # added by dreampi-netswitch$/d' "$(cat "$DEST/spi_added")"
        rm -f "$DEST/spi_added"
        echo "Removed the SPI setting added for GPIO10 (not needed for GPIO$GPIO)."
    fi
    cat > /etc/systemd/system/dreampi-netswitch-led.service <<EOF
[Unit]
Description=DreamPi Netswitch status NeoPixel
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
    rm -f /etc/systemd/system/dreampi-netswitch-led.service "$DEST/led_enabled" "$DEST/led_count" "$DEST/led_gpio"
    if [ -f "$DEST/spi_added" ]; then
        sed -i '/^dtparam=spi=on  # added by dreampi-netswitch$/d' "$(cat "$DEST/spi_added")"
        rm -f "$DEST/spi_added"
    fi
    echo "NeoPixel service removed."
fi

# ------------------------------------------------------------------ buttons
# Always installed: two GPIO buttons with a short-press function each (pins and
# functions editable from the page). Wi-Fi setup is the optional part, below.
[ -f "$DEST/button1_gpio" ] || echo "$BUTTON1_GPIO_DEFAULT" > "$DEST/button1_gpio"
[ -f "$DEST/button2_gpio" ] || echo "$BUTTON2_GPIO_DEFAULT" > "$DEST/button2_gpio"
echo "Buttons on GPIO$(cat "$DEST/button1_gpio") and GPIO$(cat "$DEST/button2_gpio") (pins and functions editable from the page's Settings > GPIO)"
# Older versions had one service for both buttons and Wi-Fi setup, enabled only
# by --wifi (marker wifi_button_enabled): carry that over.
if [ -f "$DEST/wifi_button_enabled" ]; then mv "$DEST/wifi_button_enabled" "$DEST/wifi_enabled"; fi
if [ -f /etc/systemd/system/dreampi-netswitch-wifi.service ]; then
    systemctl disable --now dreampi-netswitch-wifi.service 2>/dev/null || true
    rm -f /etc/systemd/system/dreampi-netswitch-wifi.service
fi
rm -f "$DEST/netswitch_wifi.py" "$DEST/wifi_button_gpio"
cat > /etc/systemd/system/dreampi-netswitch-buttons.service <<EOF
[Unit]
Description=DreamPi Netswitch buttons (and Wi-Fi setup)
After=network.target
StartLimitIntervalSec=0

[Service]
ExecStart=$(command -v python3) $DEST/netswitch_buttons.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# ---------------------------------------------------------------- Wi-Fi setup
if [ "$WIFI" = keep ] && [ -f "$DEST/wifi_enabled" ]; then WIFI=on; fi
if [ "$WIFI" = on ]; then
    touch "$DEST/wifi_enabled"
    # The Wi-Fi setup access point needs hostapd and dnsmasq. Install them if
    # missing, and make sure their own systemd units stay off: this add-on
    # starts and stops them itself (dreampi-netswitch-buttons.service), so a
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
    echo "Wi-Fi setup enabled (choose which button holds to start it in Settings > GPIO)"
elif [ "$WIFI" = off ]; then
    rm -f "$DEST/wifi_enabled" "$DEST/wifi_button" "$DEST/wifi_hostapd.conf" "$DEST/wifi_dnsmasq.conf"
    echo "Wi-Fi setup removed."
fi

systemctl daemon-reload
systemctl enable dreampi-netswitch.service >/dev/null 2>&1
systemctl restart dreampi-netswitch.service
if [ -f "$DEST/led_enabled" ]; then
    systemctl enable dreampi-netswitch-led.service >/dev/null 2>&1
    systemctl restart dreampi-netswitch-led.service
fi
systemctl enable dreampi-netswitch-buttons.service >/dev/null 2>&1
systemctl restart dreampi-netswitch-buttons.service
systemctl restart dreampi.service 2>/dev/null || echo "Could not restart DreamPi, please reboot."

echo
echo "Installed. Open http://dreampi.local$( [ "$PORT" = 80 ] || echo ":$PORT" )"
if [ "$HTTPS_PORT" != 0 ] && [ -f "$DEST/https.crt" ]; then
    echo "      or https://dreampi.local$( [ "$HTTPS_PORT" = 443 ] || echo ":$HTTPS_PORT" )  (accept the certificate warning once)"
fi
echo "Uninstall any time with: sudo $DEST/uninstall.sh"
