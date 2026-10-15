# DC Bridge module - sourced by install.sh while this module is in the folder (so it shares install.sh's variables: $DEST, $DCBRIDGE,
# $NS_SERVICES ...). The module's files are already copied to $DEST/modules/dcbridge.
# The bridge changes how the Pi routes the Dreamcast's own links (udev names, a service, pppd, NAT in its own DCB-* iptables chains,
# DHCP and DNS for the W5500 link in /etc/dnsmasq.d/dcbridge.conf; DreamPi's own files, rules and modem link are left alone), so it is
# only set up when it is wanted:
#   --dcbridge       install it and switch the module on
#   --no-dcbridge    take it out again and switch the module off (the saves in /var/lib/dcbridge and /etc/default/dcbridge stay)
#   no flag          an update keeps what is there: re-installed while the module is on in Settings > Modules, left alone otherwise
# See docs/dcbridge.md.
DCB_MOD="$DEST/modules/dcbridge"
dcb_is_on() {
    (cd "$DEST" && python3 -c "import sys, base_core as c; sys.exit(0 if c.module_enabled('dcbridge') else 1)")
}
if [ "$DCBRIDGE" = off ]; then
    ns_module_enable dcbridge off
    . "$DCB_MOD/remove.sh"
    echo "DC Bridge removed from the Pi (its saves are still in /var/lib/dcbridge)."
elif [ "$DCBRIDGE" = on ] || dcb_is_on; then
    [ "$DCBRIDGE" = on ] && ns_module_enable dcbridge on
    if command -v apt-get >/dev/null 2>&1; then
        apt-get install -y -q mtools dosfstools python3 ppp dnsmasq iptables \
            || echo "Could not install mtools / dosfstools / ppp / dnsmasq / iptables automatically; install them yourself for DC Bridge to work."
    fi
    mkdir -p /var/lib/dcbridge
    chmod +x "$DCB_MOD/system/dcbridge-net"
    install -m 644 "$DCB_MOD/system/dcbridge.ppp-options" /etc/ppp/dcbridge.options
    [ -e /etc/default/dcbridge ] || sed "s#@MODULE@#$DCB_MOD#g" "$DCB_MOD/system/dcbridge.default" > /etc/default/dcbridge
    # keep other network managers away from the two links
    if [ -f /etc/dhcpcd.conf ] && ! grep -q "dcbridge" /etc/dhcpcd.conf; then
        printf '\n# dcbridge: these links are configured by dcbridge-net\ndenyinterfaces dcnet0 ppp10\n' >> /etc/dhcpcd.conf
    fi
    if [ -d /etc/NetworkManager/conf.d ]; then
        printf '[keyfile]\nunmanaged-devices=interface-name:dcnet0;interface-name:ppp10\n' > /etc/NetworkManager/conf.d/dcbridge.conf
    fi
    echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/90-dcbridge.conf
    sysctl -q -p /etc/sysctl.d/90-dcbridge.conf || true
    cp "$DCB_MOD/system/99-dcbridge.rules" /etc/udev/rules.d/
    for ns_unit in dcbridge-saves dcbridge-dcnet dcbridge-ppp; do
        sed "s#@MODULE@#$DCB_MOD#g" "$DCB_MOD/system/$ns_unit.service" > "/etc/systemd/system/$ns_unit.service"
    done
    systemctl daemon-reload
    systemctl enable dnsmasq >/dev/null 2>&1 || true
    "$DCB_MOD/system/dcbridge-net" dnsmasq-conf || true
    "$DCB_MOD/system/dcbridge-net" firewall-up || true
    NS_SERVICES="$NS_SERVICES dcbridge-saves.service"      # enabled and (re)started with the others; ppp and dcnet are started by udev
    udevadm control --reload || true
    udevadm trigger --subsystem-match=tty --subsystem-match=net || true
    echo "DC Bridge: save manager in the dashboard (Settings > DC Bridge), network settings in /etc/default/dcbridge (then: sudo $DCB_MOD/system/dcbridge-net reload)"
fi
