# Wi-Fi setup module - sourced when the module is gone from the folder, and by uninstall.sh: forgets its files.
rm -f "$DEST/wifi_button" "$DEST/wifi_hostapd.conf" "$DEST/wifi_dnsmasq.conf" "$DEST/wifi_demo" "$DEST/wifi_start" "$DEST/wifi_stop" "$DEST/wifi_connect"
