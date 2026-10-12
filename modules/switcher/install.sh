# Network switcher module - sourced by install.sh while this module is in the folder (so it shares install.sh's variables:
# $DEST, $NS_SERVICES ...). The module's files are already copied to $DEST/modules/switcher.
# 1. Tells every installed Python to load the module's DreamPi integration (netswitch_dreampi.py) at startup (.pth file). It does
#    nothing unless the running program is DreamPi's. install.sh keeps the list of the .pth files in $DEST/pth_locations.
# 2. Sets up the GPIO buttons service: two buttons with a short-press function each (pins and functions editable from the page's
#    Settings > GPIO).
: > "$DEST/pth_locations"
for PY in python python2 python3; do
    command -v "$PY" >/dev/null 2>&1 || continue
    SITE=$("$PY" -c "import site; print(site.getsitepackages()[0])" 2>/dev/null) || continue
    [ -n "$SITE" ] || continue
    mkdir -p "$SITE"
    printf '%s\nimport netswitch_dreampi\n' "$DEST/modules/switcher" > "$SITE/dreampi_netswitch.pth"
    grep -qx "$SITE/dreampi_netswitch.pth" "$DEST/pth_locations" || echo "$SITE/dreampi_netswitch.pth" >> "$DEST/pth_locations"
    echo "Hook registered for $PY ($SITE)"
done

BUTTON1_GPIO_DEFAULT=17   # GPIO17 / physical pin 11
BUTTON2_GPIO_DEFAULT=4    # GPIO4 / physical pin 7
[ -f "$DEST/button1_gpio" ] || echo "$BUTTON1_GPIO_DEFAULT" > "$DEST/button1_gpio"
[ -f "$DEST/button2_gpio" ] || echo "$BUTTON2_GPIO_DEFAULT" > "$DEST/button2_gpio"
echo "Buttons on GPIO$(cat "$DEST/button1_gpio") and GPIO$(cat "$DEST/button2_gpio") (pins and functions editable from the page's Settings > GPIO)"
cat > /etc/systemd/system/dreampi-netswitch-buttons.service <<UNIT
[Unit]
Description=DreamPi Netswitch buttons
After=network.target
StartLimitIntervalSec=0
ConditionPathExists=$DEST/modules/switcher/netswitch_switcher_buttons.py

[Service]
ExecStart=$(command -v python3) $DEST/modules/switcher/netswitch_switcher_buttons.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
NS_SERVICES="$NS_SERVICES dreampi-netswitch-buttons.service"
