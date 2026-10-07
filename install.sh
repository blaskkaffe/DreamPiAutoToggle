#!/bin/sh
# DreamPi Netswitch add-on - installer. Changes no DreamPi files.
#
#   sudo ./install.sh              install or update (web page on port 80)
#   sudo ./install.sh 8080         use another port for the web page
#   sudo ./install.sh --https-port=8443   HTTPS on another port (default 443)
#   sudo ./install.sh --no-https   plain HTTP only
#   sudo ./install.sh --leds=30    NeoPixels on GPIO18: starting count 30 (a strip). The status
#                                  LED is on by default with 1 LED; --leds=0 turns it off and
#                                  hides the LED settings on the page
#   sudo ./install.sh --led-gpio=21   use GPIO10, 12, 18 (default) or 21 instead
#   (--led, --led=N and --no-led still work: same as the default, --leds=N and --leds=0)
#   The LED, Wi-Fi setup, phone numbers, online players and debug log parts are optional modules, one folder each
#   in modules/ (see "Optional parts" in the README): a folder that is not there is not installed (and one that was
#   installed before is removed), and the LED / Wi-Fi options below do nothing without their module.
#   sudo ./install.sh --wifi       add Wi-Fi setup (a temporary access point for joining a network
#                                  without a keyboard; hostapd + dnsmasq are installed with every install): its page controls
#                                  and the button hold that starts it
#   sudo ./install.sh --no-wifi    remove Wi-Fi setup again
#   sudo ./install.sh --wifi-demo  try Wi-Fi setup on dummy networks (no hostapd, nothing is changed on the
#                                  Pi's network; password "demo" connects); --no-wifi-demo ends it
#   sudo ./install.sh --pin        ask for a PIN that the page then wants before it updates, restarts
#                                  the Pi or connects Wi-Fi (--pin=1234 gives it on the command line,
#                                  which shows in the shell history); --no-pin removes it. It is kept
#                                  across updates. Without a PIN anybody on your network can use those.
#
# The two GPIO buttons (GPIO17/pin11 toggles the network, GPIO4/pin7 is off by
# default) are always installed; their pins and functions are editable from the
# page's Settings > GPIO. Which modules are on is the page's Settings > Modules (--wifi, --no-wifi and
# --wifi-demo set the Wi-Fi one from here); the LED count is kept too. The LED count, output pin, wire order and white
# balance can all be changed later from the page's Settings, without
# --leds=N/--led-gpio=N or a reinstall. Choosing GPIO10 switches the Pi's SPI on in
# config.txt by itself (the LED service does that; a reboot may be needed once).
set -e
DEST=/opt/dreampi-netswitch
SRC="$(cd "$(dirname "$0")" && pwd)"
PORT=80
HTTPS_PORT=443
# an update keeps the ports used last time unless they are given again
if [ -f "$DEST/install_ports" ]; then
    read -r OLD_PORT OLD_HTTPS < "$DEST/install_ports" || true
    case "$OLD_PORT" in ''|*[!0-9]*) ;; *) PORT=$OLD_PORT ;; esac
    case "$OLD_HTTPS" in ''|*[!0-9]*) ;; *) HTTPS_PORT=$OLD_HTTPS ;; esac
fi
LED_COUNT=
LED_GPIO=
WIFI=keep
WIFI_DEMO=keep
PIN=keep
BUTTON1_GPIO_DEFAULT=17   # GPIO17 / physical pin 11; editable later from the page's Settings > GPIO
BUTTON2_GPIO_DEFAULT=4    # GPIO4 / physical pin 7
for arg in "$@"; do
    case "$arg" in
        --led) ;;   # old option: the LED is on by default now
        --leds=*|--led=*) LED_COUNT="${arg#*=}"
                  case "$LED_COUNT" in ''|*[!0-9]*) echo "--leds needs a number, e.g. --leds=30"; exit 1 ;; esac
                  if [ "$LED_COUNT" -gt 300 ]; then echo "--leds must be 0 to 300"; exit 1; fi ;;
        --led-gpio=*) LED_GPIO="${arg#--led-gpio=}"
                  case "$LED_GPIO" in 10|12|18|21) ;; *) echo "--led-gpio must be 10, 12, 18 or 21"; exit 1 ;; esac ;;
        --no-led) LED_COUNT=0 ;;
        --wifi) WIFI=on ;;
        --no-wifi) WIFI=off ;;
        --pin) PIN=ask ;;
        --pin=*) PIN="${arg#--pin=}"
                  if [ "${#PIN}" -lt 4 ] || [ "${#PIN}" -gt 64 ]; then echo "The PIN must be 4 to 64 characters"; exit 1; fi ;;
        --no-pin) PIN=off ;;
        --wifi-demo) WIFI_DEMO=on ;;
        --no-wifi-demo) WIFI_DEMO=off ;;
        --https-port=*) HTTPS_PORT="${arg#--https-port=}" ;;
        --no-https) HTTPS_PORT=0 ;;
        [0-9]*) PORT="$arg" ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

if [ "$(id -u)" != "0" ]; then echo "Run with sudo: sudo ./install.sh [port] [--https-port=N|--no-https] [--leds=N|--led-gpio=N] [--wifi|--no-wifi|--wifi-demo|--no-wifi-demo]"; exit 1; fi

mkdir -p "$DEST"
chmod 755 "$DEST"   # the code in here runs as root: nobody else may be able to change it
cp "$SRC"/base/base_*.py "$SRC/project.json" "$SRC/netswitch_hook.py" "$SRC/netswitch_probes.py" "$SRC/netswitch_buttons.py" \
   "$SRC/uninstall.sh" "$SRC/wifi-powersave-off.sh" "$DEST/"
mkdir -p "$DEST/page" "$DEST/static"
cp "$SRC"/base/page/index.html "$SRC"/base/page/page.css "$SRC"/base/page/page.js "$SRC"/base/page/widgets.js "$SRC"/base/page/boot.js "$DEST/page/"
cp "$SRC"/static/*.png "$DEST/static/"
# Files an older layout kept next to the base (the features are folders in modules/ now)
rm -f "$DEST/netswitch_core.py" "$DEST/netswitch_modules.py" "$DEST/netswitch_web.py" "$DEST/netswitch_security.py" "$DEST/netswitch_tz.py" "$DEST/netswitch_gpio.py"
rm -f "$DEST/netswitch_update.py" "$DEST/static/three.min.js" "$DEST/static/dc-background.js" "$DEST/static/LICENSES.txt" "$DEST/netswitch_led.py" "$DEST/netswitch_led_drivers.py" "$DEST/netswitch_ledconfig.py" "$DEST/netswitch_numbers.py" \
      "$DEST/netswitch_players.py" "$DEST/netswitch_wifi_setup.py" "$DEST/page/led.html" "$DEST/page/led.js" "$DEST/page/led.css" "$DEST/page/players.js"

# >>> sync_modules
# The optional features: every folder in modules/ is copied to $DEST/modules/. A folder that was installed before but
# is gone from $SRC/modules gets its remove.sh run (if it has one) and is deleted - that is how a module is removed.
# Switching a module on or off is done on the page (Settings > Modules), not here.
ns_module_enable() {   # ns_module_enable <name> on|off : write the Modules menu's switch
    (cd "$DEST" && python3 -c "import sys, base_core as c; c.save_module_enabled(sys.argv[1], sys.argv[2] == 'on')" "$1" "$2")
}
sync_modules() {
    mkdir -p "$DEST/modules"
    for ns_dir in "$DEST"/modules/*/; do
        [ -d "$ns_dir" ] || continue
        ns_name=$(basename "$ns_dir")
        if [ ! -d "$SRC/modules/$ns_name" ]; then
            echo "Module $ns_name is no longer in this folder: removing it."
            [ -f "$ns_dir/remove.sh" ] && . "$ns_dir/remove.sh"
            rm -rf "$ns_dir"
        fi
    done
    for ns_dir in "$SRC"/modules/*/; do
        [ -f "$ns_dir/module.json" ] || continue
        ns_name=$(basename "$ns_dir")
        rm -rf "$DEST/modules/$ns_name"
        cp -r "$ns_dir" "$DEST/modules/$ns_name"
        find "$DEST/modules/$ns_name" -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
    done
}
sync_modules
# <<< sync_modules
chmod +x "$DEST/uninstall.sh"
# Add-on version for the settings page: date and commit of this checkout
if command -v git >/dev/null 2>&1 && git -C "$SRC" rev-parse >/dev/null 2>&1; then
    git -c safe.directory="$SRC" -C "$SRC" log -1 --format='%cd (%h)' --date=format:'%Y-%m-%d %H:%M' > "$DEST/version" 2>/dev/null || echo unknown > "$DEST/version"
else
    echo unknown > "$DEST/version"
fi
# For the update check and the page's "Update now": which commit this is, where
# the checkout lives, and the ports to keep when the installer is re-run.
git -c safe.directory="$SRC" -C "$SRC" rev-parse HEAD > "$DEST/version_commit" 2>/dev/null || rm -f "$DEST/version_commit"
echo "$SRC" > "$DEST/src_dir"
echo "$PORT $HTTPS_PORT" > "$DEST/install_ports"
# "Update now" only pulls from the address the checkout had when it was installed
if command -v git >/dev/null 2>&1; then
    git -c safe.directory="$SRC" -C "$SRC" config --get remote.origin.url > "$DEST/update_origin" 2>/dev/null || rm -f "$DEST/update_origin"
fi

# Optional PIN for update / restart / Wi-Fi connect on the page (stored as a salted hash)
if [ "$PIN" = ask ]; then
    printf "New PIN (4-64 characters, not shown): "
    stty -echo 2>/dev/null || true
    read -r PIN || PIN=
    stty echo 2>/dev/null || true
    echo
    if [ "${#PIN}" -lt 4 ] || [ "${#PIN}" -gt 64 ]; then echo "The PIN must be 4 to 64 characters"; exit 1; fi
fi
case "$PIN" in
    keep) ;;
    off) (cd "$DEST" && python3 base_security.py clear) && echo "PIN removed" ;;
    *) (cd "$DEST" && NS_PIN="$PIN" python3 base_security.py set) && echo "PIN set: the page asks for it before an update, restart or Wi-Fi connect" ;;
esac
PIN=

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
ExecStart=$WEBPY $DEST/base_web.py $PORT $HTTPS_PORT
Restart=always
RestartSec=3
Nice=-5
# The page runs as root, so it is fenced in: no setuid tricks, no writes to /usr, /boot or /etc,
# no cgroup or kernel-module changes. (The update runs in its own transient unit, see modules/rebootupdate/netswitch_update.py.)
NoNewPrivileges=yes
ProtectSystem=full
ProtectControlGroups=yes
ProtectKernelModules=yes

[Install]
WantedBy=multi-user.target
EOF

# ------------------------------------------------------------------ buttons
# Always installed: two GPIO buttons with a short-press function each (pins and
# functions editable from the page). Wi-Fi setup is not part of it: that is the Wi-Fi module's own service.
[ -f "$DEST/button1_gpio" ] || echo "$BUTTON1_GPIO_DEFAULT" > "$DEST/button1_gpio"
[ -f "$DEST/button2_gpio" ] || echo "$BUTTON2_GPIO_DEFAULT" > "$DEST/button2_gpio"
echo "Buttons on GPIO$(cat "$DEST/button1_gpio") and GPIO$(cat "$DEST/button2_gpio") (pins and functions editable from the page's Settings > GPIO)"
# Older versions had one service for both buttons and Wi-Fi setup, enabled only
# by --wifi (marker wifi_button_enabled): carry that over (modules/wifi/install.sh turns it into the module's switch).
if [ -f "$DEST/wifi_button_enabled" ]; then mv "$DEST/wifi_button_enabled" "$DEST/wifi_enabled"; fi
# (and a service of that name from then, running netswitch_wifi.py, is replaced by the Wi-Fi module's own service, or removed if the module is absent)
if [ -f /etc/systemd/system/dreampi-netswitch-wifi.service ] && [ ! -d "$DEST/modules/wifi" ]; then
    systemctl disable --now dreampi-netswitch-wifi.service 2>/dev/null || true
    rm -f /etc/systemd/system/dreampi-netswitch-wifi.service
fi
rm -f "$DEST/netswitch_wifi.py" "$DEST/wifi_button_gpio"
cat > /etc/systemd/system/dreampi-netswitch-buttons.service <<EOF
[Unit]
Description=DreamPi Netswitch buttons
After=network.target
StartLimitIntervalSec=0

[Service]
ExecStart=$(command -v python3) $DEST/netswitch_buttons.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# ------------------------------------------------------------------ modules
# Each installed module may have an install.sh, sourced here (it sees $DEST, $SRC, $LED_COUNT, $LED_GPIO, $WIFI, $WIFI_DEMO)
# and adds the systemd units it needs to NS_SERVICES. See modules/led and modules/wifi.
NS_SERVICES=
for ns_dir in "$DEST"/modules/*/; do
    [ -f "$ns_dir/install.sh" ] && . "$ns_dir/install.sh"
done
for ns_flag in "$WIFI$WIFI_DEMO"; do
    case "$ns_flag" in *on*|*off*) [ -d "$DEST/modules/wifi" ] || echo "Wi-Fi options ignored: the Wi-Fi setup module is not in this folder." ;; esac
done
if [ -n "$LED_COUNT$LED_GPIO" ] && [ ! -d "$DEST/modules/led" ]; then
    echo "LED options ignored: the status LED module is not in this folder."
fi

systemctl daemon-reload
systemctl enable dreampi-netswitch.service >/dev/null 2>&1
systemctl restart dreampi-netswitch.service
systemctl enable dreampi-netswitch-buttons.service >/dev/null 2>&1
systemctl restart dreampi-netswitch-buttons.service
for ns_service in $NS_SERVICES; do      # the services of the installed modules
    systemctl enable "$ns_service" >/dev/null 2>&1
    systemctl restart "$ns_service"
done
systemctl restart dreampi.service 2>/dev/null || echo "Could not restart DreamPi, please reboot."

echo
echo "Installed. Open http://dreampi.local$( [ "$PORT" = 80 ] || echo ":$PORT" )"
if [ "$HTTPS_PORT" != 0 ] && [ -f "$DEST/https.crt" ]; then
    echo "      or https://dreampi.local$( [ "$HTTPS_PORT" = 443 ] || echo ":$HTTPS_PORT" )  (accept the certificate warning once)"
fi
echo "Uninstall any time with: sudo $DEST/uninstall.sh"
