# DC Bridge module - sourced by install.sh when the module is gone from the folder, by --no-dcbridge and by uninstall.sh: stops its
# services, takes its udev rules, firewall chains, DHCP / DNS file, pppd options and network-manager settings out again.
# The saves (/var/lib/dcbridge) and the settings file /etc/default/dcbridge are kept: they are the user's.
DCB_MOD="${DCB_MOD:-$DEST/modules/dcbridge}"
systemctl disable --now dcbridge-saves.service >/dev/null 2>&1 || true
systemctl stop dcbridge-ppp.service dcbridge-dcnet.service >/dev/null 2>&1 || true
[ -x "$DCB_MOD/system/dcbridge-net" ] && "$DCB_MOD/system/dcbridge-net" firewall-down >/dev/null 2>&1 || true
rm -f /etc/systemd/system/dcbridge-saves.service /etc/systemd/system/dcbridge-dcnet.service /etc/systemd/system/dcbridge-ppp.service
rm -f /etc/udev/rules.d/99-dcbridge.rules /etc/ppp/dcbridge.options /etc/NetworkManager/conf.d/dcbridge.conf /etc/sysctl.d/90-dcbridge.conf
if [ -f /etc/dnsmasq.d/dcbridge.conf ]; then
    rm -f /etc/dnsmasq.d/dcbridge.conf
    systemctl restart dnsmasq >/dev/null 2>&1 || true
fi
if [ -f /etc/dhcpcd.conf ] && grep -q "dcbridge" /etc/dhcpcd.conf; then
    sed -i '/^# dcbridge: these links are configured by dcbridge-net$/d; /^denyinterfaces dcnet0 ppp10$/d' /etc/dhcpcd.conf
fi
systemctl daemon-reload >/dev/null 2>&1 || true
udevadm control --reload >/dev/null 2>&1 || true
