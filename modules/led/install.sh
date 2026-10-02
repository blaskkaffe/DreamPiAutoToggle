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
# GPIO10 needs the kernel's SPI driver (dtparam=spi=on in config.txt); GPIO12/18/21 use /dev/mem directly and don't.
# The LED service does the same whenever the pin is changed on the page; the helper only takes out a line it added itself.
"$(command -v python3)" "$DEST/modules/led/netswitch_led_spi.py" sync || true
cat > /etc/systemd/system/dreampi-netswitch-led.service <<UNIT
[Unit]
Description=DreamPi Netswitch status NeoPixel
After=network.target
StartLimitIntervalSec=0
# the module's files: if they are deleted from $DEST/modules/led the service is skipped quietly instead of failing in a loop
ConditionPathExists=$DEST/modules/led/netswitch_led.py
ConditionPathExists=$DEST/modules/led/netswitch_led_drivers.py
ConditionPathExists=$DEST/modules/led/netswitch_ledconfig.py
ConditionPathExists=$DEST/modules/led/netswitch_led_spi.py

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
