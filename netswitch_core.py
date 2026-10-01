# DreamPi Netswitch add-on - shared state and settings.
# Everything the web page, the LED service and the buttons service all read or
# write: file paths, the DreamPi/modem/network/Wi-Fi state files, the debug log,
# LED + button settings and the LED message list. No server, no probing, so the
# small services can import it cheaply. Works on Python 3 and 2.7.
import json
import os
import re
import time

BASE_DIR = "/opt/dreampi-netswitch"
FLAG = os.path.join(BASE_DIR, "dcnet_mode")
AUTORESET = os.path.join(BASE_DIR, "autoreset")
DEFAULT_DCNET = os.path.join(BASE_DIR, "default_dcnet")
DEBUG_DTMF = os.path.join(BASE_DIR, "debug_dtmf")
LED_CONFIG = os.path.join(BASE_DIR, "led.json")     # brightness, colours, wire order, white balance
LED_ENABLED = os.path.join(BASE_DIR, "led_enabled")  # written by install.sh --led
LED_COUNT = os.path.join(BASE_DIR, "led_count")      # number of LEDs, editable from the page
LED_GPIO = os.path.join(BASE_DIR, "led_gpio")        # output pin (10, 12, 18 or 21), likewise
LED_HIDDEN = os.path.join(BASE_DIR, "led_hidden")    # exists = LED settings hidden on the page
STATUS = "/tmp/dreampi-netswitch.active"
STATE = "/tmp/dreampi-netswitch.state"
MODEM = "/tmp/dreampi-netswitch.modem"
DTMF_LOG = "/tmp/dreampi-netswitch-dtmf.log"
# Wi-Fi setup (netswitch_buttons.py, install.sh --wifi); the buttons themselves are always installed
WIFI_ENABLED = os.path.join(BASE_DIR, "wifi_enabled")  # written by install.sh --wifi
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
    if not os.path.exists(DEBUG_DTMF):
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
TEXT_TAIL = 256000    # "Open as text" shows this much unless ?all


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


def read_log(start):
    """New log text from byte offset start. If the log was cleared or
    restarted, everything is returned with reset=True."""
    try:
        with open(DTMF_LOG, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            reset = start > size or start < 0
            if reset:
                start = 0
            # Don't send megabytes to a page that just opened
            if size - start > 200000:
                start, reset = size - 200000, True
            f.seek(start)
            data = f.read()
    except IOError:
        return {"size": 0, "text": "", "reset": start != 0}
    return {"size": start + len(data), "text": data.decode("utf-8", "replace"), "reset": reset}


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


# -------------------------------------------------------------------- page

# DreamPi states (as returned by dreampi_state) in the order the settings show them
# LED messages, highest priority first, with category and default look.
# Errors always have higher priority than information. The DreamPi ones come from
# dreampi_state(); the network ones from the checker (NET_STATE).
LED_STATES = [
    # key, label, category, colour, effect, speed, enabled
    # Wi-Fi setup (netswitch_buttons.py) always outranks everything else: while
    # it's in progress "no network"/"no internet" are usually also true, and
    # would otherwise hide it. default_led_config() switches wifi-setup's
    # default effect to "scanner" when a strip is installed (breathe on a
    # single LED, see the user request); connecting keeps the same look.
    ("wifi-setup", "Wi-Fi setup: choose a network", "wifi", "#0046ff", "breathe", "slow", True),
    ("wifi-ok", "Wi-Fi setup: connected", "wifi", "#00ff00", "solid", "slow", True),
    ("wifi-failed", "Wi-Fi setup: couldn't connect", "wifi", "#ff0000", "blink", "slow", True),
    ("no-network", "No network", "error", "#ff0000", "solid", "slow", True),
    ("no-internet", "No internet", "error", "#ff7a00", "blink", "slow", True),
    ("pi", "Power or heat problem", "error", "#ff00aa", "breathe", "slow", True),
    ("off", "DreamPi not running", "error", "#ff0000", "blink", "slow", True),
    ("unknown", "State unknown", "error", "#3c3c3c", "solid", "slow", True),
    ("busy", "Starting up", "info", "#ffaa00", "blink", "slow", True),
    ("call-dcnow", "In a call on DCNow!", "info", "#ff5000", "solid", "slow", True),
    ("call-dcnet", "In a call on DCNET", "info", "#0046ff", "solid", "slow", True),
    ("call", "In another call (Netlink)", "info", "#aa00ff", "solid", "slow", True),
    ("ok", "Ready for calls", "info", "#00ff00", "solid", "slow", True),
    ("ethernet", "Ethernet connected", "info", "#ffffff", "solid", "slow", False),
    ("wifi", "Wi-Fi connected", "info", "#00c8ff", "solid", "slow", False),
]
PRIORITY = dict((s[0], len(LED_STATES) - i) for i, s in enumerate(LED_STATES))   # higher = more important
CATEGORY = dict((s[0], s[2]) for s in LED_STATES)
_DEFAULT_COLOURS = dict((s[0], s[3:7]) for s in LED_STATES)
# LED effects. The first four work on a single LED; the rest need a strip.
# "rgb" ignores the colour and cycles through all colours (20 s slow, 10 s fast).
EFFECTS = [
    ("solid", "Solid", False),
    ("blink", "Blink", False),
    ("breathe", "Breathe", False),
    ("rgb", "RGB", False),
    ("rainbow", "Rainbow", True),
    ("scanner", "Scanner", True),
    ("comet", "Comet", True),
    ("chase", "Chase", True),
    ("twinkle", "Twinkle", True),
]
EFFECT_NAMES = set(e[0] for e in EFFECTS)
SPEEDS = ("slow", "fast")


def led_count():
    """LEDs installed: 0 = no LED service, 1 = single LED, more = strip.
    Set at install time (install.sh --led=N) and editable from the page."""
    if not os.path.exists(LED_ENABLED):
        return 0
    try:
        return max(1, min(300, int((read_file(LED_COUNT) or "1").strip())))
    except ValueError:
        return 1


def save_led_count(n):
    try:
        n = max(1, min(300, int(n)))
    except (TypeError, ValueError):
        return
    tmp = LED_COUNT + ".tmp"
    with open(tmp, "w") as f:
        f.write(str(n))
    os.rename(tmp, LED_COUNT)


GPIO_PINS = (10, 12, 18, 21)   # allowed LED output pins; see netswitch_led.py for what each needs
DEFAULT_GPIO = 18


def led_gpio():
    try:
        n = int((read_file(LED_GPIO) or "").strip())
        return n if n in GPIO_PINS else DEFAULT_GPIO
    except ValueError:
        return DEFAULT_GPIO


def save_led_gpio(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return
    if n not in GPIO_PINS:
        return
    tmp = LED_GPIO + ".tmp"
    with open(tmp, "w") as f:
        f.write(str(n))
    os.rename(tmp, LED_GPIO)


def led_hidden():
    return os.path.exists(LED_HIDDEN)


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
BUTTON_FUNCTIONS = (("off", "Off"), ("toggle", "Toggle network"),
                    ("dcnow", "Select DCNow!"), ("dcnet", "Select DCNET"))
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


NETWORKS = ("dcnow", "dcnet")
_COLOUR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
try:
    _TEXT = basestring  # noqa: F821  (Python 2: json gives unicode)
except NameError:
    _TEXT = str


LED_ORDERS = ("RGB", "RBG", "GRB", "GBR", "BRG", "BGR")   # wire order of the WS2812 strip; most are GRB

# Colour calibration: a simple NeoPixel-style white-balance pipeline, not a
# per-colour grid. netswitch_led.py applies, per channel and in this order:
# gamma correction (fixed, see GAMMA below) -> the white_balance multiplier
# -> max_brightness. White balance is found once, by eye, with the LED
# showing solid white (see WB_TEST below) and the R/G/B sliders nudging
# down whichever channel looks too strong; max_brightness is the familiar
# global brightness slider, renamed to make clear it's a ceiling applied
# after calibration, independent of the requested colour. GAMMA is stored
# for forward compatibility (a hand-edited led.json can tune it) but has no
# page control - 2.2 is a standard enough approximation of perceived
# brightness that it shouldn't need per-installation tuning.
GAMMA = 2.2


def default_led_config():
    cfg = {"max_brightness": 0.08, "order": "GRB", "gamma": GAMMA,
           "white_balance": {"r": 1.0, "g": 1.0, "b": 1.0},
           "colours": dict((net, dict((st, {"color": c, "effect": e, "speed": sp, "brightness": None,
                                            "enabled": on, "leds": None})
                                      for st, (c, e, sp, on) in _DEFAULT_COLOURS.items()))
                           for net in NETWORKS)}
    if led_count() > 1:   # a strip: scanning animation instead of a breathing single LED
        for net in NETWORKS:
            cfg["colours"][net]["wifi-setup"]["effect"] = "scanner"
    return cfg


def clean_led_config(data):
    """Defaults for anything missing or invalid in data."""
    cfg = default_led_config()
    if not isinstance(data, dict):
        return cfg
    try:
        cfg["max_brightness"] = min(1.0, max(0.0, float(data.get("max_brightness", cfg["max_brightness"]))))
    except (TypeError, ValueError):
        pass
    try:
        cfg["gamma"] = min(4.0, max(0.5, float(data.get("gamma", cfg["gamma"]))))
    except (TypeError, ValueError):
        pass
    if data.get("order") in LED_ORDERS:
        cfg["order"] = data["order"]
    wb = data.get("white_balance")
    if isinstance(wb, dict):
        for ch in ("r", "g", "b"):
            try:
                cfg["white_balance"][ch] = min(1.0, max(0.0, float(wb[ch])))
            except (TypeError, ValueError, KeyError):
                pass
    colours = data.get("colours")
    if isinstance(colours, dict):
        for net in NETWORKS:
            per_net = colours.get(net)
            if not isinstance(per_net, dict):
                continue
            for st in _DEFAULT_COLOURS:
                entry = per_net.get(st)
                if not isinstance(entry, dict):
                    continue
                if isinstance(entry.get("color"), _TEXT) and _COLOUR_RE.match(entry["color"]):
                    cfg["colours"][net][st]["color"] = entry["color"].lower()
                if entry.get("blink") is True and "effect" not in entry:   # older led.json
                    cfg["colours"][net][st]["effect"] = "blink"
                elif entry.get("blink") is False and "effect" not in entry:
                    cfg["colours"][net][st]["effect"] = "solid"
                if entry.get("effect") in EFFECT_NAMES:
                    cfg["colours"][net][st]["effect"] = str(entry["effect"])
                if entry.get("speed") in SPEEDS:
                    cfg["colours"][net][st]["speed"] = str(entry["speed"])
                if isinstance(entry.get("enabled"), bool):
                    cfg["colours"][net][st]["enabled"] = entry["enabled"]
                leds = entry.get("leds")   # None = all LEDs, else [first, last], 1-based
                if isinstance(leds, list) and len(leds) == 2 and \
                        all(isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 300 for x in leds):
                    cfg["colours"][net][st]["leds"] = [min(leds), max(leds)]
                level = entry.get("brightness")   # None = use the global brightness
                if isinstance(level, (int, float)) and not isinstance(level, bool):
                    cfg["colours"][net][st]["brightness"] = min(1.0, max(0.0, float(level)))
    return cfg


def led_config():
    try:
        with open(LED_CONFIG) as f:
            return clean_led_config(json.load(f))
    except (IOError, OSError, ValueError):
        return default_led_config()


def save_led_config(data):
    cfg = clean_led_config(data)
    tmp = LED_CONFIG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=1, sort_keys=True)
    os.rename(tmp, LED_CONFIG)   # the LED service never sees a half-written file
    return cfg


WB_TEST = "/tmp/dreampi-netswitch.wbtest"   # unix time, touched while the white-balance test is on
WB_TEST_STALE = 3   # seconds; a closed/crashed tab stops driving the LED after this


def wb_test_active():
    """True while the settings page wants the LED held at solid white (run
    through the normal calibration pipeline) for white-balance adjustment,
    instead of its usual status effects; False once the page stops saying
    so (closed, or went quiet - stale past WB_TEST_STALE)."""
    raw = read_file(WB_TEST)
    if not raw:
        return False
    try:
        return time.time() - float(raw) <= WB_TEST_STALE
    except ValueError:
        return False


def touch_wb_test():
    tmp = WB_TEST + ".tmp"
    with open(tmp, "w") as f:
        f.write("%f" % time.time())
    os.rename(tmp, WB_TEST)


def clear_wb_test():
    try:
        os.remove(WB_TEST)
    except OSError:
        pass


def active_messages(state=None, net_state=None, wifi=True):
    """Enabled LED messages that apply right now, lowest priority first (the
    LED service draws them in this order, so later ones end up on top).
    Each: key, category, color, effect, speed, brightness (effective), leds.
    wifi=False skips netswitch_buttons.py's state (used for the DreamPi dot
    preview, which only ever previews the DreamPi-state message)."""
    if state is None:
        state = dreampi_state()[0]
    if net_state is None:
        net_state = network_state()
    active = [state]
    if net_state:
        if not net_state.get("network"):
            active.append("no-network")
        elif net_state.get("internet") is False:
            active.append("no-internet")
        if net_state.get("pi_problem"):
            active.append("pi")
        if net_state.get("ethernet"):
            active.append("ethernet")
        if net_state.get("wifi"):
            active.append("wifi")
    if wifi:
        ws = wifi_state().get("state", "idle")
        if ws in ("scanning", "hosting", "connecting"):
            active.append("wifi-setup")
        elif ws == "ok":
            active.append("wifi-ok")
        elif ws == "failed":
            active.append("wifi-failed")
    cfg = led_config()
    looks = cfg["colours"]["dcnet" if os.path.exists(FLAG) else "dcnow"]
    out = []
    for key in sorted(set(active), key=lambda k: PRIORITY.get(k, 0)):
        if key not in looks or not looks[key].get("enabled", True):
            continue
        look = dict(looks[key])
        look["key"] = key
        look["category"] = CATEGORY.get(key, "info")
        if look.get("brightness") is None:
            look["brightness"] = cfg["max_brightness"]
        out.append(look)
    return out


def status_look(state=None):
    """The most important active message (what a single LED shows), or None
    when every active message is switched off."""
    msgs = active_messages(state)
    return msgs[-1] if msgs else None
