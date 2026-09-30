#!/usr/bin/env python3
# DreamPi Netswitch add-on - status on NeoPixels (WS2812), GPIO18 by default.
#
# Four GPIO pins are supported, each through a different Pi peripheral, all
# clocked from the crystal (independent of CPU/core clock changes) so every
# NeoPixel bit is 3 output-clock ticks: 100 for a 0, 110 for a 1 (417/833 ns
# at the 2.4 MHz - 19.2 MHz/8, or 54 MHz/22 on a Pi 4 - bit rate this scheme
# needs). Registers are written directly through /dev/mem (the service runs
# as root), so no driver or Python package is needed, except on GPIO10.
# - GPIO12 and GPIO18: the Pi's PWM0 output (same peripheral, only the pin's
#   ALT function differs - ALT0 on GPIO12, ALT5 on GPIO18).
# - GPIO21: the Pi's PCM output (PCM_DOUT, ALT0), the same technique through
#   a different peripheral - used instead of PWM so the analog audio jack
#   (which also uses PWM) is free, or when GPIO12/18 are wanted for something
#   else. Register values from github.com/jgarff/rpi_ws281x (pcm.h, ws2811.c).
# - GPIO10: the Pi's hardware SPI0 (MOSI), through the kernel's own spidev
#   driver (needs `dtparam=spi=on`, which install.sh adds when this pin is
#   chosen) instead of /dev/mem. A whole SPI *byte* stands for one NeoPixel
#   bit (0xF8/0xC0 at ~6.4 MHz, close enough to WS2812 timing) since spidev
#   only deals in whole bytes; this is what older versions of this add-on
#   always used, just generalised here to any LED count. No DMA: the kernel
#   driver blocks until the whole buffer is sent.
#
# - One LED on GPIO12/18: its 72 PWM bits fit in the PWM FIFO and are written
#   by the CPU (FifoPixel).
# - Everything else on GPIO12/18/21: the frame is put in GPU-shared memory
#   (allocated through the VideoCore mailbox, /dev/vcio) and a DMA channel
#   feeds it to the PWM/PCM FIFO, the same way the rpi_ws281x library does it
#   (DmaStrip; PcmStrip is the same idea against the PCM peripheral).
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

GPIO_PINS = (10, 12, 18, 21)   # allowed LED output pins
DEFAULT_GPIO = 18

# ---------------------------------------------------------------- registers
GPIO_OFFSET = 0x200000
CLOCK_OFFSET = 0x101000
PWM_OFFSET = 0x20C000
PCM_OFFSET = 0x203000
DMA_OFFSET = 0x007000
DMA_CHANNEL = 10               # same default as rpi_ws281x
PWM_FIFO_BUS = 0x7E20C018      # PWM FIF1 as seen by the DMA engine
PCM_FIFO_BUS = 0x7E203004      # PCM's fifo register, likewise

GPFSEL1 = 0x04                 # GPIO 10-19 function select (GPIO10, 12, 18)
GPFSEL2 = 0x08                 # GPIO 20-29 function select (GPIO21)
_PWM_ALT = {12: 0b100, 18: 0b010}   # ALT0, ALT5
_PCM_ALT = {21: 0b100}             # ALT0
CM_PWMCTL, CM_PWMDIV = 0xA0, 0xA4
CM_PCMCTL, CM_PCMDIV = 0x98, 0x9C
CM_PASSWD = 0x5A000000
CM_ENAB, CM_BUSY, CM_SRC_OSC = 0x10, 0x80, 1
PWM_BIT_HZ = 2400000           # 3 output-clock ticks per NeoPixel bit = 800 kHz

PWM_CTL, PWM_STA, PWM_DMAC, PWM_RNG1, PWM_FIF1 = 0x00, 0x04, 0x08, 0x10, 0x18
PWEN1, MODE1, USEF1, CLRF1 = 0x01, 0x02, 0x20, 0x40
STA_EMPT1 = 0x02
STA_ERRORS = 0x1FC             # write 1 to clear WERR/RERR/GAPO/BERR
DMAC_ENAB = 1 << 31

PCM_CS, PCM_FIFO, PCM_MODE, PCM_TXC, PCM_DREQ = 0x00, 0x04, 0x08, 0x10, 0x14
PCM_CS_EN, PCM_CS_TXON, PCM_CS_TXCLR, PCM_CS_DMAEN = 1 << 0, 1 << 2, 1 << 3, 1 << 9


def _pcm_mode(flen, fslen):
    return ((flen & 0x3FF) << 10) | (fslen & 0x3FF)


def _pcm_txc(pos, wid):
    return (1 << 31) | (1 << 30) | ((pos & 0x3FF) << 20) | ((wid & 0xF) << 16)   # CH1WEX|CH1EN|CH1POS|CH1WID


def _pcm_dreq(tx, panic):
    return ((panic & 0x7F) << 24) | ((tx & 0x7F) << 8)


PERMAP_PWM, PERMAP_PCM = 5, 2

DMA_CS, DMA_CONBLK, DMA_DEBUG = 0x00, 0x04, 0x20
CS_ACTIVE, CS_END, CS_INT = 1 << 0, 1 << 1, 1 << 2
CS_WAIT_WRITES, CS_RESET = 1 << 28, 1 << 31
TI_WAIT_RESP, TI_DEST_DREQ, TI_SRC_INC, TI_NO_WIDE = 1 << 3, 1 << 6, 1 << 8, 1 << 26

RESET_WORDS = 24               # > 300 us of low level after the data

# ---------------------------------------------------------- SPI (GPIO10)
SPI_IOC_WR_MODE = 0x40016B01
SPI_IOC_WR_MAX_SPEED_HZ = 0x40046B04
SPI_HZ = 6400000                # the Pi rounds this down to 6.25 MHz
SPI_ONE, SPI_ZERO = 0xF8, 0xC0  # one SPI byte per NeoPixel bit (0.8/0.3 us high at 6.25 MHz)
SPI_RESET_BYTES = 80            # > 50 us low after the data


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

# Wire order: which of (r, g, b) goes out first/second/third. Most WS2812s
# are GRB; a few clones are RGB or another order, hence the config option.
ORDERS = {"RGB": (0, 1, 2), "RBG": (0, 2, 1), "GRB": (1, 0, 2),
         "GBR": (1, 2, 0), "BRG": (2, 0, 1), "BGR": (2, 1, 0)}
DEFAULT_ORDER = ORDERS["GRB"]


def encode_bytes(pixels, order=DEFAULT_ORDER):
    """[(r, g, b), ...] -> PWM bit stream in the given wire order, MSB
    first, padded to whole 32-bit words."""
    a, b, c = order
    out = b"".join(_TABLE[px[a]] + _TABLE[px[b]] + _TABLE[px[c]] for px in pixels)
    return out + b"\0" * (-len(out) % 4)


def encode(r, g, b, order=DEFAULT_ORDER):
    """One pixel -> 3 FIFO words."""
    data = encode_bytes([(r, g, b)], order)
    return [int.from_bytes(data[i:i + 4], "big") for i in range(0, len(data), 4)]


# ---------------------------------------------------------------- hardware
def _set_alt(gpio_block, fsel_offset, pin_shift, alt):
    gpio_block[fsel_offset] = (gpio_block[fsel_offset] & ~(7 << pin_shift)) | (alt << pin_shift)


def _init_clock(clock, ctl_off, div_off, osc_hz, bit_hz):
    """Point a clock generator (PWM's or PCM's - same register layout, a
    different pair of offsets) at the crystal, divided down to bit_hz."""
    divider = int(round(float(osc_hz) / bit_hz))
    clock[ctl_off] = CM_PASSWD | (clock[ctl_off] & 0xFF & ~CM_ENAB)
    _wait(lambda: not clock[ctl_off] & CM_BUSY)
    clock[div_off] = CM_PASSWD | (divider << 12)
    clock[ctl_off] = CM_PASSWD | CM_SRC_OSC
    clock[ctl_off] = CM_PASSWD | CM_SRC_OSC | CM_ENAB
    _wait(lambda: clock[ctl_off] & CM_BUSY)


class PwmOutput(object):
    """GPIO12 or GPIO18 as PWM0 in serialiser mode, clocked from the crystal."""

    def __init__(self, gpio, clock, pwm, osc_hz=19200000, pin=DEFAULT_GPIO):
        self.gpio, self.clock, self.pwm = gpio, clock, pwm
        self.order = DEFAULT_ORDER
        _set_alt(self.gpio, GPFSEL1, (pin - 10) * 3, _PWM_ALT[pin])   # GPIO10-19 share GPFSEL1
        self.pwm[PWM_CTL] = 0
        _init_clock(self.clock, CM_PWMCTL, CM_PWMDIV, osc_hz, PWM_BIT_HZ)
        self.pwm[PWM_RNG1] = 32


class FifoPixel(PwmOutput):
    """A single LED: 3 words written straight into the PWM FIFO."""

    def show(self, pixels):
        pwm = self.pwm
        pwm[PWM_CTL] = 0                     # stop; the pin idles low
        pwm[PWM_STA] = STA_ERRORS
        pwm[PWM_CTL] = CLRF1                 # empty the FIFO
        time.sleep(0.0001)
        for w in encode(pixels[0][0], pixels[0][1], pixels[0][2], self.order):
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


def _alloc_gpu(fd, base, size):
    """GPU-shared memory the DMA engine can read, via the VideoCore mailbox."""
    mbox = Mailbox()
    # Pi 1 uses the L2-cached alias (flags 0xC); Pi 2 and later "direct" (0x4)
    flags = 0xC if base == 0x20000000 else 0x4
    handle = mbox.call(0x3000C, size, 4096, flags)   # allocate
    if not handle:
        raise OSError("could not allocate GPU memory for the LED strip")
    bus = mbox.call(0x3000D, handle)                 # lock
    mem = mmap.mmap(fd, size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE,
                    offset=bus & ~0xC0000000)
    return mbox, handle, bus, mem


def _free_gpu(mbox, handle):
    try:
        mbox.call(0x3000E, handle)   # unlock
        mbox.call(0x3000F, handle)   # release
    finally:
        mbox.close()


class _DmaOutput(object):
    """Shared plumbing for a strip fed by DMA from GPU memory into a fixed
    peripheral FIFO - what DmaStrip (PWM) and PcmStrip (PCM) both are.
    Subclasses set up their own peripheral (GPIO ALT function, clock, FIFO
    enable) and then call _dma_setup(); show()/close() don't otherwise
    differ between the two peripherals."""

    def _dma_setup(self, fd, base, count, dest_bus, permap):
        self.count = count
        self.data_len = len(encode_bytes([(0, 0, 0)] * count)) + 4 * RESET_WORDS
        size = (32 + self.data_len + 4095) // 4096 * 4096
        self.mbox, self.handle, self.bus, self.mem = _alloc_gpu(fd, base, size)
        self.dma = Block(fd, base + DMA_OFFSET)          # channels 0-14, 0x100 apart
        self.dma_off = DMA_CHANNEL * 0x100
        # Control block at offset 0, data right after it
        cb = struct.pack("<8I", TI_NO_WIDE | TI_WAIT_RESP | TI_DEST_DREQ | TI_SRC_INC | (permap << 16),
                         self.bus + 32, dest_bus, self.data_len, 0, 0, 0, 0)
        self.mem[0:32] = cb
        self.mem[32:32 + self.data_len] = b"\0" * self.data_len

    def _reg(self, offset, value=None):
        if value is None:
            return self.dma[self.dma_off + offset]
        self.dma[self.dma_off + offset] = value

    def show(self, pixels):
        _wait(lambda: not self._reg(DMA_CS) & CS_ACTIVE, 0.05)
        data = encode_bytes(pixels, self.order)
        words = array.array("I", data)
        words.byteswap()                     # PWM and PCM both shift each word MSB first
        data = words.tobytes() + b"\0" * (4 * RESET_WORDS)
        self.mem[32:32 + len(data)] = data
        self._reg(DMA_CS, CS_RESET)
        time.sleep(0.00001)
        self._reg(DMA_CS, CS_INT | CS_END)
        self._reg(DMA_CONBLK, self.bus)
        self._reg(DMA_DEBUG, 7)              # clear error flags
        self._reg(DMA_CS, CS_WAIT_WRITES | (15 << 20) | (15 << 16) | CS_ACTIVE)

    def _dma_close(self):
        try:
            _wait(lambda: not self._reg(DMA_CS) & CS_ACTIVE, 0.05)
            self._reg(DMA_CS, CS_RESET)
        finally:
            _free_gpu(self.mbox, self.handle)


class DmaStrip(PwmOutput, _DmaOutput):
    """Several LEDs on GPIO12/18: frame in GPU memory, fed to the PWM FIFO
    by DMA."""

    def __init__(self, fd, base, count, osc_hz, pin=DEFAULT_GPIO):
        PwmOutput.__init__(self, Block(fd, base + GPIO_OFFSET), Block(fd, base + CLOCK_OFFSET),
                           Block(fd, base + PWM_OFFSET), osc_hz, pin=pin)
        self._dma_setup(fd, base, count, PWM_FIFO_BUS, PERMAP_PWM)
        pwm = self.pwm
        pwm[PWM_CTL] = CLRF1
        time.sleep(0.0001)
        pwm[PWM_STA] = STA_ERRORS
        pwm[PWM_DMAC] = DMAC_ENAB | (7 << 8) | 3     # panic 7, dreq 3
        pwm[PWM_CTL] = PWEN1 | MODE1 | USEF1

    def close(self):
        try:
            self._dma_close()
        finally:
            self.pwm[PWM_DMAC] = 0
            self.pwm[PWM_CTL] = 0


class PcmStrip(_DmaOutput):
    """Any LED count on GPIO21 (PCM_DOUT): the PCM-peripheral equivalent of
    DmaStrip, used so GPIO12/18 (and the PWM-driven analog audio jack) stay
    free. Register values are from rpi_ws281x (pcm.h, ws2811.c setup_pcm());
    not yet verified on real hardware."""

    def __init__(self, fd, base, count, osc_hz):
        self.order = DEFAULT_ORDER
        gpio = Block(fd, base + GPIO_OFFSET)
        _set_alt(gpio, GPFSEL2, (21 - 20) * 3, _PCM_ALT[21])   # GPIO21 -> ALT0 (PCM_DOUT)
        self.pcm = Block(fd, base + PCM_OFFSET)
        self.pcm[PCM_CS] = PCM_CS_EN
        _init_clock(Block(fd, base + CLOCK_OFFSET), CM_PCMCTL, CM_PCMDIV, osc_hz, PWM_BIT_HZ)
        self.pcm[PCM_MODE] = _pcm_mode(31, 1)
        self.pcm[PCM_TXC] = _pcm_txc(0, 8)               # channel 1, 8-bit samples, position 0
        self._dma_setup(fd, base, count, PCM_FIFO_BUS, PERMAP_PCM)
        self.pcm[PCM_CS] |= PCM_CS_TXCLR
        time.sleep(0.00001)
        self.pcm[PCM_CS] |= PCM_CS_DMAEN
        self.pcm[PCM_DREQ] = _pcm_dreq(0x3F, 0x10)
        self.pcm[PCM_CS] |= PCM_CS_TXON

    def close(self):
        try:
            self._dma_close()
        finally:
            self.pcm[PCM_CS] = 0


def _spi_symbols(byte):
    return bytes(SPI_ONE if (byte >> i) & 1 else SPI_ZERO for i in range(7, -1, -1))


_SPI_TABLE = [_spi_symbols(b) for b in range(256)]


class SpiStrip(object):
    """Any LED count on GPIO10 (SPI0 MOSI), through the kernel's own spidev
    driver (needs `dtparam=spi=on`, which install.sh adds when this pin is
    chosen) instead of /dev/mem. One whole SPI byte stands for one NeoPixel
    bit (0xF8/0xC0 at ~6.4 MHz, close enough to WS2812 timing), the
    technique older versions of this add-on always used on this pin - see
    `git show 479cb3b:netswitch_led.py`. No DMA: the kernel driver blocks
    until the whole buffer is sent, which is plenty fast at 50 fps even for
    a long strip."""

    def __init__(self, count, bus=0, device=0):
        self.count, self.order = count, DEFAULT_ORDER
        self.fd = os.open("/dev/spidev%d.%d" % (bus, device), os.O_RDWR)
        fcntl.ioctl(self.fd, SPI_IOC_WR_MODE, struct.pack("B", 0))
        fcntl.ioctl(self.fd, SPI_IOC_WR_MAX_SPEED_HZ, struct.pack("I", SPI_HZ))

    def show(self, pixels):
        a, b, c = self.order
        out = b"".join(_SPI_TABLE[px[a]] + _SPI_TABLE[px[b]] + _SPI_TABLE[px[c]] for px in pixels)
        os.write(self.fd, out + bytes(SPI_RESET_BYTES))

    def close(self):
        os.close(self.fd)


def open_output(count, gpio=DEFAULT_GPIO):
    if gpio not in GPIO_PINS:
        gpio = DEFAULT_GPIO
    if gpio == 10:
        return SpiStrip(count)
    base = peripheral_base()
    osc_hz = 54000000 if base == 0xFE000000 else 19200000   # Pi 4 crystal
    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    try:
        if gpio in _PWM_ALT:
            if count <= 1:
                return FifoPixel(Block(fd, base + GPIO_OFFSET), Block(fd, base + CLOCK_OFFSET),
                                 Block(fd, base + PWM_OFFSET), osc_hz, pin=gpio)
            return DmaStrip(fd, base, count, osc_hz, pin=gpio)
        return PcmStrip(fd, base, count, osc_hz)   # gpio == 21
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


_dither_err = {}   # (led index, channel) -> carried-over rounding error


# ------------------------------------------------------------- calibration
# The swatch grid (web.CALIB_COLUMNS x web.CALIB_ROWS) gives, for each cell
# that's been calibrated, the difference between its reference swatch and
# the colour the page found the LED actually needs to look like it. To
# correct an arbitrary colour: split it into hue/lightness/saturation,
# interpolate that cell's offset circularly across the 8 hue columns at the
# matching lightness, do the same for "white" (which only has a lightness
# axis), and blend the two by saturation - a fully saturated colour uses
# the hue-interpolated offset, a grey one uses white's, anything between
# blends smoothly instead of jumping at some saturation cutoff.
def calib_table(cfg):
    """{(column, row): (dr, dg, db)} in -255..255, 0 for an uncalibrated
    (or never-loaded) cell. Built once per config read, not per pixel."""
    raw = (cfg or {}).get("calibrate") or {}
    table = {}
    for col in web.CALIB_COLUMNS:
        for row in web.CALIB_ROWS:
            hexval = (raw.get(col) or {}).get(row)
            if not hexval:
                table[(col, row)] = (0.0, 0.0, 0.0)
                continue
            cr, cg, cb = hex_rgb(hexval)
            rr, rg, rb = hex_rgb(web.calib_swatch(col, row))
            table[(col, row)] = ((cr - rr) * 255.0, (cg - rg) * 255.0, (cb - rb) * 255.0)
    return table


def _lerp3(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def _row_interp(table, col, lightness):
    """A column's offset at a lightness, interpolated across (or clamped
    to) the light/medium/dark rows."""
    lt = web.CALIB_LIGHTNESS
    if lightness >= lt["light"]:
        return table[(col, "light")]
    if lightness <= lt["dark"]:
        return table[(col, "dark")]
    if lightness >= lt["medium"]:
        lo, hi = "medium", "light"
    else:
        lo, hi = "dark", "medium"
    t = (lightness - lt[lo]) / (lt[hi] - lt[lo])
    return _lerp3(table[(col, lo)], table[(col, hi)], t)


def _hue_interp(table, hue_deg, lightness):
    """The chromatic offset at a hue (0..360) and lightness, interpolated
    circularly across the 8 hue columns (their spacing isn't even)."""
    pts = web.CALIB_HUES   # already ascending by degree
    n = len(pts)
    for i in range(n):
        name0, deg0 = pts[i]
        name1, deg1 = pts[(i + 1) % n]
        span = (deg1 - deg0) % 360 or 360
        pos = (hue_deg - deg0) % 360
        if pos <= span:
            t = pos / span
            return _lerp3(_row_interp(table, name0, lightness), _row_interp(table, name1, lightness), t)
    return _row_interp(table, pts[0][0], lightness)   # unreachable


def calib_offset(table, r, g, b):
    """(dr, dg, db) to add to (r, g, b) (0..255 each)."""
    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    white = _row_interp(table, "white", l)
    if s <= 0.0:
        return white
    return _lerp3(white, _hue_interp(table, h * 360.0, l), s)


def to_bytes(frame, brightness, calib=None, dither=True, start=0):
    """Floats 0..1 -> 0..255 with brightness and the calibration offset
    table (from calib_table(), or None for no correction). A channel that
    is on never rounds down to 0, so colours stay recognisable at low
    brightness. With dither, the rounding error is carried over to the
    next frame instead of discarded, so a value the 8-bit output can't
    represent exactly (typical at low brightness, where slow effects like
    breathe would otherwise visibly step) is approximated by alternating
    the neighbouring levels over time instead. start is the absolute LED
    index of frame[0], so a section keeps its own dither state even though
    render() quantizes one message's section at a time."""
    out = []
    for i, (r, g, b) in enumerate(frame):
        idx = start + i
        raw = (r * 255 * brightness, g * 255 * brightness, b * 255 * brightness)
        if calib:
            raw = tuple(raw[c] + d for c, d in enumerate(calib_offset(calib, *raw)))
        px = []
        for c, x in enumerate(raw):
            x = max(0.0, min(255.0, x))
            if x <= 0:
                px.append(0)
                if dither:
                    _dither_err.pop((idx, c), None)
                continue
            if dither:
                key = (idx, c)
                x += _dither_err.get(key, 0.0)
                q = max(1, min(255, int(round(x))))
                _dither_err[key] = x - q
            else:
                q = max(1, min(255, int(round(x))))
            px.append(q)
        out.append(tuple(px))
    return out


def reset_dither():
    """Forget carried-over error, e.g. when the LED count changes."""
    _dither_err.clear()


def scaled(colour, brightness, calib=None):
    """'#rrggbb' at a brightness, for a single solid pixel."""
    return to_bytes([hex_rgb(colour)], brightness, calib, dither=False)[0]


# ---------------------------------------------------------------- composing
def render(messages, now, count, clocks=None, calib=None):
    """Draw the active messages (lowest priority first) into one frame.
    Each message covers all LEDs or its own section; later (more important)
    messages draw over earlier ones, and uncovered LEDs stay dark.
    Every message's effect restarts from its beginning (blink on, breathe
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
                        m.get("brightness", 0.08), calib, start=first - 1)
        frame[first - 1:last] = part
    for key in list(clocks):
        if key not in seen:
            del clocks[key]   # starts over next time the message appears
    return frame


# ---------------------------------------------------------------- main loop
def main():
    count, gpio = web.led_count() or 1, web.led_gpio()
    cfg = web.led_config()
    order, calib = ORDERS.get(cfg.get("order"), DEFAULT_ORDER), calib_table(cfg)
    try:
        out = open_output(count, gpio)
    except (IOError, OSError) as e:
        sys.exit("Cannot drive the LEDs on GPIO%d (%s). The LED service must run as root "
                 "(and, for GPIO10, SPI must be enabled)." % (gpio, e))
    out.order = order

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
    preview = None
    clocks = {}
    last_frame, last_sent = None, 0.0
    next_read = 0.0
    while True:
        now = time.time()
        if now >= next_read:
            try:
                preview = web.calib_preview()
                messages = web.active_messages()
                cfg = web.led_config()
                order, calib = ORDERS.get(cfg.get("order"), DEFAULT_ORDER), calib_table(cfg)
                new_count, new_gpio = web.led_count() or 1, web.led_gpio()
                if new_count != count or new_gpio != gpio:   # changed on the page: reopen the output
                    try:
                        new_out = open_output(new_count, new_gpio)
                    except (IOError, OSError) as e:
                        sys.stderr.write("could not switch to GPIO%d, %d LED(s) (%s), keeping the "
                                         "current output\n" % (new_gpio, new_count, e))
                    else:
                        out.show([(0, 0, 0)] * count)
                        time.sleep(0.02)
                        out.close()
                        out, count, gpio = new_out, new_count, new_gpio
                        clocks = {}
                        reset_dither()
                out.order = order
            except Exception:   # never let a bad read stop the LED loop
                pass
            next_read = now + REFRESH
        # Colour calibration popup open on the page: show its raw sliders
        # directly (no effects, no calibration correction - that's what's
        # being figured out) so the LED can be compared to the swatch.
        frame = [preview] * count if preview else render(messages, now, count, clocks, calib)
        # Unchanged frames (solid colours) are only resent twice a second,
        # which fixes any garbled frame and keeps the CPU free for DreamPi.
        if frame != last_frame or now - last_sent >= 0.5:
            out.show(frame)
            last_frame, last_sent = frame, now
        time.sleep(max(0.0, 1.0 / FPS - (time.time() - now)))


if __name__ == "__main__":
    main()
