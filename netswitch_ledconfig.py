# DreamPi Netswitch add-on - LED settings: led.json (colours, effects, white
# balance, brightness), LED count / output pin, the LED message list and
# active_messages(), which says what the LEDs (and the status dot) show now.
# Shared by the web page and the LED service. Works on Python 3 and 2.7.
import json
import os
import re
import time

import netswitch_core as core

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
    """LEDs connected: 1 = a single LED (the default), more = a strip, 0 = none:
    the LED service then idles and the page hides the LED settings. Set at
    install time (install.sh --leds=N) and editable from the page."""
    try:
        return max(0, min(300, int((core.read_file(core.LED_COUNT) or "1").strip())))
    except ValueError:
        return 1


def save_led_count(n):
    try:
        n = max(0, min(300, int(n)))
    except (TypeError, ValueError):
        return
    tmp = core.LED_COUNT + ".tmp"
    with open(tmp, "w") as f:
        f.write(str(n))
    os.rename(tmp, core.LED_COUNT)


GPIO_PINS = (10, 12, 18, 21)   # allowed LED output pins; see netswitch_led.py for what each needs
DEFAULT_GPIO = 18


def led_gpio():
    try:
        n = int((core.read_file(core.LED_GPIO) or "").strip())
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
    tmp = core.LED_GPIO + ".tmp"
    with open(tmp, "w") as f:
        f.write(str(n))
    os.rename(tmp, core.LED_GPIO)


def led_hidden():
    return os.path.exists(core.LED_HIDDEN)


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
        with open(core.LED_CONFIG) as f:
            return clean_led_config(json.load(f))
    except (IOError, OSError, ValueError):
        return default_led_config()


def save_led_config(data):
    cfg = clean_led_config(data)
    tmp = core.LED_CONFIG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=1, sort_keys=True)
    os.rename(tmp, core.LED_CONFIG)   # the LED service never sees a half-written file
    return cfg
WB_TEST_STALE = 3   # seconds; a closed/crashed tab stops driving the LED after this


def wb_test_active():
    """True while the settings page wants the LED held at solid white (run
    through the normal calibration pipeline) for white-balance adjustment,
    instead of its usual status effects; False once the page stops saying
    so (closed, or went quiet - stale past WB_TEST_STALE)."""
    raw = core.read_file(core.WB_TEST)
    if not raw:
        return False
    try:
        return time.time() - float(raw) <= WB_TEST_STALE
    except ValueError:
        return False


def touch_wb_test():
    tmp = core.WB_TEST + ".tmp"
    with open(tmp, "w") as f:
        f.write("%f" % time.time())
    os.rename(tmp, core.WB_TEST)


def clear_wb_test():
    try:
        os.remove(core.WB_TEST)
    except OSError:
        pass


def active_messages(state=None, net_state=None, wifi=True):
    """Enabled LED messages that apply right now, lowest priority first (the
    LED service draws them in this order, so later ones end up on top).
    Each: key, category, color, effect, speed, brightness (effective), leds.
    wifi=False skips netswitch_buttons.py's state (used for the DreamPi dot
    preview, which only ever previews the DreamPi-state message)."""
    if state is None:
        state = core.dreampi_state()[0]
    if net_state is None:
        net_state = core.network_state()
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
        ws = core.wifi_state().get("state", "idle")
        if ws in ("scanning", "hosting", "connecting"):
            active.append("wifi-setup")
        elif ws == "ok":
            active.append("wifi-ok")
        elif ws == "failed":
            active.append("wifi-failed")
    cfg = led_config()
    looks = cfg["colours"]["dcnet" if os.path.exists(core.FLAG) else "dcnow"]
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
