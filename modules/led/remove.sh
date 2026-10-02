# Status LED module - sourced by install.sh when the module is gone from the folder, and by uninstall.sh.
# Stops and removes the LED service, and takes back the SPI setting if the installer had switched it on for GPIO10.
# The settings files (led.json, led_count, led_gpio) stay, so adding the module back restores them.
systemctl disable --now dreampi-netswitch-led.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/dreampi-netswitch-led.service
if [ -f "$DEST/spi_added" ]; then     # SPI was only switched on for the LEDs
    sed -i '/^dtparam=spi=on  # added by dreampi-netswitch$/d' "$(cat "$DEST/spi_added")"
    rm -f "$DEST/spi_added"
    echo "Removed the SPI setting added for the LEDs (takes effect after a reboot)."
fi
