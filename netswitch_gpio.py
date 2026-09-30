# -*- coding: utf-8 -*-
# DreamPi Netswitch add-on - low-level GPIO/peripheral register access.
#
# Used by netswitch_led.py (NeoPixel output on GPIO18). Registers are mapped
# straight from /dev/mem, 32-bit accesses only, so no driver or Python
# package is needed. Python 3 only.
import ctypes
import mmap


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
