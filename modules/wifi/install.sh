# Wi-Fi setup module - sourced by install.sh while this module is in the folder. --wifi installs what the temporary
# access point needs (hostapd and dnsmasq) and switches the module on; --no-wifi switches it off; --wifi-demo runs it on
# dummy networks. Without a flag the module keeps whatever the Modules menu says. Setup itself runs in the buttons service.
if [ -f "$DEST/wifi_enabled" ]; then       # an older install used a marker file
    ns_module_enable wifi on
    rm -f "$DEST/wifi_enabled"
fi
if [ "$WIFI" = on ]; then
    ns_module_enable wifi on
    # The Wi-Fi setup access point needs hostapd and dnsmasq. Install them if
    # missing, and make sure their own systemd units stay off: this add-on
    # starts and stops them itself (dreampi-netswitch-buttons.service), so a
    # default dnsmasq listening on every interface would conflict with it.
    if ! command -v hostapd >/dev/null 2>&1 || ! command -v dnsmasq >/dev/null 2>&1; then
        if command -v apt-get >/dev/null 2>&1; then
            echo "Installing hostapd and dnsmasq (needed to host the Wi-Fi setup access point)..."
            apt-get update -q && apt-get install -y -q hostapd dnsmasq \
                || echo "Could not install hostapd/dnsmasq automatically; install them yourself, then re-run this."
        else
            echo "hostapd and/or dnsmasq not found and apt-get isn't available; install them yourself for Wi-Fi setup to work."
        fi
    fi
    systemctl disable --now hostapd.service 2>/dev/null || true
    systemctl disable --now dnsmasq.service 2>/dev/null || true
    echo "Wi-Fi setup module on (choose which button holds to start it in Settings > GPIO)"
elif [ "$WIFI" = off ]; then
    ns_module_enable wifi off
    rm -f "$DEST/wifi_button" "$DEST/wifi_hostapd.conf" "$DEST/wifi_dnsmasq.conf"
    echo "Wi-Fi setup module off (switch it on again in Settings > Modules)."
fi
if [ "$WIFI_DEMO" = on ]; then
    ns_module_enable wifi on
    touch "$DEST/wifi_demo"
    echo "Wi-Fi setup DEMO on: dummy networks, password \"demo\" connects, nothing on the Pi's network is touched. End it with --no-wifi-demo."
elif [ "$WIFI_DEMO" = off ]; then
    rm -f "$DEST/wifi_demo"
    echo "Wi-Fi setup demo off. (Add --no-wifi to switch the module off as well.)"
fi
