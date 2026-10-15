# DC Bridge module - sourced by install.sh while this module is in the folder (so it shares install.sh's variables: $DEST, $DCBRIDGE,
# $NS_SERVICES ...). The module's files are already copied to $DEST/modules/dcbridge.
# The bridge changes how the Pi routes the Dreamcast's own links (udev names, a service, pppd, NAT in its own DCB-* iptables chains,
# DHCP and DNS for the W5500 link in /etc/dnsmasq.d/dcbridge.conf; DreamPi's own files, rules and modem link are left alone), so it is
# only set up when it is wanted. The work is in system/dcbridge-setup, which is also what the module's Install / Uninstall buttons in
# Settings > DC Bridge run, so the two ways give the same result:
#   --dcbridge       install it and switch the module on
#   --no-dcbridge    take it out again and switch the module off (the saves in /var/lib/dcbridge and /etc/default/dcbridge stay)
#   no flag          an update keeps what is there: re-installed when it is installed, left alone otherwise
# See docs/dcbridge.md.
DCB_MOD="$DEST/modules/dcbridge"
if [ "$DCBRIDGE" = off ]; then
    ns_module_enable dcbridge off
    . "$DCB_MOD/remove.sh"
    echo "DC Bridge removed from the Pi (its saves are still in /var/lib/dcbridge)."
elif [ "$DCBRIDGE" = on ] || [ -f /etc/systemd/system/dcbridge-saves.service ]; then
    [ "$DCBRIDGE" = on ] && ns_module_enable dcbridge on
    sh "$DCB_MOD/system/dcbridge-setup" install || echo "DC Bridge: the setup did not finish; run it again from Settings > DC Bridge."
    NS_SERVICES="$NS_SERVICES dcbridge-saves.service"      # (re)started with the others; ppp and dcnet are started by udev
fi
