# DC Bridge module - sourced by install.sh when the module is gone from the folder, by --no-dcbridge and by uninstall.sh: stops its
# services, takes its udev rules, firewall chains, DHCP / DNS file, pppd options and network-manager settings out again (system/dcbridge-setup,
# the same script the module's Settings button runs).
# The saves (/var/lib/dcbridge) and the settings file /etc/default/dcbridge are kept: they are the user's.
DCB_MOD="${DCB_MOD:-$DEST/modules/dcbridge}"
if [ -f "$DCB_MOD/system/dcbridge-setup" ]; then
    sh "$DCB_MOD/system/dcbridge-setup" remove
fi
