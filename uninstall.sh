#!/bin/sh
# Check-in add-on - removes everything the installer added.
DEST=/opt/checkin-board

if [ "$(id -u)" != "0" ]; then echo "Run with sudo: sudo $0"; exit 1; fi

# Every module cleans up after itself (remove.sh: its service, files, settings in the computer's config)
for ns_dir in "$DEST"/modules/*/; do
    [ -f "$ns_dir/remove.sh" ] && . "$ns_dir/remove.sh"
done

systemctl disable --now checkin-board.service 2>/dev/null
rm -f /etc/systemd/system/checkin-board.service
systemctl daemon-reload

rm -rf "$DEST" /tmp/checkin-board.*      # and the state files in /tmp (update)
echo "Uninstalled."
