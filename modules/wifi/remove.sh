# Wi-Fi setup module - sourced when the module is gone from the folder, and by uninstall.sh: stops and removes its service and forgets its files.
systemctl disable --now dreampi-netswitch-wifi.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/dreampi-netswitch-wifi.service
rm -f "$DEST/wifi_button" "$DEST/wifi_hostapd.conf" "$DEST/wifi_dnsmasq.conf" "$DEST/wifi_demo" "$DEST/wifi_start" "$DEST/wifi_stop" "$DEST/wifi_connect"
