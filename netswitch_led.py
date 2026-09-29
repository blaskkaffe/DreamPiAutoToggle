#!/usr/bin/env python3
# DreamPi Netswitch add-on - status on NeoPixels (WS2812) on GPIO18.
#
# GPIO18 is the Pi's PWM0 output. The PWM block runs in serialiser mode from
# the crystal (19.2 MHz / 8 = 2.4 MHz; 54 MHz / 22 on a Pi 4), independent of
# CPU/core clock changes, so each PWM bit lasts about 417 ns. Every NeoPixel
# bit becomes three PWM bits: 100 for a 0 (417 ns high) and 110 for a 1
# (833 ns high). Registers are written directly through /dev/mem (the service
# runs as root), so no driver or Python package is needed.
#
# - One LED: its 72 PWM bits fit in the PWM FIFO and are written by the CPU.
# - A strip (2 or more LEDs): the frame is too long for the FIFO, so it is
#   put in GPU-shared memory (allocated through the VideoCore mailbox,
#   /dev/vcio) and a DMA channel feeds it to the PWM FIFO, the same way the
#   rpi_ws281x library does it.
# When the data runs out the pin stays low, which latches the colours.
#
# What it shows comes from the page's settings (led.json, see netswitch_web):
# per message (DreamPi status, network/internet errors, Ethernet/Wi-Fi) and
# selected network: on/off, colour, effect, speed, brightness and LED section.
# Errors outrank information; see netswitch_web.active_messages().
# The number of LEDs is in /opt/dreampi-netswitch/led_count (install.sh).
import array
import colorsys
import ctypes
import fcntl
import math
import mmap
import os
import signal
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netswitch_web as web  # noqa: E402  (reuses the page's status logic)

FPS = 50
REFRESH = 0.25     # seconds between re-reading DreamPi's state and led.json

# ---------------------------------------------------------------- registers
GPIO_OFFSET = 0x200000
CLOCK_OFFSET = 0x101000
PWM_OFFSET = 0x20C000
DMA_OFFSET = 0x007000
DMA_CHANNEL = 10               # same default as rpi_ws281x
PWM_FIFO_BUS = 0x7E20C018      # PWM FIF1 as seen by the DMA engine

GPFSEL1 = 0x04                 # GPIO 10-19 function select
CM_PWMCTL, CM_PWMDIV = 0xA0, 0xA4
CM_PASSWD = 0x5A000000
CM_ENAB, CM_BUSY, CM_SRC_OSC = 0x10, 0x80, 1
PWM_BIT_HZ = 2400000           # 3 PWM bits per NeoPixel bit = 800 kHz

PWM_CTL, PWM_STA, PWM_DMAC, PWM_RNG1, PWM_FIF1 = 0x00, 0x04, 0x08, 0x10, 0x18
PWEN1, MODE1, USEF1, CLRF1 = 0x01, 0x02, 0x20, 0x40
STA_EMPT1 = 0x02
STA_ERRORS = 0x1FC             # write 1 to clear WERR/RERR/GAPO/BERR
DMAC_ENAB = 1 << 31

DMA_CS, DMA_CONBLK, DMA_DEBUG = 0x00, 0x04, 0x20
CS_ACTIVE, CS_END, CS_INT = 1 << 0, 1 << 1, 1 << 2
CS_WAIT_WRITES, CS_RESET = 1 << 28, 1 << 31
TI_WAIT_RESP, TI_DEST_DREQ, TI_SRC_INC, TI_NO_WIDE = 1 << 3, 1 << 6, 1 << 8, 1 << 26
PERMAP_PWM = 5

RESET_WORDS = 24               # > 300 us of low level after the data


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
    """A register block mapped from /dev/mem, 32-bit accesses only."""

    def __init__(self, fd, address, size=4096):
        self.mem = mmap.mmap(fd, size, mmap.MAP_SHARED,
                             mmap.PROT_READ | mmap.PROT_WRITE, offset=address)

    def __getitem__(self, offset):
        return ctypes.c_uint32.from_buffer(self.mem, offset).value

    def __setitem__(self, offset, value):
        ctypes.c_uint32.from_buffer(self.mem, offset).value = value & 0xFFFFFFFF


def _wait(done, timeout=0.1):
    end = time.time() + timeout
    while not done() and time.time() < end:
        time.sleep(0.0001)


# ---------------------------------------------------------------- encoding
def _symbols(byte):
    """8 NeoPixel bits -> 24 PWM bits (3 per bit), as 3 bytes."""
    bits = 0
    for i in range(7, -1, -1):
        bits = (bits << 3) | (0b110 if (byte >> i) & 1 else 0b100)
    return bits.to_bytes(3, "big")


_TABLE = [_symbols(b) for b in range(256)]


def encode_bytes(pixels):
    """[(r, g, b), ...] -> PWM bit stream, GRB order, MSB first, padded to
    whole 32-bit words."""
    out = b"".join(_TABLE[g] + _TABLE[r] + _TABLE[b] for r, g, b in pixels)
    return out + b"\0" * (-len(out) % 4)


def encode(r, g, b):
    """One pixel -> 3 FIFO words."""
    data = encode_bytes([(r, g, b)])
    return [int.from_bytes(data[i:i + 4], "big") for i in range(0, len(data), 4)]


# ---------------------------------------------------------------- hardware
class PwmOutput(object):
    """GPIO18 as PWM0 in serialiser mode, clocked from the crystal."""

    def __init__(self, gpio, clock, pwm, osc_hz=19200000):
        self.gpio, self.clock, self.pwm = gpio, clock, pwm
        divider = int(round(float(osc_hz) / PWM_BIT_HZ))
        # GPIO18 -> ALT5 (PWM0): bits 24-26 of GPFSEL1 = 0b010
        self.gpio[GPFSEL1] = (self.gpio[GPFSEL1] & ~(7 << 24)) | (2 << 24)
        self.pwm[PWM_CTL] = 0
        self.clock[CM_PWMCTL] = CM_PASSWD | (self.clock[CM_PWMCTL] & 0xFF & ~CM_ENAB)
        _wait(lambda: not self.clock[CM_PWMCTL] & CM_BUSY)
        self.clock[CM_PWMDIV] = CM_PASSWD | (divider << 12)
        self.clock[CM_PWMCTL] = CM_PASSWD | CM_SRC_OSC
        self.clock[CM_PWMCTL] = CM_PASSWD | CM_SRC_OSC | CM_ENAB
        _wait(lambda: self.clock[CM_PWMCTL] & CM_BUSY)
        self.pwm[PWM_RNG1] = 32


class FifoPixel(PwmOutput):
    """A single LED: 3 words written straight into the PWM FIFO."""

    def show(self, pixels):
        pwm = self.pwm
        pwm[PWM_CTL] = 0                     # stop; the pin idles low
        pwm[PWM_STA] = STA_ERRORS
        pwm[PWM_CTL] = CLRF1                 # empty the FIFO
        time.sleep(0.0001)
        for w in encode(*pixels[0]):
            pwm[PWM_FIF1] = w
        pwm[PWM_CTL] = PWEN1 | MODE1 | USEF1  # shift it out once, then stay low
        _wait(lambda: pwm[PWM_STA] & STA_EMPT1, 0.01)

    def close(self):
        self.pwm[PWM_CTL] = 0


class Mailbox(object):
    """VideoCore mailbox (/dev/vcio) for GPU memory the DMA engine can read."""

    def __init__(self):
        self.fd = os.open("/dev/vcio", os.O_RDWR)
        size = ctypes.sizeof(ctypes.c_void_p)
        self.ioctl = (3 << 30) | (size << 16) | (100 << 8) | 0   # _IOWR(100, 0, char *)

    def call(self, tag, *args):
        words = [0, 0, tag, 4 * max(len(args), 1), 0] + list(args or [0]) + [0]
        words[0] = 4 * len(words)
        buf = array.array("I", words)
        fcntl.ioctl(self.fd, self.ioctl, buf, True)
        if buf[1] != 0x80000000:
            raise OSError("mailbox call 0x%x failed" % tag)
        return buf[5]

    def close(self):
        os.close(self.fd)


class DmaStrip(PwmOutput):
    """Several LEDs: frame in GPU memory, fed to the PWM FIFO by DMA."""

    def __init__(self, fd, base, count, osc_hz):
        self.count = count
        self.data_len = len(encode_bytes([(0, 0, 0)] * count)) + 4 * RESET_WORDS
        self.size = (32 + self.data_len + 4095) // 4096 * 4096
        self.mbox = Mailbox()
        # Pi 1 uses the L2-cached alias (flags 0xC); Pi 2 and later "direct" (0x4)
        flags = 0xC if base == 0x20000000 else 0x4
        self.handle = self.mbox.call(0x3000C, self.size, 4096, flags)   # allocate
        if not self.handle:
            raise OSError("could not allocate GPU memory for the LED strip")
        self.bus = self.mbox.call(0x3000D, self.handle)                 # lock
        self.mem = mmap.mmap(fd, self.size, mmap.MAP_SHARED,
                             mmap.PROT_READ | mmap.PROT_WRITE,
                             offset=self.bus & ~0xC0000000)
        self.dma = Block(fd, base + DMA_OFFSET)          # channels 0-14, 0x100 apart
        self.dma_off = DMA_CHANNEL * 0x100
        PwmOutput.__init__(self, Block(fd, base + GPIO_OFFSET), Block(fd, base + CLOCK_OFFSET),
                           Block(fd, base + PWM_OFFSET), osc_hz)
        # Control block at offset 0, data right after it
        cb = struct.pack("<8I", TI_NO_WIDE | TI_WAIT_RESP | TI_DEST_DREQ | TI_SRC_INC | (PERMAP_PWM << 16),
                         self.bus + 32, PWM_FIFO_BUS, self.data_len, 0, 0, 0, 0)
        self.mem[0:32] = cb
        self.mem[32:32 + self.data_len] = b"\0" * self.data_len
        pwm = self.pwm
        pwm[PWM_CTL] = CLRF1
        time.sleep(0.0001)
        pwm[PWM_STA] = STA_ERRORS
        pwm[PWM_DMAC] = DMAC_ENAB | (7 << 8) | 3     # panic 7, dreq 3
        pwm[PWM_CTL] = PWEN1 | MODE1 | USEF1

    def _reg(self, offset, value=None):
        if value is None:
            return self.dma[self.dma_off + offset]
        self.dma[self.dma_off + offset] = value

    def show(self, pixels):
        _wait(lambda: not self._reg(DMA_CS) & CS_ACTIVE, 0.05)
        data = encode_bytes(pixels)
        words = array.array("I", data)
        words.byteswap()                     # PWM shifts each word MSB first
        data = words.tobytes() + b"\0" * (4 * RESET_WORDS)
        self.mem[32:32 + len(data)] = data
        self._reg(DMA_CS, CS_RESET)
        time.sleep(0.00001)
        self._reg(DMA_CS, CS_INT | CS_END)
        self._reg(DMA_CONBLK, self.bus)
        self._reg(DMA_DEBUG, 7)              # clear error flags
        self._reg(DMA_CS, CS_WAIT_WRITES | (15 << 20) | (15 << 16) | CS_ACTIVE)

    def close(self):
        try:
            _wait(lambda: not self._reg(DMA_CS) & CS_ACTIVE, 0.05)
            self._reg(DMA_CS, CS_RESET)
            self.pwm[PWM_DMAC] = 0
            self.pwm[PWM_CTL] = 0
        finally:
            try:
                self.mbox.call(0x3000E, self.handle)   # unlock
                self.mbox.call(0x3000F, self.handle)   # release
            finally:
                self.mbox.close()


def open_output(count):
    base = peripheral_base()
    osc_hz = 54000000 if base == 0xFE000000 else 19200000   # Pi 4 crystal
    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    try:
        if count <= 1:
            return FifoPixel(Block(fd, base + GPIO_OFFSET), Block(fd, base + CLOCK_OFFSET),
                             Block(fd, base + PWM_OFFSET), osc_hz)
        return DmaStrip(fd, base, count, osc_hz)
    finally:
        os.close(fd)   # the mappings stay valid


# ---------------------------------------------------------------- effects
# Each effect gives a list of (r, g, b) floats 0..1 per LED at time t.
# Periods in seconds for (slow, fast).
PERIODS = {
    "blink": (1.0, 0.4),
    "breathe": (4.0, 1.6),
    "rainbow": (20.0, 10.0),
    "scanner": (3.0, 1.2),
    "comet": (3.0, 1.2),
    "chase": (0.6, 0.24),      # time for one full 3-LED step cycle
    "twinkle": (3.0, 1.2),
    "rgb": (20.0, 10.0),       # fast = a standard, calm RGB cycle; slow = half that speed
}


def hex_rgb(colour):
    return tuple(int(colour[i:i + 2], 16) / 255.0 for i in (1, 3, 5))


def hue(h):
    return colorsys.hsv_to_rgb(h % 1.0, 1.0, 1.0)


def _mul(c, f):
    return (c[0] * f, c[1] * f, c[2] * f)


def _rand(i, salt):
    """Stable pseudo-random 0..1 per LED."""
    x = math.sin(i * 12.9898 + salt * 78.233) * 43758.5453
    return x - math.floor(x)


def effect_frame(effect, speed, colour, t, n):
    c = hex_rgb(colour)
    fast = speed == "fast"
    if effect == "solid":
        return [c] * n
    period = PERIODS.get(effect, (1.0, 0.4))[1 if fast else 0]
    phase = (t / period) % 1.0
    if effect == "rgb":
        return [hue(phase)] * n
    if effect == "blink":
        return [c if phase < 0.5 else (0, 0, 0)] * n
    if effect == "breathe":
        f = 0.5 + 0.5 * math.cos(2 * math.pi * phase)    # starts bright
        return [_mul(c, f * f)] * n
    if n == 1:   # strip effects on a single LED
        if effect == "rainbow":
            return [hue(phase)]
        if effect in ("chase", "twinkle"):
            return [c if phase < 0.5 else (0, 0, 0)]
        f = 0.5 + 0.5 * math.cos(2 * math.pi * phase)
        return [_mul(c, f * f)]
    if effect == "rainbow":
        return [hue(phase + float(i) / n) for i in range(n)]
    if effect == "scanner":
        pos = (n - 1) * (1 - abs(2 * phase - 1))            # back and forth
        return [_mul(c, max(0.0, 1 - abs(i - pos) / 1.5) ** 2) for i in range(n)]
    if effect == "comet":
        head = phase * n
        tail = max(2.0, n / 4.0)
        out = []
        for i in range(n):
            d = (head - i) % n
            out.append(_mul(c, max(0.0, 1 - d / tail) ** 2))
        return out
    if effect == "chase":
        step = int(phase * 3 + 1e-6) % 3     # 1e-6: no float rounding at the step edges
        return [c if (i - step) % 3 == 0 else (0, 0, 0) for i in range(n)]   # moves forward
    if effect == "twinkle":
        out = []
        for i in range(n):
            p = period * (0.6 + 0.8 * _rand(i, 1))
            s = math.sin(2 * math.pi * (t / p + _rand(i, 2)))
            out.append(_mul(c, max(0.0, s) ** 6))
        return out
    return [c] * n


def to_bytes(frame, brightness):
    """Floats 0..1 -> 0..255 with brightness. A channel that is on never
    rounds down to 0, so colours stay recognisable at low brightness."""
    out = []
    for r, g, b in frame:
        px = []
        for v in (r, g, b):
            x = v * 255 * brightness
            px.append(0 if x <= 0 else max(1, min(255, int(round(x)))))
        out.append(tuple(px))
    return out


def scaled(colour, brightness):
    """'#rrggbb' at a brightness, for a single solid pixel."""
    return to_bytes([hex_rgb(colour)], brightness)[0]


# ---------------------------------------------------------------- composing
def render(messages, now, count, clocks=None):
    """Draw the active messages (lowest priority first) into one frame.
    Each message covers all LEDs or its own section; later (more important)
    messages draw over earlier ones, and uncovered LEDs stay dark.
    Every message's effect starts from its beginning (blink on, breathe
    bright) when the message appears or its look changes, so a change shows
    straight away instead of landing somewhere in the middle of a cycle.
    clocks keeps those start times between frames."""
    if clocks is None:
        clocks = {}
    frame = [(0, 0, 0)] * count
    seen = set()
    for m in messages:
        key = m.get("key", "")
        seen.add(key)
        sig = (m.get("effect"), m.get("speed"), m.get("color"), m.get("leds"))
        if key not in clocks or clocks[key][0] != sig:
            clocks[key] = (sig, now)
        leds = m.get("leds")
        first, last = (1, count) if not leds else (max(1, leds[0]), min(count, leds[1]))
        if first > last:
            continue          # section lies beyond the end of this strip
        n = last - first + 1
        part = to_bytes(effect_frame(m.get("effect", "solid"), m.get("speed", "slow"),
                                     m.get("color", "#3c3c3c"), now - clocks[key][1], n),
                        m.get("brightness", 0.08))
        frame[first - 1:last] = part
    for key in list(clocks):
        if key not in seen:
            del clocks[key]   # starts over next time the message appears
    return frame


# ---------------------------------------------------------------- main loop
def main():
    count = web.led_count() or 1
    try:
        out = open_output(count)
    except (IOError, OSError) as e:
        sys.exit("Cannot drive the LEDs on GPIO18 (%s). The LED service must run as root." % e)

    def stop(*_):
        try:
            out.show([(0, 0, 0)] * count)
            time.sleep(0.02)
            out.close()
        finally:
            sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    messages = []
    clocks = {}
    last_frame, last_sent = None, 0.0
    next_read = 0.0
    while True:
        now = time.time()
        if now >= next_read:
            try:
                messages = web.active_messages()
            except Exception:   # never let a bad read stop the LED loop
                pass
            next_read = now + REFRESH
        frame = render(messages, now, count, clocks)
        # Unchanged frames (solid colours) are only resent twice a second,
        # which fixes any garbled frame and keeps the CPU free for DreamPi.
        if frame != last_frame or now - last_sent >= 0.5:
            out.show(frame)
            last_frame, last_sent = frame, now
        time.sleep(max(0.0, 1.0 / FPS - (time.time() - now)))


if __name__ == "__main__":
    main()
