# Reboot and Update - sourced by uninstall.sh and by install.sh when the module is dropped (as root): the units and the polkit rule.
rm -f /etc/systemd/system/checkin-board-update@.service /etc/systemd/system/checkin-board-reboot.service /etc/polkit-1/rules.d/50-checkin-board.rules
rm -rf /run/checkin-board-update
