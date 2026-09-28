#!/usr/bin/env python3
# DreamPi Netswitch add-on - status on a single NeoPixel (WS2812) on GPIO10.
#
# GPIO10 is the Pi's SPI data pin (MOSI). Each NeoPixel bit is sent as one SPI
# byte at ~6.25 MHz: 0b11111000 for a 1 (0.8 us high) and 0b11000000 for a 0
# (0.32 us high). That meets WS2812 timing without DMA or special drivers.
# Needs SPI enabled (dtparam=spi=on) and python3-spidev.
#
# Shows the same DreamPi status as the web page, using the same colours.
# Works on Python 3 and 2.7.
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netswitch_web as web  # noqa: E402  (reuses the page's status logic)

try:
    import spidev
except ImportError:
    sys.exit("python3-spidev is missing: sudo apt install python3-spidev")

# Status (as returned by web.dreampi_state) -> (red, green, blue, blink)
COLOURS = {
    "ok":         (0, 255, 0, False),     # ready for calls
    "busy":       (255, 170, 0, True),    # starting up (blinking yellow)
    "call-dcnow": (255, 80, 0, False),    # in a call on DCNow! (orange)
    "call-dcnet": (0, 70, 255, False),    # in a call on DCNET (blue)
    "call":       (170, 0, 255, False),   # other calls, e.g. Netlink (purple)
    "off":        (255, 0, 0, True),      # DreamPi not running (blinking red)
    "unknown":    (60, 60, 60, False),    # state unknown (dim white)
}

BRIGHTNESS = float(os.environ.get("NETSWITCH_LED_BRIGHTNESS", "0.15"))
SPI_BUS = int(os.environ.get("NETSWITCH_LED_SPI_BUS", "0"))      # GPIO10 = bus 0
SPI_DEVICE = int(os.environ.get("NETSWITCH_LED_SPI_DEVICE", "0"))
SPI_HZ = 6400000   # the Pi rounds down to 6.25 MHz at both 250 and 400 MHz core
ONE, ZERO = 0xF8, 0xC0
RESET = [0] * 48   # > 50 us low latches the colour


def encode(r, g, b):
    """WS2812 wants green, red, blue, most significant bit first."""
    out = []
    for byte in (g, r, b):
        for i in range(7, -1, -1):
            out.append(ONE if (byte >> i) & 1 else ZERO)
    return RESET + out + RESET


def scaled(r, g, b):
    return tuple(int(round(c * BRIGHTNESS)) for c in (r, g, b))


def main():
    spi = spidev.SpiDev()
    try:
        spi.open(SPI_BUS, SPI_DEVICE)
    except (IOError, OSError) as e:
        sys.exit("Cannot open /dev/spidev%d.%d (%s). Is SPI enabled "
                 "(dtparam=spi=on in config.txt, then reboot)?" % (SPI_BUS, SPI_DEVICE, e))
    spi.max_speed_hz = SPI_HZ
    spi.mode = 0

    def off(*_):
        try:
            spi.xfer2(encode(0, 0, 0))
        finally:
            sys.exit(0)

    signal.signal(signal.SIGTERM, off)
    signal.signal(signal.SIGINT, off)

    phase = False
    while True:
        state, _ = web.dreampi_state()
        r, g, b, blink = COLOURS.get(state, COLOURS["unknown"])
        phase = not phase
        colour = scaled(r, g, b) if (phase or not blink) else (0, 0, 0)
        # Sent every half second, so a glitch (e.g. a CPU clock change during
        # a transfer) fixes itself straight away.
        spi.xfer2(encode(*colour))
        time.sleep(0.5)


if __name__ == "__main__":
    main()
