#!/bin/sh
# Check-in add-on - removes everything the installer added.
DEST=/opt/checkin-board        # the code (root)
DATA=/var/lib/checkin-board    # the state of the service: the people and who is in

if [ "$(id -u)" != "0" ]; then echo "Run with sudo: sudo $0"; exit 1; fi

# Every module cleans up after itself (remove.sh: its service, files, settings in the computer's config)
for ns_dir in "$DEST"/modules/*/; do
    [ -f "$ns_dir/remove.sh" ] && . "$ns_dir/remove.sh"
done

systemctl disable --now checkin-board.service 2>/dev/null
rm -f /etc/systemd/system/checkin-board.service
rm -f /etc/sysctl.d/90-checkin-reboot.conf /etc/systemd/system.conf.d/90-checkin-watchdog.conf      # the restart-on-crash settings (they apply from the next boot)
rm -f /etc/systemd/logind.conf.d/90-checkin-no-sleep.conf      # the host may sleep again
[ ! -f "$DEST/sleep_masked" ] || systemctl unmask $(cat "$DEST/sleep_masked") 2>/dev/null
systemctl daemon-reload

[ ! -f "$DEST/user_created" ] || userdel "$(cat "$DEST/user_created")" 2>/dev/null     # the user the installer made for the service
rm -rf "$DEST" "$DATA" /run/checkin-board /run/checkin-board-update      # and the state files in /run (update)
echo "Uninstalled."
