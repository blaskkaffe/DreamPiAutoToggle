# Status LED module - sourced by install.sh while this module is in the folder (so it shares install.sh's variables:
# $DEST, $LED_COUNT, $LED_GPIO ...). Sets up the LED service; the module's files are already copied to $DEST/modules/led.
# The count (0 = none: the service idles and the page hides the LED settings), output pin, wire order and colours are
# editable from the page afterwards. Without the module there is no service and no settings on the page, and the settings
# files stay for when it comes back.
rm -f "$DEST/led_enabled"   # old marker, no longer used
if [ -n "$LED_COUNT" ]; then echo "$LED_COUNT" > "$DEST/led_count"; fi
[ -f "$DEST/led_count" ] || echo 1 > "$DEST/led_count"
if [ -n "$LED_GPIO" ]; then echo "$LED_GPIO" > "$DEST/led_gpio"; fi
[ -f "$DEST/led_gpio" ] || echo 18 > "$DEST/led_gpio"
GPIO=$(cat "$DEST/led_gpio")
if [ "$(cat "$DEST/led_count")" = 0 ]; then
    echo "NeoPixels off (0 LEDs); set a count with --leds=N."
else
    echo "NeoPixel output on GPIO$GPIO: $(cat "$DEST/led_count") LED(s)"
fi
# GPIO10 needs the kernel's SPI driver; GPIO12/18/21 use /dev/mem directly
# and don't. Track what we changed in spi_added, so switching away from
# GPIO10 later (here or from the page) takes the setting back out again.
CONFIG_TXT=
for candidate in /boot/firmware/config.txt /boot/config.txt; do
    [ -f "$candidate" ] && CONFIG_TXT="$candidate" && break
done
if [ "$GPIO" = 10 ]; then
    if [ -n "$CONFIG_TXT" ] && ! grep -q '^dtparam=spi=on' "$CONFIG_TXT"; then
        printf '\ndtparam=spi=on  # added by dreampi-netswitch\n' >> "$CONFIG_TXT"
        echo "$CONFIG_TXT" > "$DEST/spi_added"
        echo "Enabled SPI in $CONFIG_TXT for GPIO10; reboot before the LEDs will work on it."
    elif [ -z "$CONFIG_TXT" ]; then
        echo "Could not find config.txt to enable SPI for GPIO10 - add dtparam=spi=on yourself and reboot."
    fi
elif [ -f "$DEST/spi_added" ]; then
    sed -i '/^dtparam=spi=on  # added by dreampi-netswitch$/d' "$(cat "$DEST/spi_added")"
    rm -f "$DEST/spi_added"
    echo "Removed the SPI setting added for GPIO10 (not needed for GPIO$GPIO)."
fi
cat > /etc/systemd/system/dreampi-netswitch-led.service <<UNIT
[Unit]
Description=DreamPi Netswitch status NeoPixel
After=network.target
StartLimitIntervalSec=0
# the module's files: if they are deleted from $DEST/modules/led the service is skipped quietly instead of failing in a loop
ConditionPathExists=$DEST/modules/led/netswitch_led.py
ConditionPathExists=$DEST/modules/led/netswitch_led_drivers.py
ConditionPathExists=$DEST/modules/led/netswitch_ledconfig.py

[Service]
ExecStart=$(command -v python3) $DEST/modules/led/netswitch_led.py
Restart=always
RestartSec=10
# the LED animation must never slow down the web page or DreamPi
Nice=10

[Install]
WantedBy=multi-user.target
UNIT
NS_SERVICES="$NS_SERVICES dreampi-netswitch-led.service"
