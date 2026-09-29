# -*- coding: utf-8 -*-
# DreamPi Netswitch add-on - shared low-level GPIO register access.
#
# Used by netswitch_led.py (NeoPixel output on GPIO18) and netswitch_wifi.py
# (the Wi-Fi setup button input). Registers are mapped straight from
# /dev/mem, 32-bit accesses only, so no driver or Python package is needed;
# each caller opens its own mapping since these run in separate processes.
# Python 3 only (both services run under python3).
import ctypes
import mmap
import time

GPIO_OFFSET = 0x200000

GPFSEL0 = 0x00                 # GPIO 0-9 function select; GPFSELn is 4 bytes apart
GPLEV0, GPLEV1 = 0x34, 0x38    # pin level, 0-31 / 32-53
GPPUD, GPPUDCLK0, GPPUDCLK1 = 0x94, 0x98, 0x9C            # BCM2835/6/7 pull config
GPIO_PUP_PDN_CNTRL_REG0 = 0xE4                             # BCM2711 (Pi 4) pull config

PULL_NONE, PULL_UP, PULL_DOWN = 0, 1, 2


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


def is_pi4(base):
    return base == 0xFE000000


class Block(object):
    """A register block mapped from /dev/mem, 32-bit accesses only."""

    def __init__(self, fd, address, size=4096):
        self.mem = mmap.mmap(fd, size, mmap.MAP_SHARED,
                             mmap.PROT_READ | mmap.PROT_WRITE, offset=address)

    def __getitem__(self, offset):
        return ctypes.c_uint32.from_buffer(self.mem, offset).value

    def __setitem__(self, offset, value):
        ctypes.c_uint32.from_buffer(self.mem, offset).value = value & 0xFFFFFFFF


# ------------------------------------------------------------------- input
# Only what the Wi-Fi setup button needs: one pin, as input with an internal
# pull-up (idle high; the button pulls it to GND when pressed).

def set_input_pullup(gpio, pin, base):
    """Configure a GPIO pin as input with its internal pull-up enabled."""
    reg = GPFSEL0 + (pin // 10) * 4
    shift = (pin % 10) * 3
    gpio[reg] = gpio[reg] & ~(7 << shift)   # 000 = input
    if is_pi4(base):
        reg = GPIO_PUP_PDN_CNTRL_REG0 + (pin // 16) * 4
        shift = (pin % 16) * 2
        gpio[reg] = (gpio[reg] & ~(3 << shift)) | (PULL_UP << shift)
    else:
        # Classic BCM2835/6/7 sequence: set GPPUD, clock it into the pin,
        # then clear both (see the BCM2835 ARM Peripherals datasheet).
        clk_reg = GPPUDCLK0 if pin < 32 else GPPUDCLK1
        bit = 1 << (pin % 32)
        gpio[GPPUD] = PULL_UP
        time.sleep(0.00001)
        gpio[clk_reg] = bit
        time.sleep(0.00001)
        gpio[GPPUD] = 0
        gpio[clk_reg] = 0


def read_level(gpio, pin):
    """True (high) / False (low) level currently on a GPIO pin."""
    reg = GPLEV0 if pin < 32 else GPLEV1
    return bool(gpio[reg] & (1 << (pin % 32)))
