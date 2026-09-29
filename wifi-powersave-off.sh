#!/bin/sh
# DreamPi Netswitch add-on - run by the web page service before it starts.
# Wi-Fi power saving makes a Raspberry Pi drop off the network now and then,
# which looks like the web page being unreachable. This switches it off for
# every Wi-Fi interface. It resets on reboot, and runs again at every start.
for dev in /sys/class/net/*; do
    [ -d "$dev/wireless" ] || continue
    name=$(basename "$dev")
    if command -v iw >/dev/null 2>&1; then
        iw dev "$name" set power_save off 2>/dev/null
    elif command -v iwconfig >/dev/null 2>&1; then
        iwconfig "$name" power off 2>/dev/null
    fi
done
exit 0
