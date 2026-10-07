# DreamPi Netswitch add-on - network switcher module: the files it owns and how to read them. DreamPi's hook (netswitch_dreampi.py)
# writes the state files, the checker (netswitch_switcher_probes.py) writes NET_STATE, the page and the buttons write the selection and the
# button settings. Other modules read these files themselves (docs/hook.md, docs/web.md); nothing outside this module imports this file.
# Works on Python 3 and 2.7.
import json
import os
import re
import time

import base_core as core

BASE_DIR, TMP = core.BASE_DIR, core.TMP_PREFIX
FLAG = os.path.join(BASE_DIR, "dcnet_mode")                  # exists = DCNET is selected (removed on every reboot: DCNow! again)
BOOT_ID = os.path.join(BASE_DIR, "boot_id")                  # the kernel's id of the boot the selection was last reset for
KERNEL_BOOT_ID = "/proc/sys/kernel/random/boot_id"
STATUS = TMP + ".active"                                     # "active pid=N" while DreamPi runs the hook, or why it does not (the hook writes it)
STATE = TMP + ".state"                                       # "<starting|ready|call dcnow|call dcnet> <unix time>" (the hook)
MODEM = TMP + ".modem"                                       # "<unix time> <text>": the latest modem event DreamPi logged (the hook)
NET_STATE = TMP + ".net"                                     # the checker's JSON: links, internet, Pi health, modem (read by the LED module)
NET_STALE = 20                                               # ignore NET_STATE when older than this (the web service is down)
BUTTON1_GPIO = os.path.join(BASE_DIR, "button1_gpio")
BUTTON2_GPIO = os.path.join(BASE_DIR, "button2_gpio")
BUTTON1_FUNCTION = os.path.join(BASE_DIR, "button1_function")
BUTTON2_FUNCTION = os.path.join(BASE_DIR, "button2_function")


def reset_network_after_boot():
    """DCNow! is the selected network after every reboot: the first service that starts in a boot (web page or
    buttons) removes dcnet_mode; later calls in the same boot, and restarts of a service, leave the selection alone (so does
    the first run after an install).
    Uses the kernel's boot id, not the clock, because a Pi without a clock has a wrong time at boot."""
    try:
        with open(KERNEL_BOOT_ID) as f:
            now = f.read().strip()
    except (IOError, OSError):
        return False
    before = core.read_file(BOOT_ID)
    if not now or before == now:
        return False
    try:
        if before is not None and os.path.exists(FLAG):     # no record yet = the add-on was just installed: keep the selection
            os.remove(FLAG)
        with open(BOOT_ID, "w") as f:
            f.write(now + "\n")
    except OSError:
        return False
    if before is not None:
        core.debug_log("new boot: DCNow! selected")
    return before is not None


def hook_problem():
    """None when DreamPi is running with the hook loaded, else a reason."""
    status = core.read_file(STATUS)
    if status is None:
        return "DreamPi has not loaded the add-on yet (restart DreamPi or reboot)"
    if not status.startswith("active"):
        return status
    m = re.search(r"pid=(\d+)", status)
    if m and not os.path.exists("/proc/" + m.group(1)):
        return "DreamPi is not running"
    return None


def _dcnet_check():
    """(code, reason): (None, None) when DreamPi's DCNET support is switched on, else why not: code "noupdates" (/boot/noautoupdates.txt
    exists), "config" (netlink_config.ini is not found) or "disabled" ([DCNet] enabled = yes is missing)."""
    if os.path.exists("/boot/noautoupdates.txt"):
        return "noupdates", ("/boot/noautoupdates.txt exists, so DreamPi skips netlink_config.ini "
                             "and DCNET stays off")
    for path in ("/boot/netlink_config.ini", "/home/pi/dreampi/netlink_config.ini"):
        if os.path.isfile(path):
            break
    else:
        return "config", "netlink_config.ini not found, so DCNET is off"
    text = core.read_file(path) or ""
    section = re.search(r"^\[DCNet\](.*?)(?=^\[|\Z)", text, re.M | re.S)
    if not section or not re.search(r"^\s*enabled\s*=\s*yes\s*$", section.group(1), re.M):
        return "disabled", "DCNET is not enabled in " + path + " ([DCNet] enabled = yes)"
    return None, None


def dcnet_problem():
    """None when DreamPi's DCNET support is switched on, else a reason."""
    return _dcnet_check()[1]


def dcnet_code():
    """"ok" when DreamPi's DCNET support is switched on, else a short code for why not (see _dcnet_check()), "inactive" when DreamPi is
    not running the add-on (nothing is being switched then). openMenu gets it in the DCNET line of the poll (through NET_STATE)."""
    if hook_problem():
        return "inactive"
    return _dcnet_check()[0] or "ok"


# The short tag served at GET /tag for openMenu (docs/openmenu.md): which network this
# DreamPi is running. openMenu keeps its own list of what each code means; the texts
# here are only a suggestion and what /tag?text returns.
TAGS = (("DCNET", "Running DCNet!"), ("DCNOW", "Running DCNow!"),
        ("DCNET_OFF", "DCNet is selected but not available"), ("INACTIVE", ""))


def tag():
    """One of the codes in TAGS for the current state of this DreamPi."""
    if hook_problem():
        return "INACTIVE"          # DreamPi isn't running the add-on: nothing is being switched
    if os.path.exists(FLAG):
        return "DCNET_OFF" if dcnet_problem() else "DCNET"
    return "DCNOW"


def dreampi_state():
    """(state, text) for what DreamPi is doing right now."""
    if hook_problem() == "DreamPi is not running":
        return "off", "Not running"
    parts = (core.read_file(STATE) or "").split()
    if len(parts) < 2:
        return "unknown", "State unknown"
    state = " ".join(parts[:-1])
    if state == "starting":
        return "busy", "Starting up, not answering calls yet"
    if state == "ready":
        return "ok", "Ready for calls"
    if state.startswith("call "):
        kind = state[5:]
        net = {"dcnow": "DCNow!", "dcnet": "DCNET"}.get(kind, kind)
        return ("call-" + kind if kind in ("dcnow", "dcnet") else "call"), "In a call: " + net
    return "unknown", "State unknown"


def modem_state():
    """(text, unix time) of the latest modem event DreamPi logged."""
    if hook_problem() == "DreamPi is not running":
        return "DreamPi not running", 0
    raw = core.read_file(MODEM)
    if not raw or " " not in raw:
        return "Unknown", 0
    since, text = raw.split(" ", 1)
    try:
        return text, int(since)
    except ValueError:
        return text, 0


def network_state():
    """Latest link + internet state written by the checker, or None."""
    try:
        with open(NET_STATE) as f:
            data = json.load(f)
        if time.time() - data.get("time", 0) > NET_STALE:
            return None
        return data
    except (IOError, OSError, ValueError):
        return None


def write_net_state(data):
    tmp = NET_STATE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.rename(tmp, NET_STATE)
    except (IOError, OSError):
        pass


# ------------------------------------------------------------------ buttons
# Up to two physical GPIO buttons (netswitch_switcher_buttons.py), each independently wired to a pin and a short-press function; which
# one (or both held together) triggers Wi-Fi setup on a 3-second hold is the Wi-Fi module's setting. Unlike the LED output pins, a
# button needs no special peripheral, so any header GPIO is allowed.
BUTTON_GPIO_PINS = tuple(range(2, 28))   # BCM GPIO2-27 (0/1 are reserved for the ID EEPROM)
BUTTON_DEFAULT_GPIO1 = 17
BUTTON_DEFAULT_GPIO2 = 4
# What a button does. Push buttons act on a short press. A toggle switch is wired
# between the pin and GND and acts on its position: closed (pin low) = "on",
# open = "off"; the position is also applied once at start.
# (name, label, group, needs Wi-Fi setup installed, the line under the button's row on the page; "{pin}" becomes "GPIO17" for its pin)
BUTTON_FUNCTIONS = (
    ("off", "Off", "Push button", False, "{pin} is not used"),
    ("toggle", "Toggle network", "Push button", False, "{pin} toggles DCNow! and DCNET"),
    ("dcnow", "Select DCNow!", "Push button", False, "{pin} selects DCNow!"),
    ("dcnet", "Select DCNET", "Push button", False, "{pin} selects DCNET"),
    ("sw_dcnet", "On = DCNET", "Toggle switch", False, "{pin} closed: DCNET, open: DCNow!"),
    ("sw_dcnow", "On = DCNow!", "Toggle switch", False, "{pin} closed: DCNow!, open: DCNET"),
    ("sw_wifi", "On = Wi-Fi setup", "Toggle switch", True, "{pin} closed: Wi-Fi setup, open: normal mode"),
    ("sw_wifi_off", "Off = Wi-Fi setup", "Toggle switch", True, "{pin} open: Wi-Fi setup, closed: normal mode"),
)
_BUTTON_FUNCTION_NAMES = tuple(f[0] for f in BUTTON_FUNCTIONS)
BUTTON_DEFAULT_FUNCTION1 = "toggle"
BUTTON_DEFAULT_FUNCTION2 = "off"


def button_gpio(which):
    """which: 1 or 2."""
    path = BUTTON1_GPIO if which == 1 else BUTTON2_GPIO
    default = BUTTON_DEFAULT_GPIO1 if which == 1 else BUTTON_DEFAULT_GPIO2
    try:
        n = int((core.read_file(path) or "").strip())
        return n if n in BUTTON_GPIO_PINS else default
    except ValueError:
        return default


def save_button_gpio(which, n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return
    if n not in BUTTON_GPIO_PINS:
        return
    path = BUTTON1_GPIO if which == 1 else BUTTON2_GPIO
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(str(n))
    os.rename(tmp, path)


def button_function(which):
    path = BUTTON1_FUNCTION if which == 1 else BUTTON2_FUNCTION
    default = BUTTON_DEFAULT_FUNCTION1 if which == 1 else BUTTON_DEFAULT_FUNCTION2
    v = (core.read_file(path) or "").strip()
    return v if v in _BUTTON_FUNCTION_NAMES else default


def save_button_function(which, v):
    if v not in _BUTTON_FUNCTION_NAMES:
        return
    path = BUTTON1_FUNCTION if which == 1 else BUTTON2_FUNCTION
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(v)
    os.rename(tmp, path)
