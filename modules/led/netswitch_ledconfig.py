# DreamPi Netswitch add-on - LED settings and what the LEDs show now.
# led.json keeps colour calibration (white balance, brightness, wire order) and the colour GROUPS: each group is one look
# (colour, effect, speed, level, which LEDs) plus the list of messages (triggers) that use it. A message is something the add-on can
# tell happened ("Starting up", "No internet", "Update available" ...): the modules announce theirs in module.json
# ("led_messages", see core.module_led_messages()); active_messages() works out which are true right now, finds their groups and
# gives the looks the LED service draws. The order of the groups is the priority: the top group wins where looks overlap.
# Also: LED count / output pin and the white-balance test flag. Shared by the web page and the LED service. Works on Python 3 and 2.7.
import json
import re
import os
import time

import base_core as core
import netswitch_led_inputs as inputs

LED_COLOURS = os.path.join(core.BASE_DIR, "led_colours.json")   # {"red": "#rrggbb"}: how the LED shows a palette colour when that is not the default
LED_DEFAULTS = {
 "global": "#8090ff",
 "red": "#ff0000",
 "orange": "#ff8c00",
 "yellow": "#ffd000",
 "green": "#00ff00",
 "cyan": "#00c8ff",
 "blue": "#0046ff",
 "purple": "#aa00ff",
 "white": "#ffffff",
 "bright-red": "#ff5050",
 "bright-green": "#50ff70",
 "bright-cyan": "#70e0ff",
 "bright-blue": "#5080ff",
 "bright-purple": "#cc66ff",
 "bright-pink": "#ff70b0"
}    # how the LED shows each colour the add-on ships (the palette itself is the base's, and only knows the screen colours)
LED_CONFIG = os.path.join(core.BASE_DIR, "led.json")     # brightness, colours, wire order, white balance, the groups
LED_COUNT = os.path.join(core.BASE_DIR, "led_count")      # number of LEDs, editable from the page
LED_GPIO = os.path.join(core.BASE_DIR, "led_gpio")        # output pin (10, 12, 18 or 21), likewise
WB_TEST = core.TMP_PREFIX + ".wbtest"                     # unix time, touched while the white-balance test is on

# -------------------------------------------------------------------- the messages
# The messages themselves are announced by the modules (module.json "led_messages"); the detection of when each is true is
# active_keys() below. A message whose module is off is not offered and never lights.
_KEY = re.compile(r"^[a-z][a-z0-9-]*$")


def messages():
    """[{"key", "label", "group", "description", "module"}] of the enabled modules, in picker order (core.module_led_messages())."""
    return core.module_led_messages()


ERRORS = ("notrunning", "no-network", "no-internet", "undervoltage", "hot", "modem-missing")
WARNINGS = ("dns-fail", "net-slow", "wifi-weak", "no-ip", "throttled", "warm", "wifisetup-failed", "update-failed", "update-addon", "update-dreampi")
# a message an older led.json has, as the messages that replaced it
OLD_KEYS = {"ready": ["ready-dcnow", "ready-dcnet"]}

# -------------------------------------------------------------------- the looks (groups)
# A group's colour is a palette id (core.PALETTE, the LED value of it), or a token that follows the networks' global colours:
# "dcnow", "dcnet" (what the network switcher gave them) or "network" (the colour of whichever network is selected).
COLOUR_TOKENS = [("dcnow", "DCNow!"), ("dcnet", "DCNET")]      # ("network" comes from the switcher module, "global" is in the palette)
TOKEN_IDS = tuple(t[0] for t in COLOUR_TOKENS)
# LED effects (the engine, with the timings, is in netswitch_led.py): name, label, whether it takes a speed.
EFFECTS = [
    ("solid", "Solid", False),
    ("blink", "Blink", False),
    ("fade", "Fade", False),
    ("breathe", "Breathe", False),
    ("blink1", "Short blink", False),
    ("blink2", "Double blink", False),
    ("blink3", "Triple blink", False),
    ("rainbow", "Rainbow", False),
]
EFFECT_NAMES = set(e[0] for e in EFFECTS)
SPEEDS = ("slow", "fast")
MAX_GROUPS = 24
try:
    _TEXT = basestring  # noqa: F821  (Python 2: json gives unicode)
except NameError:
    _TEXT = str


def _group(gid, colour, effect, speed, messages):
    return {"id": gid, "colour": colour, "effect": effect, "speed": speed, "brightness": None, "leds": None, "messages": list(messages)}


def default_groups():
    """The looks the add-on starts with, most important first (the order is the priority): red blinking when DreamPi is not running,
    yellow blinking while starting, the network's colour during a call (purple for other calls), bright pink blinking while a DC99
    event you asked to be reminded of starts soon, and the network's colour while ready or selected. Everything else is optional:
    add it to a row on the page."""
    return [
        _group("g1", "red", "blink", "slow", ["notrunning"]),
        _group("g2", "yellow", "blink", "slow", ["busy"]),
        _group("g3", "network", "solid", "slow", ["call-dcnow", "call-dcnet"]),
        _group("g4", "purple", "solid", "slow", ["call-other"]),
        _group("g5", "bright-pink", "blink", "slow", ["event-soon"]),
        _group("g6", "network", "solid", "slow", ["ready-dcnow", "ready-dcnet", "sel-dcnow", "sel-dcnet"]),
    ]


def _old_default_groups():
    """What the add-on started with before the order of the groups was the priority (it had a separate list of messages in order)."""
    return [
        _group("g1", "dcnow", "solid", "slow", ["sel-dcnow", "ready-dcnow", "call-dcnow"]),
        _group("g2", "dcnet", "solid", "slow", ["sel-dcnet", "ready-dcnet", "call-dcnet"]),
        _group("g3", "purple", "solid", "slow", ["call-other"]),
        _group("g4", "yellow", "blink", "slow", ["busy"]),
        _group("g5", "red", "blink", "slow", ["notrunning"]),
        _group("g6", "bright-pink", "blink", "slow", ["event-soon"]),
    ]


def led_count():
    """LEDs connected: 1 = a single LED (the default), more = a strip, 0 = none:
    the LED service then idles and the page hides the LED settings. Set at
    install time (install.sh --leds=N) and editable from the page."""
    try:
        return max(0, min(300, int((core.read_file(LED_COUNT) or "1").strip())))
    except ValueError:
        return 1


def save_led_count(n):
    try:
        n = max(0, min(300, int(n)))
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
        n = int((core.read_file(LED_GPIO) or "").strip())
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
    return {"max_brightness": 0.08, "order": "GRB", "gamma": GAMMA,
            "white_balance": {"r": 1.0, "g": 1.0, "b": 1.0},
            "groups": default_groups()}


def order_by_priority(groups, priority):
    """Groups of an older led.json, which had the message priority as a separate list, put in the order that list gave: a group takes the
    place of its most important message (groups with no ranked message keep their order, at the end). Groups that are the add-on's
    own old defaults become the new defaults, which split the groups so that the order can do the same."""
    if groups == _old_default_groups():
        return default_groups()
    rank = dict((k, i) for i, k in enumerate(priority if isinstance(priority, list) else []))
    big = len(rank) + 1
    return sorted(groups, key=lambda g: min([rank.get(m, big) for m in g["messages"]] or [big]))


_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def led_overrides():
    """{palette id: "#rrggbb"} the user gave the LED (only for colours that are still in the palette)."""
    try:
        with open(LED_COLOURS) as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        return {}
    ids = core.palette_ids()
    return dict((i, v.lower()) for i, v in data.items() if isinstance(data, dict) and i in ids and isinstance(v, _TEXT) and _HEX.match(v)) if isinstance(data, dict) else {}


def led_default(ident):
    """How the LED shows a palette colour as shipped: the add-on's own table, else (a colour the user added) its screen colour."""
    return LED_DEFAULTS.get(ident) or core.colour(ident)["ui"]


def led_colour(ident):
    """"#rrggbb" for what the LED is asked to show for a palette colour or a colour token (before the white balance and the brightness).
    A token follows the colour it stands for: "Selected network" is the LED value of the selected network's colour."""
    ident = core.LEGACY_COLOURS.get(ident, ident)
    if ident in LED_DEFAULTS or ident in core.palette_ids():
        return led_overrides().get(ident) or led_default(ident)
    if ident == "network":
        return led_colour(network_colour(inputs.selected())["id"])
    return led_colour(core.DEFAULT_COLOUR)


def save_led_colours(over):
    tmp = LED_COLOURS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(over, f)
    os.rename(tmp, LED_COLOURS)


def set_led_colour(ident, led):
    """The user changes how the LED shows a palette colour, "#rrggbb". A value equal to the default is not kept. False for an unknown colour or a bad value."""
    if ident not in core.palette_ids() or not (isinstance(led, _TEXT) and _HEX.match(led)):
        return False
    over = led_overrides()
    if led.lower() == led_default(ident).lower():
        over.pop(ident, None)
    else:
        over[ident] = led.lower()
    save_led_colours(over)
    return True


def reset_led_colours(ident=None):
    """Put one colour (or all) back to what the LED showed as shipped."""
    over = {} if ident is None else dict((i, v) for i, v in led_overrides().items() if i != ident)
    save_led_colours(over)


def colour_table():
    """[{"id", "name", "ui", "led", "led_default", "fixed"}] of the palette, for the page's LED colour editor; a colour token ("Selected network")
    follows another colour, so its LED value is that one's and it is fixed."""
    over = led_overrides()
    out = []
    for c in core.colours():
        if c.get("token"):
            out.append({"id": c["id"], "name": c["name"], "ui": c["ui"], "led": led_colour(c["id"]), "led_default": led_colour(c["id"]), "fixed": True})
        else:
            out.append({"id": c["id"], "name": c["name"], "ui": c["ui"], "led": over.get(c["id"]) or led_default(c["id"]),
                        "led_default": led_default(c["id"]), "fixed": False})
    return out


def network_colour(net):
    """The palette entry of the colour the user gave the network "dcnow" or "dcnet" (the network switcher's colour picks, in the
    base's colours.json; orange and blue without them)."""
    return core.colour(core.module_colours("switcher").get(net) or {"dcnow": "orange", "dcnet": "blue"}.get(net, core.DEFAULT_COLOUR))


def _valid_colour(c):
    return isinstance(c, _TEXT) and (c in TOKEN_IDS or c in core.colour_ids() or c in core.LEGACY_COLOURS)


def clean_groups(data):
    """The saved groups made safe: at most MAX_GROUPS, unique ids, a valid colour / effect / speed / level / LED range, and each
    message in at most one group (the first that has it; a message of a module that is off stays in its group). Returns None when data
    isn't a list."""
    if not isinstance(data, list):
        return None
    out, seen_ids, seen_msgs = [], set(), set()
    for g in data[:MAX_GROUPS]:
        if not isinstance(g, dict):
            continue
        gid = g.get("id") if isinstance(g.get("id"), _TEXT) and g.get("id") and len(g["id"]) <= 24 and g["id"] not in seen_ids else None
        if gid is None:
            n = 1
            while "g%d" % n in seen_ids:
                n += 1
            gid = "g%d" % n
        seen_ids.add(gid)
        group = _group(str(gid), core.LEGACY_COLOURS.get(str(g["colour"]), str(g["colour"])) if _valid_colour(g.get("colour")) else "orange",
                       str(g["effect"]) if g.get("effect") in EFFECT_NAMES else "solid",
                       str(g["speed"]) if g.get("speed") in SPEEDS else "slow", [])
        level = g.get("brightness")                      # None = use the global brightness
        if isinstance(level, (int, float)) and not isinstance(level, bool):
            group["brightness"] = min(1.0, max(0.0, float(level)))
        leds = g.get("leds")                             # None = all LEDs, else [first, last], 1-based (one LED = [n, n])
        if isinstance(leds, list) and len(leds) == 2 and all(isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 300 for x in leds):
            group["leds"] = [min(leds), max(leds)]
        wanted = []
        for key in g.get("messages") if isinstance(g.get("messages"), list) else []:
            wanted.extend(OLD_KEYS.get(key, [key]) if isinstance(key, _TEXT) else [])
        for key in wanted:
            if _KEY.match(key) and key not in seen_msgs:
                seen_msgs.add(key)
                group["messages"].append(str(key))
        out.append(group)
    return out


def clean_led_config(data):
    """Defaults for anything missing or invalid in data. An older led.json (one look per message, "messages" or "colours") has no
    groups: it gets the default groups."""
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
    groups = clean_groups(data.get("groups"))
    if groups is not None:
        cfg["groups"] = order_by_priority(groups, data.get("priority")) if "priority" in data else groups
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


def colour_choices():
    """What a group's colour can be, for the page: the palette (id, name, page colour) and the network tokens."""
    return {"palette": [{"id": c["id"], "name": c["name"], "ui": c["ui"], "ui_l": c["ui_l"]} for c in core.colours()],
            "tokens": [{"id": t[0], "name": t[1]} for t in COLOUR_TOKENS]}


def resolve_colour(colour, selected="dcnow"):
    """The LED colour ("#rrggbb", as the LED shows it) of a group's colour: a palette id, or a network token."""
    if colour == "network":
        colour = selected
    if colour in ("dcnow", "dcnet"):
        return led_colour(network_colour(colour)["id"])
    return led_colour(colour)


WB_TEST_STALE = 3   # seconds; a closed/crashed tab stops driving the LED after this


def _wb_test_file():
    """(time, colour) written by the page while a test is open: white for the white balance, or the colour being calibrated."""
    raw = (core.read_file(WB_TEST) or "").split()
    if not raw:
        return None, None
    try:
        when = float(raw[0])
    except ValueError:
        return None, None
    colour = raw[1] if len(raw) > 1 and re.match(r"^#[0-9a-fA-F]{6}$", raw[1]) else "#ffffff"
    return when, colour.lower()


def wb_test_active():
    """True while the settings page wants the LED held at one solid colour (white for the white balance, or the colour being
    calibrated), run through the normal calibration pipeline, instead of its usual status effects; False once the page stops
    saying so (closed, or went quiet - stale past WB_TEST_STALE)."""
    when, _colour = _wb_test_file()
    return when is not None and time.time() - when <= WB_TEST_STALE


def wb_test_colour():
    """The colour of the test that is open ("#ffffff" for the white balance)."""
    return _wb_test_file()[1] or "#ffffff"


def touch_wb_test(colour=None):
    tmp = WB_TEST + ".tmp"
    with open(tmp, "w") as f:
        f.write("%f %s" % (time.time(), colour if isinstance(colour, _TEXT) and re.match(r"^#[0-9a-fA-F]{6}$", colour) else "#ffffff"))
    os.rename(tmp, WB_TEST)


def clear_wb_test():
    try:
        os.remove(WB_TEST)
    except OSError:
        pass


# -------------------------------------------------------------------- what is true right now
def gather(live=True):
    """What the messages are made from, read from the files the other services write (netswitch_led_inputs.py). live=False is only
    what DreamPi is doing and which network is selected (the status dot's preview)."""
    return inputs.gather(live)


def active_keys(ctx):
    """The set of message keys that are true for this ctx (see gather()). "off" is never in it: it is the fallback."""
    state, net, keys = ctx["state"], ctx.get("net") or {}, set()
    keys.add({"busy": "busy", "ok": "ready-" + ctx["selected"], "off": "notrunning", "unknown": "unknown", "call-dcnow": "call-dcnow",
              "call-dcnet": "call-dcnet", "call": "call-other"}.get(state, "unknown"))
    keys.add("sel-" + ctx["selected"])
    if net:                                              # only while the web service's measurements are fresh
        if not net.get("network"):
            keys.add("no-network")
        elif net.get("internet") is False and not net.get("dns_fail"):
            keys.add("no-internet")
        if net.get("internet") is True:
            keys.add("internet-ok")
        for flag, key in (("no_ip", "no-ip"), ("dns_fail", "dns-fail"), ("ethernet", "ethernet"), ("wifi", "wifi"),
                          ("wifi_weak", "wifi-weak"), ("slow", "net-slow"), ("undervoltage", "undervoltage"),
                          ("throttled", "throttled"), ("hot", "hot"), ("warm", "warm")):
            if net.get(flag):
                keys.add(key)
        if net.get("modem") is True:
            keys.add("modem-ok")
        elif net.get("modem") is False:
            keys.add("modem-missing")
    ws = ctx.get("wifi", "idle")
    if ws in ("scanning", "hosting"):
        keys.add("wifisetup-scan")
    if ws == "hosting":
        keys.add("wifisetup-choose")
    for st, key in (("connecting", "wifisetup-connecting"), ("ok", "wifisetup-ok"), ("failed", "wifisetup-failed")):
        if ws == st:
            keys.add(key)
    info = ctx.get("update_info") or {}
    if info.get("addon"):
        keys.add("update-addon")
    if info.get("dreampi"):
        keys.add("update-dreampi")
    for st, key in (("running", "update-running"), ("ok", "update-ok"), ("failed", "update-failed")):
        if ctx.get("update") == st:
            keys.add(key)
    if ctx.get("reboot"):
        keys.add("reboot")
    watch = ctx.get("players") or {}
    if watch.get("games"):
        keys.add("players-game")
    if watch.get("friends"):
        keys.add("players-friend")
    if ctx.get("event"):
        keys.add("event-soon")
    if any(k in keys for k in ERRORS):
        keys.add("error")
    if any(k in keys for k in WARNINGS) or ctx.get("dcnet_problem"):
        keys.add("warning")
    if "error" not in keys and "warning" not in keys and state in ("ok", "call-dcnow", "call-dcnet", "call") \
            and net.get("network") and net.get("internet") is True:
        keys.add("ok")
    return keys


def active_messages(ctx=None):
    """The looks to draw now, lowest priority first (the LED service draws them in this order, so later ones end up on top). The
    order of the groups is the priority: the top group wins. One entry per group that has an active message: key (the group's id),
    color ("#rrggbb"), effect, speed, brightness (the group's level, or the global one), leds, messages (its active message keys).
    Only the messages the enabled modules announce can be active. When nothing applies, the group with "off" gives the look."""
    ctx = ctx or gather()
    keys = active_keys(ctx) & set(m["key"] for m in messages())
    cfg = led_config()
    entries = []
    for i, g in enumerate(cfg["groups"]):
        active = [m for m in g["messages"] if m in keys]
        if active:
            entries.append((len(cfg["groups"]) - i, g, active))      # higher = more important
    if not entries:
        for g in cfg["groups"]:
            if "off" in g["messages"]:
                entries.append((0, g, ["off"]))
    out = []
    for _prio, g, active in sorted(entries, key=lambda e: e[0]):
        out.append({"key": g["id"], "colour": g["colour"], "color": resolve_colour(g["colour"], ctx["selected"]), "effect": g["effect"], "speed": g["speed"],
                    "brightness": cfg["max_brightness"] if g.get("brightness") is None else g["brightness"],
                    "leds": g["leds"], "messages": active})
    return out


def dreampi_look():
    """The look of what DreamPi is doing (not the network or Pi messages), or None."""
    looks = active_messages(gather(live=False))
    return looks[-1] if looks else None


def dreampi_dot():
    """What the status dot on the page previews: that look as the page draws it, the group's palette colour (not the LED's calibrated
    value) with its effect and speed, or None."""
    look = dreampi_look()
    return {"colour": look["colour"], "effect": look["effect"], "speed": look["speed"]} if look else None
