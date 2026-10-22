# Reboot and Update - sourced by install.sh (as root; sees $DEST and $RUN_USER).
# The web service is an ordinary user. It gets exactly three things it may ask systemd for, nothing else: start the updater for the recorded checkout,
# start the updater for a USB stick, and reboot the computer. They are units owned by root that run the files in $DEST (which the service can not
# change); the polkit rule below names those units.
ns_updater="$DEST/modules/rebootupdate/update-run.sh"
chmod 755 "$ns_updater"
cat > /etc/systemd/system/checkin-board-update@.service <<UNIT
[Unit]
Description=Check-in update (%i)

[Service]
Type=oneshot
# the folder the page reads the progress from (the updater writes into it as root; everybody may read it)
RuntimeDirectory=checkin-board-update
RuntimeDirectoryPreserve=yes
RuntimeDirectoryMode=0755
ExecStart=/bin/sh $ns_updater %i
UNIT
cat > /etc/systemd/system/checkin-board-reboot.service <<'UNIT'
[Unit]
Description=Check-in reboot (asked for on the page)

[Service]
Type=oneshot
# two seconds, so that the page gets its answer first
ExecStart=/bin/sh -c 'sleep 2; exec systemctl --no-block --ignore-inhibitors reboot'
UNIT

ns_pk=$(pkaction --version 2>/dev/null | grep -Eo '[0-9]+(\.[0-9]+)*' | head -n 1)
ns_pk_ok=0
case "$ns_pk" in ''|0|0.[0-9]|0.[0-9][0-9]|0.10[0-5]) ;; *) ns_pk_ok=1 ;; esac      # rules in JavaScript need polkit 0.106 or newer (122 on Debian 12)
if [ "$ns_pk_ok" = 1 ]; then
    mkdir -p /etc/polkit-1/rules.d
    cat > /etc/polkit-1/rules.d/50-checkin-board.rules <<RULES
// Check-in: the web service ($RUN_USER) may start these three units and nothing else.
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.systemd1.manage-units" && subject.user == "$RUN_USER" && action.lookup("verb") == "start") {
        var unit = action.lookup("unit");
        if (unit == "checkin-board-update@git.service" || unit == "checkin-board-update@usb.service" || unit == "checkin-board-reboot.service")
            return polkit.Result.YES;
    }
});
RULES
    chmod 644 /etc/polkit-1/rules.d/50-checkin-board.rules
else
    echo "NOTE: polkit 0.106 or newer was not found (found: ${ns_pk:-none}). The page's Reboot and Update now buttons will not work for the service user;"
    echo "      update with 'sudo ./install.sh' from the checkout and restart with 'sudo reboot'. (sudo apt install policykit-1 on Debian / Ubuntu.)"
fi
