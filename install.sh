#!/bin/sh
# Check-in add-on - installer.
#
#   sudo ./install.sh              install or update (web page on port 80)
#   sudo ./install.sh 8080         use another port for the web page
#   sudo ./install.sh --https-port=8443   HTTPS on another port (default 443)
#   sudo ./install.sh --no-https   plain HTTP only
#   The check-in board, the contacts and the system controls are modules, one folder each in
#   modules/ (see docs/modules.md): a folder that is not there is not installed (and one that was installed before is
#   removed). Which modules are on is the page's Settings > System > Modules.
#   sudo ./install.sh --hostname=checkinchicken   give the computer that name, so the board is at http://checkinchicken.local
#                                  (the address the kiosk screens use when they are not told another one; needs avahi-daemon for the .local name)
#   sudo ./install.sh --allow-sleep  do not stop the computer from sleeping (by default the host never sleeps, see below)
#   sudo ./install.sh --user=NAME  run the web service as this user (default: checkin, a system user that is made for it). The service is never root:
#                                  it gets the right to open port 80 / 443 and to ask systemd for three things (update, update from USB,
#                                  reboot), see docs/web.md. An existing user may be named; its state folder is /var/lib/checkin-board.
#   sudo ./install.sh --pin        ask for a PIN that the page then wants before it updates, restarts
#                                  the computer or imports contacts (--pin=1234 gives it on the command line,
#                                  which shows in the shell history); --no-pin removes it. It is kept
#                                  across updates. Without a PIN anybody on your network can use those.
#
# One computer runs this (the host); every other screen opens its address in a browser, in kiosk mode if you like
# (kiosk/kiosk-browser.sh). Everything the screens show is kept by the host, so they are all in step.
set -e
DEST=/opt/checkin-board         # the code and what only the installer writes: owned by root, the service only reads it (project.json "install_dir")
DATA=/var/lib/checkin-board     # everything the service writes: owned by the service's user (project.json "data_dir")
RUN_USER=checkin
umask 022                       # what is copied to $DEST must be readable by the service whatever the shell's umask is
SRC="$(cd "$(dirname "$0")" && pwd)"
PORT=80
HTTPS_PORT=443
# an update keeps the ports used last time unless they are given again
if [ -f "$DEST/install_ports" ]; then
    read -r OLD_PORT OLD_HTTPS < "$DEST/install_ports" || true
    case "$OLD_PORT" in ''|*[!0-9]*) ;; *) PORT=$OLD_PORT ;; esac
    case "$OLD_HTTPS" in ''|*[!0-9]*) ;; *) HTTPS_PORT=$OLD_HTTPS ;; esac
fi
if [ -f "$DEST/run_user" ]; then read -r OLD_USER < "$DEST/run_user" || true; [ -z "$OLD_USER" ] || RUN_USER=$OLD_USER; fi      # an update keeps the user
PIN=keep
NEW_HOSTNAME=""
ALLOW_SLEEP=0
for arg in "$@"; do
    case "$arg" in
        --pin) PIN=ask ;;
        --pin=*) PIN="${arg#--pin=}"
                  if [ "${#PIN}" -lt 4 ] || [ "${#PIN}" -gt 64 ]; then echo "The PIN must be 4 to 64 characters"; exit 1; fi ;;
        --no-pin) PIN=off ;;
        --allow-sleep) ALLOW_SLEEP=1 ;;
        --user=*) RUN_USER="${arg#--user=}" ;;
        --https-port=*) HTTPS_PORT="${arg#--https-port=}" ;;
        --no-https) HTTPS_PORT=0 ;;
        --hostname=*) NEW_HOSTNAME="${arg#--hostname=}"
                      case "$NEW_HOSTNAME" in ''|-*|*[!A-Za-z0-9-]*) echo "The host name may only have letters, digits and dashes"; exit 1 ;; esac ;;
        [0-9]*) PORT="$arg" ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

if [ "$(id -u)" != "0" ]; then echo "Run with sudo: sudo ./install.sh [port] [--https-port=N|--no-https]"; exit 1; fi
case "$RUN_USER" in ''|-*|root|*[!a-z0-9_-]*) echo "The service must run as an ordinary user (letters, digits, - and _; not root): --user=$RUN_USER"; exit 1 ;; esac

if [ -n "$NEW_HOSTNAME" ] && [ "$(hostname)" != "$NEW_HOSTNAME" ]; then
    if command -v hostnamectl >/dev/null 2>&1; then hostnamectl set-hostname "$NEW_HOSTNAME"; else echo "$NEW_HOSTNAME" > /etc/hostname; hostname "$NEW_HOSTNAME"; fi
    # the new name must resolve on this computer (sudo and the tools that look it up complain otherwise)
    if grep -q '^127\.0\.1\.1' /etc/hosts 2>/dev/null; then sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$NEW_HOSTNAME/" /etc/hosts; else printf '127.0.1.1\t%s\n' "$NEW_HOSTNAME" >> /etc/hosts; fi
    echo "The computer is now called $NEW_HOSTNAME (http://$NEW_HOSTNAME.local with avahi-daemon running)"
fi

# The user the web service runs as, and its folder. An existing user is used as it is; a new one has no login and no shell.
MADE_USER=
if ! id "$RUN_USER" >/dev/null 2>&1; then
    useradd --system --user-group --no-create-home --home-dir "$DATA" --shell /usr/sbin/nologin "$RUN_USER" 2>/dev/null \
        || useradd -r -M -d "$DATA" -s /bin/false "$RUN_USER" \
        || { echo "Could not make the user $RUN_USER"; exit 1; }
    MADE_USER=1
    echo "Made the user $RUN_USER for the web service"
fi
RUN_GROUP=$(id -gn "$RUN_USER")
mkdir -p "$DEST" "$DATA"
chown root:root "$DEST"; chmod 755 "$DEST"   # the code: nobody but root may change it, the service only reads it
echo "$RUN_USER" > "$DEST/run_user"
[ -z "$MADE_USER" ] || echo "$RUN_USER" > "$DEST/user_created"      # so that uninstall.sh removes it again (a user that was there before is left alone)

# An install from before the service was a user kept its state next to the code: move it to its own folder (nothing is overwritten).
for ns_name in contacts.json checkin.json modules.json module_order.json colours.json tints.json palette.json palette_custom.json time_zone language \
               photos screen.json tile_layout.json screens sounds snow.json settings_pin background_image imagebg.json allowed_hosts https.crt https.key debug; do
    if [ -e "$DEST/$ns_name" ] && [ ! -e "$DATA/$ns_name" ]; then mv "$DEST/$ns_name" "$DATA/$ns_name"; fi
done
rm -rf "$DEST/usb_src"
cp "$SRC"/base/base_*.py "$SRC"/base/lang_*.json "$SRC/base/layout.json" "$SRC/project.json" "$SRC/uninstall.sh" "$SRC/diagnose-network.sh" "$DEST/"
rm -f "$DEST/wifi-powersave-off.sh"      # an older install had a Wi-Fi script here
mkdir -p "$DEST/page" "$DEST/kiosk"
cp "$SRC"/base/page/index.html "$SRC"/base/page/page.css "$SRC"/base/page/page.js "$SRC"/base/page/widgets.js "$SRC"/base/page/boot.js "$DEST/page/"
cp "$SRC"/kiosk/* "$DEST/kiosk/"
chmod +x "$DEST/kiosk/kiosk-browser.sh"
mkdir -p "$DATA/sounds"; cp "$SRC"/base/sounds/* "$DATA/sounds/"      # the button sounds (copy more .wav / .mp3 / .ogg files in by hand: Settings > Appearance > Button sound lists them)

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
# Add-on version for the settings page: date and commit of this checkout. An update from a USB stick (the page's "Install from USB") runs this
# installer from a copy of the stick's folder with NS_KEEP_SRC=1 and NS_VERSION: it names its own version and leaves the recorded checkout alone,
# so that "Update now" from GitHub keeps working.
if [ -n "$NS_VERSION" ]; then
    echo "$NS_VERSION" > "$DEST/version"
elif command -v git >/dev/null 2>&1 && git -C "$SRC" rev-parse >/dev/null 2>&1; then
    git -c safe.directory="$SRC" -C "$SRC" log -1 --format='%cd (%h)' --date=format:'%Y-%m-%d %H:%M' > "$DEST/version" 2>/dev/null || echo unknown > "$DEST/version"
else
    echo unknown > "$DEST/version"
fi
# For the update check and the page's "Update now": which commit this is, where
# the checkout lives, and the ports to keep when the installer is re-run.
if [ -z "$NS_KEEP_SRC" ]; then
    git -c safe.directory="$SRC" -C "$SRC" rev-parse HEAD > "$DEST/version_commit" 2>/dev/null || rm -f "$DEST/version_commit"
    echo "$SRC" > "$DEST/src_dir"
else
    rm -f "$DEST/version_commit"      # this install is not that commit any more
fi
echo "$PORT $HTTPS_PORT" > "$DEST/install_ports"
# "Update now" only pulls from the address the checkout had when it was installed
if [ -z "$NS_KEEP_SRC" ] && command -v git >/dev/null 2>&1; then
    git -c safe.directory="$SRC" -C "$SRC" config --get remote.origin.url > "$DEST/update_origin" 2>/dev/null || rm -f "$DEST/update_origin"
    git -c safe.directory="$SRC" -C "$SRC" rev-parse --abbrev-ref HEAD > "$DEST/update_branch" 2>/dev/null || rm -f "$DEST/update_branch"
fi

# Optional PIN for update / restart on the page (stored as a salted hash)
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
    *) (cd "$DEST" && NS_PIN="$PIN" python3 base_security.py set && chgrp "$RUN_GROUP" "$DEST/admin_pin" && chmod 640 "$DEST/admin_pin") && echo "PIN set: the page asks for it before an update or restart" ;;
esac
PIN=

# Self-signed certificate for the HTTPS page. Kept on updates, renewed when it
# expires within 30 days. 820 days: Apple devices refuse certificates valid
# for more than 825 days.
if [ -f "$DATA/https.crt" ] && command -v openssl >/dev/null 2>&1 \
        && ! openssl x509 -checkend 2592000 -noout -in "$DATA/https.crt" >/dev/null 2>&1; then
    rm -f "$DATA/https.crt" "$DATA/https.key"
fi
if [ "$HTTPS_PORT" != 0 ] && [ ! -f "$DATA/https.crt" ]; then
    if command -v openssl >/dev/null 2>&1; then
        HOST=$(hostname)
        SAN="DNS:$HOST.local,DNS:$HOST,DNS:localhost,IP:127.0.0.1"
        for IP in $(hostname -I 2>/dev/null); do
            case "$IP" in *:*) ;; *) SAN="$SAN,IP:$IP" ;; esac
        done
        CNF=$(mktemp)
        printf '[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n[dn]\nCN=%s.local\nO=Check-in\n[ext]\nsubjectAltName=%s\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' "$HOST" "$SAN" > "$CNF"
        if openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 820 \
                -keyout "$DATA/https.key" -out "$DATA/https.crt" -config "$CNF" >/dev/null 2>&1; then
            chmod 600 "$DATA/https.key"
            echo "Created a self-signed HTTPS certificate"
        else
            rm -f "$DATA/https.key" "$DATA/https.crt"
            echo "Could not create an HTTPS certificate, the page stays HTTP only"
        fi
        rm -f "$CNF"
    else
        echo "openssl not found, the page stays HTTP only"
    fi
fi

WEBPY=$(command -v python3 || command -v python)
cat > /etc/systemd/system/checkin-board.service <<EOF
[Unit]
Description=Check-in web page
After=network.target
# never give up restarting (the default stops after 5 quick failures)
StartLimitIntervalSec=0

[Service]
User=$RUN_USER
Group=$RUN_GROUP
ExecStart=$WEBPY $DEST/base_web.py $PORT $HTTPS_PORT
Restart=always
RestartSec=3
Environment=PYTHONDONTWRITEBYTECODE=1
# Not root. The one privilege it keeps is opening port 80 / 443; update and reboot are asked of systemd (polkit rule, modules/rebootupdate/install.sh).
RuntimeDirectory=checkin-board
RuntimeDirectoryMode=0755
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_BIND_SERVICE
NoNewPrivileges=yes
# It can write in its own folder and nowhere else; /home and /tmp are not there for it, the code in $DEST is read-only.
ProtectSystem=strict
ReadWritePaths=$DATA
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
LockPersonality=yes
UMask=0027

[Install]
WantedBy=multi-user.target
EOF

# The computer restarts by itself if the kernel panics (after 10 s) or systemd stops answering (the watchdog, where the hardware has one;
# removed again by uninstall.sh)
mkdir -p /etc/sysctl.d /etc/systemd/system.conf.d
printf 'kernel.panic = 10\nkernel.panic_on_oops = 1\n' > /etc/sysctl.d/90-checkin-reboot.conf
printf '[Manager]\nRuntimeWatchdogSec=60\nRebootWatchdogSec=10min\nShutdownWatchdogSec=5min\n' > /etc/systemd/system.conf.d/90-checkin-watchdog.conf
sysctl -q -p /etc/sysctl.d/90-checkin-reboot.conf >/dev/null 2>&1 || true

# The host must never sleep: a suspended computer does not answer the screens (no ping, no page) until somebody uses it, which is what an idle
# desktop does after about 20 minutes, and nobody touches a computer that only serves a board. The sleep targets are masked (what the desktop,
# the lid and the power button ask for is then refused) and logind is told to ignore idleness, the lid and the keys. Undone by uninstall.sh.
if [ "$ALLOW_SLEEP" = 1 ]; then
    rm -f /etc/systemd/logind.conf.d/90-checkin-no-sleep.conf
    if [ -f "$DEST/sleep_masked" ]; then systemctl unmask $(cat "$DEST/sleep_masked") >/dev/null 2>&1 || true; rm -f "$DEST/sleep_masked"; fi
    echo "Sleep is allowed (--allow-sleep): a sleeping host does not answer the screens."
else
    mkdir -p /etc/systemd/logind.conf.d
    printf '[Login]\nIdleAction=ignore\nHandleSuspendKey=ignore\nHandleHibernateKey=ignore\nHandleLidSwitch=ignore\nHandleLidSwitchExternalPower=ignore\nHandleLidSwitchDocked=ignore\nHandlePowerKey=ignore\n' > /etc/systemd/logind.conf.d/90-checkin-no-sleep.conf
    MASKED=""
    for t in sleep.target suspend.target hibernate.target hybrid-sleep.target; do
        if [ "$(systemctl is-enabled "$t" 2>/dev/null)" != masked ]; then systemctl mask "$t" >/dev/null 2>&1 && MASKED="$MASKED $t"; fi
    done
    [ -z "$MASKED" ] || { OLD=$(cat "$DEST/sleep_masked" 2>/dev/null || true); echo "$OLD$MASKED" | tr -s ' ' '\n' | grep . | sort -u | tr '\n' ' ' > "$DEST/sleep_masked"; }
    systemctl kill -s HUP systemd-logind >/dev/null 2>&1 || true
fi

# ------------------------------------------------------------------ modules
# Each installed module may have an install.sh, sourced here (it sees $DEST and $SRC)
# and adds the systemd units it needs to NS_SERVICES. See docs/modules.md.
NS_SERVICES=
for ns_dir in "$DEST"/modules/*/; do
    [ -f "$ns_dir/install.sh" ] && . "$ns_dir/install.sh"
done

# Ownership: the code is root's (the service can not change what it runs); the state folder is the service's. The key of the HTTPS certificate is
# readable by the service only. (Everything above that wrote into $DATA ran as root.)
chown -R root:root "$DEST"
chmod -R go-w "$DEST"
find "$DEST" -type d -exec chmod 755 {} +
find "$DEST" -type f -exec chmod go+r {} +
python3 -m compileall -q "$DEST" >/dev/null 2>&1 || true      # the service can not write the compiled files itself
chown -R "$RUN_USER:$RUN_GROUP" "$DATA"
chmod 750 "$DATA"
[ ! -f "$DATA/https.key" ] || chmod 600 "$DATA/https.key"
[ ! -f "$DEST/admin_pin" ] || { chgrp "$RUN_GROUP" "$DEST/admin_pin"; chmod 640 "$DEST/admin_pin"; }

systemctl daemon-reload
systemctl enable checkin-board.service >/dev/null 2>&1
systemctl restart checkin-board.service
for ns_service in $NS_SERVICES; do      # the services of the installed modules
    systemctl enable "$ns_service" >/dev/null 2>&1
    systemctl restart "$ns_service"
done

echo
echo "Installed. Open http://$(hostname).local$( [ "$PORT" = 80 ] || echo ":$PORT" )"
if [ "$HTTPS_PORT" != 0 ] && [ -f "$DATA/https.crt" ]; then
    echo "      or https://$(hostname).local$( [ "$HTTPS_PORT" = 443 ] || echo ":$HTTPS_PORT" )  (accept the certificate warning once)"
fi
echo "The web service runs as the user $RUN_USER (not root); its state is in $DATA."
echo "Import the people in Settings > Contacts. Other screens: open the same address (see kiosk/kiosk-browser.sh)."
echo "Uninstall any time with: sudo $DEST/uninstall.sh"
