#!/usr/bin/env python3
# DreamPi Netswitch add-on - status on a single NeoPixel (WS2812) on GPIO18.
#
# GPIO18 is the Pi's PWM0 output. The PWM block runs in serialiser mode from
# the crystal (19.2 MHz / 8 = 2.4 MHz; 54 MHz / 22 on a Pi 4), independent of
# CPU/core clock changes, so each PWM bit lasts about 417 ns. Every NeoPixel bit becomes three PWM
# bits: 100 for a 0 (417 ns high) and 110 for a 1 (833 ns high). One pixel is
# 72 PWM bits, which fits in the PWM FIFO, so no DMA or driver is needed: the
# registers are written directly through /dev/mem (the service runs as root).
# When the FIFO runs empty the pin stays low, which latches the colour.
#
# Shows the same DreamPi status as the web page. Colours, blinking and
# brightness (global or per status) come from the page's settings (led.json, see netswitch_web).
import ctypes
import mmap
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netswitch_web as web  # noqa: E402  (reuses the page's status logic)

# ---------------------------------------------------------------- registers
GPIO_OFFSET = 0x200000
CLOCK_OFFSET = 0x101000
PWM_OFFSET = 0x20C000

GPFSEL1 = 0x04                 # GPIO 10-19 function select
CM_PWMCTL, CM_PWMDIV = 0xA0, 0xA4
CM_PASSWD = 0x5A000000
CM_ENAB, CM_BUSY, CM_SRC_OSC = 0x10, 0x80, 1
PWM_BIT_HZ = 2400000           # 3 PWM bits per NeoPixel bit = 800 kHz

PWM_CTL, PWM_STA, PWM_RNG1, PWM_FIF1 = 0x00, 0x04, 0x10, 0x18
PWEN1, MODE1, USEF1, CLRF1 = 0x01, 0x02, 0x20, 0x40
STA_EMPT1 = 0x02
STA_ERRORS = 0x1FC             # write 1 to clear WERR/RERR/GAPO/BERR


def peripheral_base():
    """Physical peripheral address (Pi 1/Zero, Pi 2/3 and Pi 4 differ)."""
    try:
        with open("/proc/device-tree/soc/ranges", "rb") as f:
            ranges = bytearray(f.read(12))
        base = int.from_bytes(ranges[4:8], "big")
        if base == 0:   # Pi 4: 64-bit parent address
            base = int.from_bytes(ranges[8:12], "big")
        return base
    except (IOError, OSError):
        return 0x3F000000   # Pi 2/3


class Block(object):
    """One 4 KB register block mapped from /dev/mem, 32-bit accesses only."""

    def __init__(self, fd, address):
        self.mem = mmap.mmap(fd, 4096, mmap.MAP_SHARED,
                             mmap.PROT_READ | mmap.PROT_WRITE, offset=address)

    def __getitem__(self, offset):
        return ctypes.c_uint32.from_buffer(self.mem, offset).value

    def __setitem__(self, offset, value):
        ctypes.c_uint32.from_buffer(self.mem, offset).value = value & 0xFFFFFFFF


class PwmPixel(object):
    def __init__(self, gpio, clock, pwm, osc_hz=19200000):
        self.gpio, self.clock, self.pwm = gpio, clock, pwm
        divider = int(round(float(osc_hz) / PWM_BIT_HZ))
        # GPIO18 -> ALT5 (PWM0): bits 24-26 of GPFSEL1 = 0b010
        self.gpio[GPFSEL1] = (self.gpio[GPFSEL1] & ~(7 << 24)) | (2 << 24)
        # PWM clock from the crystal
        self.pwm[PWM_CTL] = 0
        self.clock[CM_PWMCTL] = CM_PASSWD | (self.clock[CM_PWMCTL] & 0xFF & ~CM_ENAB)
        self._wait(lambda: not self.clock[CM_PWMCTL] & CM_BUSY)
        self.clock[CM_PWMDIV] = CM_PASSWD | (divider << 12)
        self.clock[CM_PWMCTL] = CM_PASSWD | CM_SRC_OSC
        self.clock[CM_PWMCTL] = CM_PASSWD | CM_SRC_OSC | CM_ENAB
        self._wait(lambda: self.clock[CM_PWMCTL] & CM_BUSY)
        self.pwm[PWM_RNG1] = 32

    @staticmethod
    def _wait(done, timeout=0.1):
        end = time.time() + timeout
        while not done() and time.time() < end:
            time.sleep(0.0001)

    def show(self, words):
        pwm = self.pwm
        pwm[PWM_CTL] = 0                     # stop; the pin idles low
        pwm[PWM_STA] = STA_ERRORS
        pwm[PWM_CTL] = CLRF1                 # empty the FIFO
        time.sleep(0.0001)
        for w in words:
            pwm[PWM_FIF1] = w
        pwm[PWM_CTL] = PWEN1 | MODE1 | USEF1  # shift it out once, then stay low
        self._wait(lambda: pwm[PWM_STA] & STA_EMPT1, 0.01)


def encode(r, g, b):
    """GRB, most significant bit first, 3 PWM bits per NeoPixel bit,
    packed into 32-bit FIFO words (the unused tail stays low)."""
    bits = 0
    for byte in (g, r, b):
        for i in range(7, -1, -1):
            bits = (bits << 3) | (0b110 if (byte >> i) & 1 else 0b100)
    bits <<= 96 - 72
    return [(bits >> shift) & 0xFFFFFFFF for shift in (64, 32, 0)]


def scaled(colour, brightness):
    """'#rrggbb' -> (r, g, b) scaled by brightness (0..1). At low brightness a
    channel that is on never rounds down to 0, so the hue stays recognisable
    (e.g. orange doesn't turn red at 2 %)."""
    out = []
    for i in (1, 3, 5):
        c = int(colour[i:i + 2], 16)
        v = int(round(c * brightness))
        out.append(max(v, 1) if c and brightness > 0 else v)
    return tuple(out)


def open_pixel():
    base = peripheral_base()
    osc_hz = 54000000 if base == 0xFE000000 else 19200000   # Pi 4 crystal
    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    try:
        return PwmPixel(Block(fd, base + GPIO_OFFSET),
                        Block(fd, base + CLOCK_OFFSET),
                        Block(fd, base + PWM_OFFSET), osc_hz)
    finally:
        os.close(fd)   # the mappings stay valid


def main():
    try:
        pixel = open_pixel()
    except (IOError, OSError) as e:
        sys.exit("Cannot access the PWM hardware through /dev/mem (%s). "
                 "The LED service must run as root." % e)

    def off(*_):
        try:
            pixel.show(encode(0, 0, 0))
        finally:
            sys.exit(0)

    signal.signal(signal.SIGTERM, off)
    signal.signal(signal.SIGINT, off)

    phase = False
    while True:
        try:
            look = web.status_look()
            brightness = look["brightness"]   # this status's own level, or the global one
        except Exception:   # never let a bad read stop the LED loop
            look, brightness = {"color": "#3c3c3c", "blink": False}, 0.08
        phase = not phase
        on = phase or not look["blink"]
        colour = scaled(look["color"], brightness) if on else (0, 0, 0)
        # Sent every half second, so a garbled frame fixes itself.
        pixel.show(encode(*colour))
        time.sleep(0.5)


if __name__ == "__main__":
    main()
