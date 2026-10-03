# DreamPi Netswitch add-on - shared state and settings.
# Everything the web page, the LED service and the buttons service all read or
# write: file paths, the DreamPi/modem/network/Wi-Fi state files, the debug log,
# button settings and the paths of everything else. No server, no probing, so the
# small services can import it cheaply. Works on Python 3 and 2.7.
import json
import os
import re
import time

BASE_DIR = "/opt/dreampi-netswitch"
FLAG = os.path.join(BASE_DIR, "dcnet_mode")
NET_COLOURS = os.path.join(BASE_DIR, "network_colours.json")   # which colour DCNow! and DCNET have, everywhere (page and LEDs)
BOOT_ID = os.path.join(BASE_DIR, "boot_id")              # the kernel's id of the boot the selection was last reset for
KERNEL_BOOT_ID = "/proc/sys/kernel/random/boot_id"
DEBUG_DTMF = os.path.join(BASE_DIR, "debug_dtmf")
ADDON_COMMIT = os.path.join(BASE_DIR, "version_commit")  # full commit hash of the checkout that was installed (install.sh)
ADDON_SRC = os.path.join(BASE_DIR, "src_dir")            # that checkout's folder, used by the web update
INSTALL_PORTS = os.path.join(BASE_DIR, "install_ports")  # "<http port> <https port>", so an update keeps them
UPDATE_ORIGIN = os.path.join(BASE_DIR, "update_origin")  # the checkout's git origin URL when installed; "Update now" refuses another one
ADMIN_PIN = os.path.join(BASE_DIR, "admin_pin")          # salted hash of the optional PIN for update/restart/Wi-Fi (install.sh --pin)
ALLOWED_HOSTS = os.path.join(BASE_DIR, "allowed_hosts")  # extra host names the web page answers to, one per line
UPDATE_STATUS = "/tmp/dreampi-netswitch.update"          # running / ok / failed, written by the update script
UPDATE_LOG = "/tmp/dreampi-netswitch.update.log"
PLAYERS_SOURCES = os.path.join(BASE_DIR, "players_sources.json")   # JSON addresses for the optional online-players list
NUMBERS = os.path.join(BASE_DIR, "numbers.json")     # phone numbers per action, edited on the page, read by the hook
LED_CONFIG = os.path.join(BASE_DIR, "led.json")     # brightness, colours, wire order, white balance
LED_COUNT = os.path.join(BASE_DIR, "led_count")      # number of LEDs, editable from the page
LED_GPIO = os.path.join(BASE_DIR, "led_gpio")        # output pin (10, 12, 18 or 21), likewise
SPI_ADDED = os.path.join(BASE_DIR, "spi_added")      # the config.txt this add-on put dtparam=spi=on into (so it can take it out again)
STATUS = "/tmp/dreampi-netswitch.active"
STATE = "/tmp/dreampi-netswitch.state"
MODEM = "/tmp/dreampi-netswitch.modem"
DTMF_LOG = "/tmp/dreampi-netswitch-dtmf.log"
# Wi-Fi setup (netswitch_buttons.py, install.sh --wifi); the buttons themselves are always installed
WIFI_DEMO = os.path.join(BASE_DIR, "wifi_demo")        # exists = Wi-Fi setup runs on dummy networks (install.sh --wifi-demo)
WIFI_START = os.path.join(BASE_DIR, "wifi_start")   # touched to ask netswitch_buttons.py to start
WIFI_STOP = os.path.join(BASE_DIR, "wifi_stop")     # touched to ask it to stop / cancel
WIFI_CONNECT = os.path.join(BASE_DIR, "wifi_connect")   # {"ssid":..., "password":...}, an alternative
                                                         # to the setup access point's own /connect -
                                                         # lets the regular page pick a network too,
                                                         # useful when it's reachable some other way
                                                         # (e.g. Ethernet) while Wi-Fi is being set up
WIFI_STATE = "/tmp/dreampi-netswitch.wifi"          # written by netswitch_buttons.py
WIFI_STALE = 30       # ignore WIFI_STATE when older than this (the service is down)
WIFI_AP_SSID = "DreamPi WiFi Config"
NET_STATE = "/tmp/dreampi-netswitch.net"   # shared with the LED service
NET_STALE = 20        # ignore NET_STATE when older than this (web service down)


# ------------------------------------------------------------------ modules
# The optional features (LED, Wi-Fi setup, phone numbers, online players, debug log) are folders in
# modules/, each with a module.json. A module is *installed* when its folder is there and *enabled*
# when the Modules menu has it on (modules.json; a module without an entry uses the "default" in its
# manifest). Everything that has to know - the web page, the LED service, the buttons service - asks here.
MODULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules")
MODULES_STATE = os.path.join(BASE_DIR, "modules.json")     # {"led": true, "wifi": false, ...} set from the Modules menu


def module_manifest(name):
    """The module's module.json as a dict, or None when it isn't installed."""
    if not re.match(r"^[a-z][a-z0-9_]*$", name or ""):
        return None
    try:
        with open(os.path.join(MODULES_DIR, name, "module.json")) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (IOError, OSError, ValueError):
        return None


def module_names():
    """Names of the installed modules (folders with a readable module.json), in menu order."""
    try:
        names = [n for n in os.listdir(MODULES_DIR) if module_manifest(n)]
    except OSError:
        return []
    return sorted(names, key=lambda n: (module_manifest(n).get("order", 100), n))


def modules_state():
    try:
        with open(MODULES_STATE) as f:
            data = json.load(f)
        return dict((k, v) for k, v in data.items() if isinstance(v, bool)) if isinstance(data, dict) else {}
    except (IOError, OSError, ValueError):
        return {}


def module_enabled(name, state=None):
    """Installed and switched on. state: modules_state() already read (saves a file read per module)."""
    manifest = module_manifest(name)
    if manifest is None:
        return False
    state = modules_state() if state is None else state
    return state.get(name, bool(manifest.get("default", True)))


def save_module_enabled(name, on):
    """Switch a module on or off from the Modules menu. False when it isn't installed."""
    if module_manifest(name) is None:
        return False
    state = modules_state()
    state[name] = bool(on)
    tmp = MODULES_STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    os.rename(tmp, MODULES_STATE)
    return True


def wifi_enabled():
    """Wi-Fi setup module installed and on (the buttons and the Wi-Fi service ask)."""
    return module_enabled("wifi")


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
    before = read_file(BOOT_ID)
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
        debug_log("new boot: DCNow! selected")
    return before is not None


# ---------------------------------------------------------------- network colours
# DCNow! and DCNET each have one colour, used everywhere: the page (buttons, boxes, the players counts) and the status LEDs.
# The user picks it from this list in Settings. id, name, page colour, its lighter variant (borders, text), LED colour (the
# LED's own tuning: a screen colour looks different lit on a NeoPixel).
NETWORK_COLOURS = (
    ("orange", "Orange", "#e8761c", "#f6b27a", "#ff8c00"),
    ("blue", "Blue", "#1c6fe8", "#80b1f6", "#0046ff"),
    ("red", "Red", "#d9363e", "#ef8a8f", "#ff0000"),
    ("green", "Green", "#2fa84f", "#8ed9a4", "#00ff00"),
)
DEFAULT_NETWORK_COLOURS = {"dcnow": "orange", "dcnet": "blue"}
_NETWORK_COLOUR_IDS = tuple(c[0] for c in NETWORK_COLOURS)


def network_colours():
    """{"dcnow": id, "dcnet": id}: the two colour ids in use (always different, always from NETWORK_COLOURS)."""
    out = dict(DEFAULT_NETWORK_COLOURS)
    try:
        with open(NET_COLOURS) as f:
            data = json.load(f)
        for net in out:
            if data.get(net) in _NETWORK_COLOUR_IDS:
                out[net] = str(data[net])
    except (IOError, OSError, ValueError, AttributeError):
        pass
    if out["dcnow"] == out["dcnet"]:
        out = dict(DEFAULT_NETWORK_COLOURS)
    return out


def network_colour(net):
    """The palette entry (dict: id, name, ui, ui_l, led) for "dcnow" or "dcnet"."""
    ident = network_colours().get(net, DEFAULT_NETWORK_COLOURS.get(net, "orange"))
    for c in NETWORK_COLOURS:
        if c[0] == ident:
            return {"id": c[0], "name": c[1], "ui": c[2], "ui_l": c[3], "led": c[4]}
    return {"id": "orange", "name": "Orange", "ui": "#e8761c", "ui_l": "#f6b27a", "led": "#ff8c00"}


def set_network_colour(net, ident):
    """Give DCNow! or DCNET a colour. If the other network has it, the two swap, so they never share one.
    Returns the new {"dcnow": id, "dcnet": id}."""
    cur = network_colours()
    if net not in cur or ident not in _NETWORK_COLOUR_IDS:
        return cur
    other = "dcnet" if net == "dcnow" else "dcnow"
    if cur[other] == ident:
        cur[other] = cur[net]
    cur[net] = ident
    tmp = NET_COLOURS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cur, f)
    os.rename(tmp, NET_COLOURS)
    return cur


def network_colours_css():
    """:root rules that give the page's network colour variables the chosen colours (the page's own :root has the defaults)."""
    def rgb(h):
        return "%d,%d,%d" % (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))
    out = ":root{"
    for net in ("dcnow", "dcnet"):
        c = network_colour(net)
        out += "--%s:%s;--%s-l:%s;--%s-rgb:%s;--%s-l-rgb:%s;" % (net, c["ui"], net, c["ui_l"], net, rgb(c["ui"]), net, rgb(c["ui_l"]))
    return out + "}"


# ---------------------------------------------------------------- file state

def read_file(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except IOError:
        return None


def hook_problem():
    """None when DreamPi is running with the hook loaded, else a reason."""
    status = read_file(STATUS)
    if status is None:
        return "DreamPi has not loaded the add-on yet (restart DreamPi or reboot)"
    if not status.startswith("active"):
        return status
    m = re.search(r"pid=(\d+)", status)
    if m and not os.path.exists("/proc/" + m.group(1)):
        return "DreamPi is not running"
    return None


def dcnet_problem():
    """None when DreamPi's DCNET support is switched on, else a reason."""
    if os.path.exists("/boot/noautoupdates.txt"):
        return ("/boot/noautoupdates.txt exists, so DreamPi skips netlink_config.ini "
                "and DCNET stays off")
    for path in ("/boot/netlink_config.ini", "/home/pi/dreampi/netlink_config.ini"):
        if os.path.isfile(path):
            break
    else:
        return "netlink_config.ini not found, so DCNET is off"
    text = read_file(path) or ""
    section = re.search(r"^\[DCNet\](.*?)(?=^\[|\Z)", text, re.M | re.S)
    if not section or not re.search(r"^\s*enabled\s*=\s*yes\s*$", section.group(1), re.M):
        return "DCNET is not enabled in " + path + " ([DCNet] enabled = yes)"
    return None


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
    parts = (read_file(STATE) or "").split()
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
    raw = read_file(MODEM)
    if not raw or " " not in raw:
        return "Unknown", 0
    since, text = raw.split(" ", 1)
    try:
        return text, int(since)
    except ValueError:
        return text, 0


def debug_log(text):
    """Add a line to the debug timeline (same format as the hook)."""
    if not os.path.exists(DEBUG_DTMF) or not module_enabled("debuglog"):
        return
    try:
        now = time.time()
        with open(DTMF_LOG, "a") as f:
            f.write("%s.%03d %9s  %s\n" % (time.strftime("%H:%M:%S", time.localtime(now)),
                                          int(now * 1000) % 1000, "", text))
    except IOError:
        pass


LOG_MAX = 1000000     # the debug log is trimmed to its newest LOG_KEEP bytes
LOG_KEEP = 500000     # when it grows past LOG_MAX


def trim_log():
    """Keep the debug log from growing without limit while recording.
    The hook opens the file for every line, so replacing it is safe."""
    try:
        if os.path.getsize(DTMF_LOG) <= LOG_MAX:
            return
        with open(DTMF_LOG, "rb") as f:
            f.seek(-LOG_KEEP, 2)
            data = f.read()
        data = data[data.find(b"\n") + 1:]      # start at a whole line
        tmp = DTMF_LOG + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.rename(tmp, DTMF_LOG)
    except (IOError, OSError):
        pass


def network_state():
    """Latest link + internet state written by the web service, or None."""
    try:
        with open(NET_STATE) as f:
            data = json.load(f)
        if time.time() - data.get("time", 0) > NET_STALE:
            return None
        return data
    except (IOError, OSError, ValueError):
        return None


def wifi_state():
    """Latest Wi-Fi setup state written by netswitch_buttons.py: state (idle /
    scanning / hosting / connecting / ok / failed), ssid, networks (scan
    results while hosting) and time. {"state": "idle"} when the service
    hasn't run yet, or hasn't updated the file in a while (it isn't
    running any more, or crashed mid-setup)."""
    try:
        with open(WIFI_STATE) as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        return {"state": "idle"}
    if data.get("state", "idle") != "idle" and time.time() - data.get("time", 0) > WIFI_STALE:
        return {"state": "idle"}
    return data


def _write_net_state(data):
    tmp = NET_STATE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.rename(tmp, NET_STATE)
    except (IOError, OSError):
        pass


# ------------------------------------------------------------------ buttons
# Up to two physical GPIO buttons (netswitch_buttons.py, always installed),
# each independently wired to a pin and a short-press function; which one
# (or both held together) triggers Wi-Fi setup on a 3-second hold is also
# configurable. Unlike the LED output pins, a button needs no special
# peripheral, so any header GPIO is allowed.
BUTTON1_GPIO = os.path.join(BASE_DIR, "button1_gpio")
BUTTON2_GPIO = os.path.join(BASE_DIR, "button2_gpio")
BUTTON1_FUNCTION = os.path.join(BASE_DIR, "button1_function")
BUTTON2_FUNCTION = os.path.join(BASE_DIR, "button2_function")
WIFI_BUTTON_FILE = os.path.join(BASE_DIR, "wifi_button")   # "1", "2" or "12": which button(s) hold-to-start Wi-Fi setup

BUTTON_GPIO_PINS = tuple(range(2, 28))   # BCM GPIO2-27 (0/1 are reserved for the ID EEPROM)
BUTTON_DEFAULT_GPIO1 = 17
BUTTON_DEFAULT_GPIO2 = 4
# What a button does. Push buttons act on a short press. A toggle switch is wired
# between the pin and GND and acts on its position: closed (pin low) = "on",
# open = "off"; the position is also applied once at start.
# (name, label, group, needs Wi-Fi setup installed, description shown on the page)
BUTTON_FUNCTIONS = (
    ("off", "Off", "Push button", False, "Not mapped to a function"),
    ("toggle", "Toggle network", "Push button", False, "Push button to switch DCNow! and DCNET"),
    ("dcnow", "Select DCNow!", "Push button", False, "Push button to select DCNow!"),
    ("dcnet", "Select DCNET", "Push button", False, "Push button to select DCNET"),
    ("sw_dcnet", "On = DCNET", "Toggle switch", False, "Toggle switch closed: DCNET, open: DCNow!"),
    ("sw_dcnow", "On = DCNow!", "Toggle switch", False, "Toggle switch closed: DCNow!, open: DCNET"),
    ("sw_wifi", "On = Wi-Fi setup", "Toggle switch", True, "Toggle switch closed: Wi-Fi setup, open: Normal mode"),
    ("sw_wifi_off", "Off = Wi-Fi setup", "Toggle switch", True, "Toggle switch open: Wi-Fi setup, closed: Normal mode"),
)
_BUTTON_FUNCTION_NAMES = tuple(f[0] for f in BUTTON_FUNCTIONS)
BUTTON_DEFAULT_FUNCTION1 = "toggle"
BUTTON_DEFAULT_FUNCTION2 = "off"
WIFI_BUTTON_CHOICES = (("1", "Button 1"), ("2", "Button 2"), ("12", "Button 1 + 2"))
_WIFI_BUTTON_NAMES = tuple(c[0] for c in WIFI_BUTTON_CHOICES)
WIFI_BUTTON_DEFAULT = "1"


def button_gpio(which):
    """which: 1 or 2."""
    path = BUTTON1_GPIO if which == 1 else BUTTON2_GPIO
    default = BUTTON_DEFAULT_GPIO1 if which == 1 else BUTTON_DEFAULT_GPIO2
    try:
        n = int((read_file(path) or "").strip())
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
    v = (read_file(path) or "").strip()
    return v if v in _BUTTON_FUNCTION_NAMES else default


def save_button_function(which, v):
    if v not in _BUTTON_FUNCTION_NAMES:
        return
    path = BUTTON1_FUNCTION if which == 1 else BUTTON2_FUNCTION
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(v)
    os.rename(tmp, path)


def wifi_button():
    v = (read_file(WIFI_BUTTON_FILE) or "").strip()
    return v if v in _WIFI_BUTTON_NAMES else WIFI_BUTTON_DEFAULT


def save_wifi_button(v):
    if v not in _WIFI_BUTTON_NAMES:
        return
    tmp = WIFI_BUTTON_FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write(v)
    os.rename(tmp, WIFI_BUTTON_FILE)


WB_TEST = "/tmp/dreampi-netswitch.wbtest"   # unix time, touched while the white-balance test is on
