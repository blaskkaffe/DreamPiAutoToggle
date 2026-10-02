#!/usr/bin/env python3
# DreamPi Netswitch add-on - LED module: turns the Pi's SPI on for GPIO10 and off again.
#
# GPIO10 drives the LEDs through the kernel's SPI driver, which only exists when config.txt has dtparam=spi=on. The LED
# service calls ensure_spi() whenever the output pin is GPIO10 (at start and when the pin is changed on the page), and
# ensure_spi(False) when it leaves GPIO10. A line is only ever taken out again if this add-on put it there (core.SPI_ADDED
# remembers which config.txt); an SPI setting you made yourself is left alone. install.sh runs "netswitch_led_spi.py sync".
# After editing config.txt it also asks the running system to switch SPI on right away (dtparam), which works on current
# Raspberry Pi OS; if the device still doesn't show up, the change applies after the next reboot.
import os
import re
import shutil
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))          # the add-on's base files (netswitch_core)
import netswitch_core as core  # noqa: E402

CONFIG_CANDIDATES = ["/boot/firmware/config.txt", "/boot/config.txt"]
MARKER = "dtparam=spi=on  # added by dreampi-netswitch"
SPI_DEVICE = "/dev/spidev0.0"
_ON = re.compile(r"^\s*dtparam=spi=on\b", re.M)


def config_path():
    for path in CONFIG_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def _run(*cmd):
    """Best effort: a missing tool or a failing command is not an error here."""
    if not shutil.which(cmd[0]):
        return False
    try:
        return subprocess.call(list(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE) == 0
    except OSError:
        return False


def ensure_spi(on=True):
    """Make config.txt (and, if possible, the running system) match: SPI on while GPIO10 is the LED pin. Returns a
    short text about what was done, or "" when nothing needed doing."""
    if on:
        path = config_path()
        if path is None:
            return "config.txt not found: add dtparam=spi=on to it yourself and reboot"
        with open(path) as f:
            text = f.read()
        said = ""
        if not _ON.search(text):
            with open(path, "a") as f:
                f.write(("" if text.endswith("\n") or not text else "\n") + MARKER + "\n")
            with open(core.SPI_ADDED, "w") as f:
                f.write(path + "\n")
            said = "SPI switched on in %s for GPIO10" % path
        if not os.path.exists(SPI_DEVICE):
            _run("dtparam", "spi=on")
            _run("modprobe", "spidev")
            if not os.path.exists(SPI_DEVICE) and said:
                said += "; it applies after a reboot"
        return said
    path = (core.read_file(core.SPI_ADDED) or "").strip()
    if not path:
        return ""
    try:
        with open(path) as f:
            lines = f.read().split("\n")
        with open(path, "w") as f:
            f.write("\n".join(l for l in lines if l.strip() != MARKER))
    except (IOError, OSError):
        pass
    try:
        os.remove(core.SPI_ADDED)
    except OSError:
        pass
    _run("dtparam", "spi=off")
    return "SPI setting added for GPIO10 taken out of %s" % path


def sync():
    """Match config.txt to the pin that is set now (what install.sh calls)."""
    sys.path.insert(0, _HERE)
    import netswitch_ledconfig as ledconfig
    return ensure_spi(ledconfig.led_gpio() == 10)


if __name__ == "__main__":
    if sys.argv[1:] == ["sync"]:
        text = sync()
        if text:
            print(text)
    else:
        sys.exit("usage: netswitch_led_spi.py sync")
