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

# LED messages. Every message is independent: on/off, colour, effect, speed, brightness and
# which LEDs. Many share the same default look on purpose; they are separate so each can be
# customised or sent to its own LED. Colour meaning: the DCNow! and DCNET messages use the
# networks' own colours, which are global (Settings > Network colours, core.network_colour(): orange
# and blue unless changed) and cannot be set per message; PURPLE = Netlink, RED = something is wrong,
# so a failed call is red, not the network's own colour. A message's colour is "#rrggbb", or "dcnow" /
# "dcnet" for the network's colour (resolved by active_messages()).
GROUPS = [   # key, heading (the order the settings page lists them)
    ("system", "System"),
    ("network", "Network"),
    ("call-dcnow", u"Call \u2014 DCNow!"),
    ("call-dcnet", u"Call \u2014 DCNET"),
    ("call-netlink", u"Call \u2014 Netlink"),
    ("wifi", "Wi-Fi setup"),
]
DCNOW, DCNET, PURPLE = "dcnow", "dcnet", "#aa00ff"   # the first two are the networks' global colours
RED, AMBER, GREEN, CYAN = "#ff0000", "#ffd000", "#00ff00", "#00c8ff"
LED_STATES = [
    # key, label, group, colour, effect, speed, enabled by default, detected
    # "detected" False = the page can set it up, but nothing tells the add-on yet when it
    # happens (DreamPi's state file has no "connecting"/"failed", Netlink isn't selectable
    # and nothing marks a network switch), so the message never shows. Not faked.
    ("busy", "Starting up", "system", AMBER, "blink", "slow", True, True),
    ("off", "DreamPi not running", "system", RED, "blink", "slow", True, True),
    ("pi", "Power or heat problem", "system", RED, "blink", "fast", True, True),
    ("unknown", "State unknown", "system", "#3c3c3c", "solid", "slow", True, True),
    ("no-network", "No network", "network", RED, "solid", "slow", True, True),
    ("no-internet", "No internet", "network", AMBER, "blink", "slow", True, True),
    ("ethernet", "Ethernet connected", "network", GREEN, "solid", "slow", False, True),
    ("wifi", "Wi-Fi connected", "network", CYAN, "solid", "slow", False, True),
    ("net-switch", "Network switching", "network", "#ffffff", "blink", "fast", False, False),
    ("ready-dcnow", u"Ready for calls \u2014 DCNow!", "call-dcnow", DCNOW, "solid", "slow", True, True),
    ("connecting-dcnow", u"Connecting \u2014 DCNow!", "call-dcnow", DCNOW, "blink", "slow", True, False),
    ("call-dcnow", u"In a call \u2014 DCNow!", "call-dcnow", DCNOW, "solid", "slow", True, True),
    ("failed-dcnow", u"Call failed \u2014 DCNow!", "call-dcnow", RED, "blink", "fast", True, False),
    ("ready-dcnet", u"Ready for calls \u2014 DCNET", "call-dcnet", DCNET, "solid", "slow", True, True),
    ("connecting-dcnet", u"Connecting \u2014 DCNET", "call-dcnet", DCNET, "blink", "slow", True, False),
    ("call-dcnet", u"In a call \u2014 DCNET", "call-dcnet", DCNET, "solid", "slow", True, True),
    ("failed-dcnet", u"Call failed \u2014 DCNET", "call-dcnet", RED, "blink", "fast", True, False),
    ("ready-netlink", u"Ready for calls \u2014 Netlink", "call-netlink", PURPLE, "solid", "slow", False, False),
    ("connecting-netlink", u"Connecting \u2014 Netlink", "call-netlink", PURPLE, "blink", "slow", False, False),
    ("call-netlink", u"In a call \u2014 Netlink", "call-netlink", PURPLE, "solid", "slow", False, True),
    ("failed-netlink", u"Call failed \u2014 Netlink", "call-netlink", RED, "blink", "fast", False, False),
    # Wi-Fi setup (netswitch_buttons.py) outranks everything else: while it's in progress "no
    # network"/"no internet" are usually also true and would otherwise hide it.
    ("wifi-setup", "Wi-Fi setup: choose a network", "wifi", CYAN, "blink", "slow", True, True),
    ("wifi-ok", "Wi-Fi setup: connected", "wifi", GREEN, "solid", "slow", True, True),
    ("wifi-failed", "Wi-Fi setup: couldn't connect", "wifi", RED, "blink", "slow", True, True),
]
# What wins when several messages apply at once, most important first: Wi-Fi setup, then
# errors, then what is happening, then plain information; "State unknown" is the last resort
# (see active_messages(): it is dropped whenever anything else applies).
PRIORITY_ORDER = [
    "wifi-setup", "wifi-ok", "wifi-failed",
    "no-network", "no-internet", "pi", "off",
    "failed-dcnow", "failed-dcnet", "failed-netlink",
    "net-switch", "busy",
    "call-dcnow", "call-dcnet", "call-netlink",
    "connecting-dcnow", "connecting-dcnet", "connecting-netlink",
    "ready-dcnow", "ready-dcnet", "ready-netlink",
    "ethernet", "wifi",
    "unknown",
]
PRIORITY = dict((k, len(PRIORITY_ORDER) - i) for i, k in enumerate(PRIORITY_ORDER))   # higher = more important
GROUP = dict((s[0], s[2]) for s in LED_STATES)
NET_BOUND = dict((s[0], s[3]) for s in LED_STATES if s[3] in ("dcnow", "dcnet"))   # message -> the network whose colour it shows
_DEFAULT_LOOKS = dict((s[0], s[3:7]) for s in LED_STATES)
# LED effects: "solid" (on) and "blink" (on and off, half the time each; slow = a second per blink, fast = 0.4 s).
# More are planned (the engine in netswitch_led.py is built so one can be added next to them); the earlier
# animations were removed.
EFFECTS = [
    ("solid", "Solid", False),
    ("blink", "Blink", False),
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


def _default_message(st):
    c, e, sp, on = _DEFAULT_LOOKS[st]
    return {"color": c, "effect": e, "speed": sp, "brightness": None, "enabled": on, "leds": None}


def default_led_config():
    return {"max_brightness": 0.08, "order": "GRB", "gamma": GAMMA,
            "white_balance": {"r": 1.0, "g": 1.0, "b": 1.0},
            "messages": dict((s[0], _default_message(s[0])) for s in LED_STATES)}


def _apply_entry(target, entry, key=None):
    """Copy the valid fields of one message's saved settings onto target (a default). The colour of a DCNow! / DCNET
    message is the network's global colour, so a saved colour for those is ignored."""
    if key not in NET_BOUND and isinstance(entry.get("color"), _TEXT) and _COLOUR_RE.match(entry["color"]):
        target["color"] = str(entry["color"].lower())
    if entry.get("blink") is True and "effect" not in entry:   # an older led.json
        target["effect"] = "blink"
    elif entry.get("blink") is False and "effect" not in entry:
        target["effect"] = "solid"
    if entry.get("effect") in EFFECT_NAMES:
        target["effect"] = str(entry["effect"])
    if entry.get("speed") in SPEEDS:
        target["speed"] = str(entry["speed"])
    if isinstance(entry.get("enabled"), bool):
        target["enabled"] = entry["enabled"]
    leds = entry.get("leds")   # None = all LEDs, else [first, last], 1-based (one LED = [n, n])
    if isinstance(leds, list) and len(leds) == 2 and \
            all(isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 300 for x in leds):
        target["leds"] = [min(leds), max(leds)]
    level = entry.get("brightness")   # None = use the global brightness
    if isinstance(level, (int, float)) and not isinstance(level, bool):
        target["brightness"] = min(1.0, max(0.0, float(level)))


# Before the messages were independent, led.json kept one table per *selected* network:
# {"colours": {"dcnow": {<old state>: {...}}, "dcnet": {...}}}. Those tables are still read
# (never written): an old entry carries over when the user had changed it from its old default;
# one still at its old default simply gets the new default look.
_LEGACY_DEFAULTS = {   # old state -> (colour, effect, speed, enabled)
    "wifi-setup": ("#0046ff", "breathe", "slow", True), "wifi-ok": ("#00ff00", "solid", "slow", True),
    "wifi-failed": ("#ff0000", "blink", "slow", True), "no-network": ("#ff0000", "solid", "slow", True),
    "no-internet": ("#ff7a00", "blink", "slow", True), "pi": ("#ff00aa", "breathe", "slow", True),
    "off": ("#ff0000", "blink", "slow", True), "unknown": ("#3c3c3c", "solid", "slow", True),
    "busy": ("#ffaa00", "blink", "slow", True), "call-dcnow": ("#ff5000", "solid", "slow", True),
    "call-dcnet": ("#0046ff", "solid", "slow", True), "call": ("#aa00ff", "solid", "slow", True),
    "ok": ("#00ff00", "solid", "slow", True), "ethernet": ("#ffffff", "solid", "slow", False),
    "wifi": ("#00c8ff", "solid", "slow", False),
}
_LEGACY_MAP = {   # new message -> (old state, the old tables to look in, in order)
    "ready-dcnow": ("ok", ("dcnow",)), "ready-dcnet": ("ok", ("dcnet",)),
    "call-netlink": ("call", ("dcnow", "dcnet")),
}


def _legacy_entry(colours, key):
    old, nets = _LEGACY_MAP.get(key, (key, ("dcnow", "dcnet")))
    base = _LEGACY_DEFAULTS.get(old)
    if base is None:
        return None
    for net in nets:
        entry = (colours.get(net) or {}).get(old) if isinstance(colours.get(net), dict) else None
        if not isinstance(entry, dict):
            continue
        got = {"color": base[0], "effect": base[1], "speed": base[2], "enabled": base[3], "leds": None, "brightness": None}
        _apply_entry(got, entry, key)
        effect_same = got["effect"] == base[1] or (old == "wifi-setup" and got["effect"] == "scanner")
        if (got["color"], got["speed"], got["enabled"]) != (base[0], base[2], base[3]) or not effect_same \
                or got["leds"] is not None or got["brightness"] is not None:
            return got
    return None


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
    messages = data.get("messages")
    if isinstance(messages, dict):
        for st in _DEFAULT_LOOKS:
            if isinstance(messages.get(st), dict):
                _apply_entry(cfg["messages"][st], messages[st], st)
    elif isinstance(data.get("colours"), dict):
        for st in _DEFAULT_LOOKS:
            carried = _legacy_entry(data["colours"], st)
            if carried:
                if st in NET_BOUND:
                    carried.pop("color", None)
                cfg["messages"][st].update(carried)
    for st, m in cfg["messages"].items():     # an effect that no longer exists (an older led.json) gets the message's default
        if m.get("effect") not in EFFECT_NAMES:
            m["effect"] = _DEFAULT_LOOKS[st][1]
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


def message_for_state(state, dcnet):
    """The LED message for a dreampi_state() value (None if there is none). "Ready" and
    "In a call" depend on the network: ready follows the selected one; DreamPi's own other
    calls (Netlink, XBAND) are the Netlink message."""
    if state == "ok":
        return "ready-dcnet" if dcnet else "ready-dcnow"
    if state == "call":
        return "call-netlink"
    return state if state in _DEFAULT_LOOKS else None


def active_messages(state=None, net_state=None, wifi=True):
    """Enabled LED messages that apply right now, lowest priority first (the
    LED service draws them in this order, so later ones end up on top).
    Each: key, group, color, effect, speed, brightness (effective), leds.
    A disabled message gives nothing. "State unknown" is only a fallback: it is
    left out as soon as any other enabled message applies.
    wifi=False skips netswitch_buttons.py's state (used for the DreamPi dot
    preview, which only ever previews the DreamPi-state message)."""
    if state is None:
        state = core.dreampi_state()[0]
    if net_state is None:
        net_state = core.network_state()
    active = [message_for_state(state, os.path.exists(core.FLAG))]
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
    looks = cfg["messages"]
    out = []
    for key in sorted(set(k for k in active if k), key=lambda k: PRIORITY.get(k, 0)):
        if key not in looks or not looks[key].get("enabled", True):
            continue
        look = dict(looks[key])
        if key in NET_BOUND:
            look["color"] = core.network_colour(NET_BOUND[key])["led"]      # the network's global colour, as the LED shows it
        look["key"] = key
        look["group"] = GROUP.get(key, "system")
        if look.get("brightness") is None:
            look["brightness"] = cfg["max_brightness"]
        out.append(look)
    if len(out) > 1:
        out = [m for m in out if m["key"] != "unknown"]   # a fallback, never on top of or beside anything else
    return out


