# DreamPi Netswitch add-on - LED settings and what the LEDs show now.
# led.json keeps colour calibration (white balance, brightness, wire order) and the colour GROUPS: each group is one look
# (colour, effect, speed, level, which LEDs) plus the list of messages that use it. A message is something the add-on can
# tell happened (MESSAGES below: "Starting up", "No internet", "Update available" ...); active_messages() works out which
# are true right now, finds their groups and gives the looks the LED service draws.
# Also: LED count / output pin and the white-balance test flag. Shared by the web page and the LED service. Works on Python 3 and 2.7.
import json
import re
import os
import time

import netswitch_core as core

# -------------------------------------------------------------------- the messages
CATEGORIES = [   # key, heading (the order the page lists them in)
    ("dreampi", "DreamPi"),
    ("calls", "Calls"),
    ("selection", "Network selection"),
    ("connection", "Connection and link"),
    ("modem", "Modem"),
    ("pi", "Raspberry Pi health"),
    ("wifisetup", "Wi-Fi setup"),
    ("addon", "The add-on"),
    ("players", "Online players"),
    ("general", "General"),
]
# key, label (the short name shown as a tag), category, what it means, detected.
# detected False = the page can offer it, but nothing tells the add-on yet when it happens, so it never lights (not faked).
MESSAGES = [
    ("busy", "Starting up", "dreampi", "DreamPi is starting and does not answer calls yet.", True),
    ("ready-dcnow", "Ready for calls, DCNow!", "dreampi", "DreamPi is waiting for the Dreamcast to dial and DCNow! is the selected network.", True),
    ("ready-dcnet", "Ready for calls, DCNET", "dreampi", "DreamPi is waiting for the Dreamcast to dial and DCNET is the selected network.", True),
    ("notrunning", "DreamPi not running", "dreampi", "DreamPi has stopped or crashed.", True),
    ("unknown", "State unknown", "dreampi", "The add-on cannot tell what DreamPi is doing: its state file is missing or out of date, for example just after DreamPi restarted or while the add-on is not loaded in it. Best used as a last resort (a dim colour, say).", True),
    ("call-dcnow", "In a call, DCNow!", "calls", "A call is connected through DCNow!.", True),
    ("call-dcnet", "In a call, DCNET", "calls", "A call is connected through DCNET.", True),
    ("call-other", "In a call, Netlink or other", "calls", "A call that is neither DCNow! nor DCNET (Netlink, XBAND and so on).", True),
    ("sel-dcnow", "DCNow! selected", "selection", "DCNow! is the selected network.", True),
    ("sel-dcnet", "DCNET selected", "selection", "DCNET is the selected network.", True),
    ("no-ip", "No IP address yet", "connection", "The cable or Wi-Fi is connected, but the Pi has no address from the router yet (DHCP pending).", True),
    ("no-network", "No network", "connection", "The Pi has no route to the router: a cable is unplugged or Wi-Fi is not connected.", True),
    ("no-internet", "No internet", "connection", "The Pi reaches the router, but not the internet.", True),
    ("internet-ok", "Internet OK", "connection", "The Pi can reach the internet.", True),
    ("dns-fail", "DNS failing", "connection", "The internet answers, but name lookups (DNS) fail.", True),
    ("ethernet", "Ethernet connected", "connection", "A network cable is connected.", True),
    ("wifi", "Wi-Fi connected", "connection", "The Pi is connected to a Wi-Fi network.", True),
    ("wifi-weak", "Weak Wi-Fi signal", "connection", "The Wi-Fi signal is weak (-75 dBm or less).", True),
    ("net-slow", "Slow connection", "connection", "High latency or packet loss to the internet (an average of 200 ms or more, or 10 % of the packets lost). Measured with ping every 30 seconds.", True),
    ("modem-ok", "Modem plugged in", "modem", "The modem's USB serial port is there.", True),
    ("modem-missing", "Modem missing", "modem", "The modem is unplugged or its USB serial port is gone.", True),
    ("undervoltage", "Under-voltage", "pi", "The Pi is getting too little power right now.", True),
    ("throttled", "Throttled", "pi", "The Pi is slowing itself down right now (power or heat).", True),
    ("hot", u"Over 80 \u00b0C", "pi", u"The Pi is 80 \u00b0C or hotter.", True),
    ("warm", u"70 \u00b0C or warmer", "pi", u"The Pi is 70 \u00b0C or warmer (also true above 80 \u00b0C).", True),
    ("wifisetup-scan", "Scanning or hosting", "wifisetup", "Wi-Fi setup is looking for networks or hosting its own.", True),
    ("wifisetup-choose", "Choose a network", "wifisetup", "Wi-Fi setup is waiting for you to pick a network.", True),
    ("wifisetup-connecting", "Connecting", "wifisetup", "Wi-Fi setup is connecting to the network you picked.", True),
    ("wifisetup-ok", "Connected", "wifisetup", "Wi-Fi setup connected to the network.", True),
    ("wifisetup-failed", "Could not connect", "wifisetup", "Wi-Fi setup could not connect.", True),
    ("update-addon", "Add-on update available", "addon", "A newer version of this add-on is on GitHub.", True),
    ("update-dreampi", "DreamPi update available", "addon", "DreamPi has newer scripts than the Pi has.", True),
    ("update-running", "Update running", "addon", "An update of the add-on is in progress.", True),
    ("update-ok", "Update done", "addon", "The add-on was updated (for 10 minutes afterwards).", True),
    ("update-failed", "Update failed", "addon", "The update of the add-on failed (for 10 minutes afterwards).", True),
    ("reboot", "About to reboot", "addon", "A reboot was requested; the Pi goes down in a moment.", True),
    ("players-game", "Your game is played", "players", "Others are playing your game. Needs a game name set up first; nothing detects it yet.", False),
    ("players-friend", "A friend came online", "players", "A watched player came online. Needs a friends list; nothing detects it yet.", False),
    ("ok", "Everything OK", "general", "No error and no warning: DreamPi is ready or in a call, and the network and internet work.", True),
    ("error", "Error", "general", u"Anything critical: DreamPi not running, no network, no internet, under-voltage, over 80 \u00b0C or the modem missing.", True),
    ("warning", "Warning", "general", "Any warning or important information: DNS failing, slow connection, weak Wi-Fi, no IP address yet, throttled or warm, DCNET unavailable, a failed update, a failed Wi-Fi setup, an update available.", True),
    ("off", "Off (nothing else applies)", "general", "Used when no other message is showing. Leave it out for dark LEDs, or give it a very dim colour.", True),
]
MESSAGE = dict((m[0], m) for m in MESSAGES)
ERRORS = ("notrunning", "no-network", "no-internet", "undervoltage", "hot", "modem-missing")
WARNINGS = ("dns-fail", "net-slow", "wifi-weak", "no-ip", "throttled", "warm", "wifisetup-failed", "update-failed", "update-addon", "update-dreampi")
# What wins when several messages apply at once on the same LEDs, most important first: a reboot, Wi-Fi setup, an update,
# then errors, warnings, what DreamPi is doing, plain information. "off" is not in the list: it only applies when nothing else does.
PRIORITY_ORDER = [
    "reboot",
    "wifisetup-failed", "wifisetup-ok", "wifisetup-connecting", "wifisetup-choose", "wifisetup-scan",
    "update-failed", "update-ok", "update-running",
    "error",
    "notrunning", "undervoltage", "hot", "modem-missing", "no-ip", "no-network", "no-internet",
    "warning",
    "dns-fail", "net-slow", "throttled", "wifi-weak", "warm",
    "busy",
    "call-dcnow", "call-dcnet", "call-other",
    "update-addon", "update-dreampi",
    "players-friend", "players-game",
    "ready-dcnow", "ready-dcnet", "sel-dcnow", "sel-dcnet",
    "ethernet", "wifi", "internet-ok", "modem-ok",
    "ok", "unknown",
]
# a message an older led.json has, as the messages that replaced it
OLD_KEYS = {"ready": ["ready-dcnow", "ready-dcnet"]}
PRIORITY = dict((k, len(PRIORITY_ORDER) - i) for i, k in enumerate(PRIORITY_ORDER))   # higher = more important

# -------------------------------------------------------------------- the looks (groups)
# A group's colour is a palette id (core.PALETTE, the LED value of it), or a token that follows the networks' global colours:
# "dcnow", "dcnet" (what the network switcher gave them) or "network" (the colour of whichever network is selected).
COLOUR_TOKENS = [("dcnow", "DCNow!"), ("dcnet", "DCNET"), ("network", "Selected network")]
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
    """The looks the add-on starts with: the networks' colours for their selection and calls, purple for other calls, the network
    colour while ready (each network has its own message), yellow blinking while starting and red blinking when DreamPi is not running. Everything else is optional:
    add it to a group on the page."""
    return [
        _group("g1", "dcnow", "solid", "slow", ["sel-dcnow", "ready-dcnow", "call-dcnow"]),
        _group("g2", "dcnet", "solid", "slow", ["sel-dcnet", "ready-dcnet", "call-dcnet"]),
        _group("g3", "purple", "solid", "slow", ["call-other"]),
        _group("g4", "yellow", "blink", "slow", ["busy"]),
        _group("g5", "red", "blink", "slow", ["notrunning"]),
    ]


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


def _valid_colour(c):
    return isinstance(c, _TEXT) and (c in TOKEN_IDS or c in core.PALETTE_IDS)


def clean_groups(data):
    """The saved groups made safe: at most MAX_GROUPS, unique ids, a valid colour / effect / speed / level / LED range, and each
    known message in at most one group (the first that has it). Returns None when data isn't a list."""
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
        group = _group(str(gid), str(g["colour"]) if _valid_colour(g.get("colour")) else "orange",
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
            if key in MESSAGE and key not in seen_msgs:
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
        cfg["groups"] = groups
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


def colour_choices():
    """What a group's colour can be, for the page: the palette (id, name, page colour) and the network tokens."""
    return {"palette": [{"id": c["id"], "name": c["name"], "ui": c["ui"], "ui_l": c["ui_l"]} for c in core.colours()],
            "tokens": [{"id": t[0], "name": t[1]} for t in COLOUR_TOKENS]}


def resolve_colour(colour, selected="dcnow"):
    """The LED colour ("#rrggbb", as the LED shows it) of a group's colour: a palette id, or a network token."""
    if colour == "network":
        colour = selected
    if colour in ("dcnow", "dcnet"):
        return core.network_colour(colour)["led"]
    return core.colour(colour)["led"]


WB_TEST_STALE = 3   # seconds; a closed/crashed tab stops driving the LED after this


def _wb_test_file():
    """(time, colour) written by the page while a test is open: white for the white balance, or the colour being calibrated."""
    raw = (core.read_file(core.WB_TEST) or "").split()
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
    tmp = core.WB_TEST + ".tmp"
    with open(tmp, "w") as f:
        f.write("%f %s" % (time.time(), colour if isinstance(colour, _TEXT) and re.match(r"^#[0-9a-fA-F]{6}$", colour) else "#ffffff"))
    os.rename(tmp, core.WB_TEST)


def clear_wb_test():
    try:
        os.remove(core.WB_TEST)
    except OSError:
        pass


# -------------------------------------------------------------------- what is true right now
def gather(live=True):
    """What the messages are made from, read from the files the other services write. live=False is only what DreamPi is doing and
    which network is selected (the status dot's preview)."""
    ctx = {"state": core.dreampi_state()[0], "selected": "dcnet" if os.path.exists(core.FLAG) else "dcnow",
           "net": {}, "wifi": "idle", "update": "idle", "update_info": {}, "reboot": False, "dcnet_problem": False}
    if live:
        ctx.update(net=core.network_state() or {}, wifi=core.wifi_state().get("state", "idle"), update=core.update_status(),
                   update_info=core.update_info(), reboot=core.reboot_pending(), dcnet_problem=bool(core.dcnet_problem()))
    return ctx


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
    if any(k in keys for k in ERRORS):
        keys.add("error")
    if any(k in keys for k in WARNINGS) or ctx.get("dcnet_problem"):
        keys.add("warning")
    if "error" not in keys and "warning" not in keys and state in ("ok", "call-dcnow", "call-dcnet", "call") \
            and net.get("network") and net.get("internet") is True:
        keys.add("ok")
    return keys


def active_messages(ctx=None):
    """The looks to draw now, lowest priority first (the LED service draws them in this order, so later ones end up on top). One
    entry per group that has an active message: key (the group's id), color ("#rrggbb"), effect, speed, brightness (the group's
    level, or the global one), leds, messages (its active message keys). When nothing applies, the group with "off" gives the look."""
    ctx = ctx or gather()
    keys = active_keys(ctx)
    cfg = led_config()
    entries = []
    for g in cfg["groups"]:
        active = [m for m in g["messages"] if m in keys]
        if active:
            entries.append((max(PRIORITY.get(m, 0) for m in active), g, active))
    if not entries:
        for g in cfg["groups"]:
            if "off" in g["messages"]:
                entries.append((0, g, ["off"]))
    out = []
    for _prio, g, active in sorted(entries, key=lambda e: e[0]):
        out.append({"key": g["id"], "color": resolve_colour(g["colour"], ctx["selected"]), "effect": g["effect"], "speed": g["speed"],
                    "brightness": cfg["max_brightness"] if g.get("brightness") is None else g["brightness"],
                    "leds": g["leds"], "messages": active})
    return out


def dreampi_look():
    """What the status dot on the page previews: the look of what DreamPi is doing (not the network or Pi messages), or None."""
    looks = active_messages(gather(live=False))
    return looks[-1] if looks else None
