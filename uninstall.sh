#!/bin/sh
# Check-in add-on - removes everything the installer added.
DEST=/opt/checkin-board

if [ "$(id -u)" != "0" ]; then echo "Run with sudo: sudo $0"; exit 1; fi

# Every module cleans up after itself (remove.sh: its service, files, settings in the Pi's config)
for ns_dir in "$DEST"/modules/*/; do
    [ -f "$ns_dir/remove.sh" ] && . "$ns_dir/remove.sh"
done

# the services of an install under the old names (dreampi-netswitch*), if one is still there
for SERVICE in checkin-board checkin-board-wifi dreampi-netswitch dreampi-netswitch-wifi; do
    systemctl disable --now "$SERVICE.service" 2>/dev/null
    rm -f "/etc/systemd/system/$SERVICE.service"
done
systemctl daemon-reload

rm -rf "$DEST" /tmp/checkin-board.* /tmp/dreampi-netswitch.*      # and the state files in /tmp (update)
echo "Uninstalled."
