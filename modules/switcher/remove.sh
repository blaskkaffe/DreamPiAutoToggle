# Network switcher module - sourced by install.sh when the module is gone from the folder, and by uninstall.sh.
# Takes the DreamPi integration out of every Python (the .pth files) and removes the buttons service. The settings files
# (button1_gpio ...) stay, so adding the module back restores them.
systemctl disable --now dreampi-netswitch-buttons.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/dreampi-netswitch-buttons.service
if [ -f "$DEST/pth_locations" ]; then
    while read -r NS_PTH; do rm -f "$NS_PTH"; done < "$DEST/pth_locations"
    : > "$DEST/pth_locations"
fi
