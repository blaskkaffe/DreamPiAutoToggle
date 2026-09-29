#!/usr/bin/env python3
# DreamPi Netswitch add-on - web page to choose DCNow! or DCNET.
# Shows DreamPi's and the modem's live status and internet access, plus an
# optional debug timeline. It only creates/removes the files that
# netswitch_hook.py reads.
# Works on Python 3 and 2.7.
import gzip
import io
import json
import os
import re
import socket
import sys
import threading
import time

import ssl
try:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from socketserver import ThreadingMixIn
except ImportError:
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
    from SocketServer import ThreadingMixIn

BASE_DIR = "/opt/dreampi-netswitch"
FLAG = os.path.join(BASE_DIR, "dcnet_mode")
AUTORESET = os.path.join(BASE_DIR, "autoreset")
DEFAULT_DCNET = os.path.join(BASE_DIR, "default_dcnet")
DEBUG_DTMF = os.path.join(BASE_DIR, "debug_dtmf")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
STATIC_FILES = {   # only these are served from /static/
    "three.min.js": "application/javascript; charset=utf-8",
    "dc-background.js": "application/javascript; charset=utf-8",
    "LICENSES.txt": "text/plain; charset=utf-8",
}
LED_CONFIG = os.path.join(BASE_DIR, "led.json")     # brightness + colours
LED_ENABLED = os.path.join(BASE_DIR, "led_enabled")  # written by install.sh --led
LED_COUNT = os.path.join(BASE_DIR, "led_count")      # number of LEDs (install.sh --leds=N)
STATUS = "/tmp/dreampi-netswitch.active"
STATE = "/tmp/dreampi-netswitch.state"
MODEM = "/tmp/dreampi-netswitch.modem"
DTMF_LOG = "/tmp/dreampi-netswitch-dtmf.log"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 80
HTTPS_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 443   # 0 = no HTTPS
CERT = os.path.join(BASE_DIR, "https.crt")   # self-signed, made by install.sh
KEY = os.path.join(BASE_DIR, "https.key")

INTERNET_EVERY = 30   # seconds between internet checks while it works
INTERNET_RETRY = 5    # ... and while it doesn't
LINK_EVERY = 2        # seconds between checks of cables / Wi-Fi / route
NET_STATE = "/tmp/dreampi-netswitch.net"   # shared with the LED service
NET_STALE = 20        # ignore NET_STATE when older than this (web service down)

_checks = {"internet": {"state": "checking", "text": "Checking...", "time": 0}}
_checks_lock = threading.Lock()


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


# ----------------------------------------------------------- internet check

def check_internet():
    """Same idea as DreamPi's own check: reach public DNS servers over TCP,
    then resolve the Dreamcast Live host name."""
    best = None
    for host in ("1.1.1.1", "8.8.8.8", "208.67.222.222"):
        start = time.time()
        try:
            s = socket.create_connection((host, 53), 3)
            s.close()
            best = int((time.time() - start) * 1000)
            break
        except Exception:
            continue
    if best is None:
        return {"state": "bad", "text": "No internet connection"}
    try:
        socket.gethostbyname("dreamcast.online")
    except Exception:
        return {"state": "warn", "text": "Connected, but DNS lookups fail"}
    return {"state": "ok", "text": "Connected (%d ms)" % best}


def _sys(iface, name):
    return read_file("/sys/class/net/%s/%s" % (iface, name))


def link_state():
    """Which links are up, and whether there is a default route.
    Ethernet: a wired interface (eth*/en*) with carrier. Wi-Fi: a wireless
    interface (wlan*/wl*) that is up, i.e. associated with a network."""
    ethernet = wifi = False
    try:
        ifaces = os.listdir("/sys/class/net")
    except OSError:
        ifaces = []
    for iface in ifaces:
        up = _sys(iface, "operstate") == "up"
        if os.path.isdir("/sys/class/net/%s/wireless" % iface) or iface.startswith(("wlan", "wl")):
            wifi = wifi or up
        elif iface.startswith(("eth", "en")):
            ethernet = ethernet or (up and _sys(iface, "carrier") == "1")
    route = False
    try:
        with open("/proc/net/route") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) > 3 and parts[1] == "00000000" and int(parts[3], 16) & 1 \
                        and not parts[0].startswith(("ppp", "tun", "lo")):
                    route = True
    except (IOError, OSError, ValueError):
        pass
    # "network" = the Pi has a default route (a router to send traffic to)
    return {"ethernet": ethernet, "wifi": wifi, "network": route}


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


def _write_net_state(data):
    tmp = NET_STATE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.rename(tmp, NET_STATE)
    except (IOError, OSError):
        pass


_net = {"links": None, "internet": {"state": "checking", "text": "Checking...", "time": 0},
        "recheck": threading.Event()}


def internet_checker():
    """Internet check: every 30 s while it works, every 5 s while it doesn't,
    and straight away when a cable or Wi-Fi connection changes."""
    while True:
        links = _net["links"]
        if links is not None and not links["network"]:
            result = {"state": "bad", "text": "No network connection"}
        else:
            result = check_internet()
        result["time"] = int(time.time())
        _net["internet"] = result
        _net["recheck"].clear()
        _net["recheck"].wait(INTERNET_EVERY if result["state"] == "ok" else INTERNET_RETRY)


def checker():
    """Cables / Wi-Fi / route every 2 s (cheap, so errors show quickly), and
    the shared state file for the LED service."""
    t = threading.Thread(target=internet_checker)
    t.daemon = True
    t.start()
    while True:
        links = link_state()
        if links != _net["links"]:           # plugged/unplugged, Wi-Fi joined/lost
            _net["links"] = links
            _net["recheck"].set()
        internet = _net["internet"]
        if not links["network"]:
            internet = {"state": "bad", "text": "No network connection", "time": int(time.time())}
        shown = dict(internet)
        if internet["state"] == "ok" and (links["ethernet"] or links["wifi"]):
            via = " and ".join(n for n, on in (("Ethernet", links["ethernet"]), ("Wi-Fi", links["wifi"])) if on)
            shown["text"] = internet["text"].replace("Connected", "Connected via " + via, 1)
        with _checks_lock:
            _checks["internet"] = shown
        _write_net_state({"ethernet": links["ethernet"], "wifi": links["wifi"],
                          "network": links["network"],
                          "internet": None if internet["state"] == "checking" else internet["state"] == "ok",
                          "time": time.time()})
        trim_log()
        time.sleep(LINK_EVERY)


# -------------------------------------------------------------------- page

# DreamPi states (as returned by dreampi_state) in the order the settings show them
# LED messages, highest priority first, with category and default look.
# Errors always have higher priority than information. The DreamPi ones come from
# dreampi_state(); the network ones from the checker (NET_STATE).
LED_STATES = [
    # key, label, category, colour, effect, speed, enabled
    ("no-network", "No network", "error", "#ff0000", "solid", "slow", True),
    ("no-internet", "No internet", "error", "#ff7a00", "blink", "slow", True),
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
PRIORITY = dict((s[0], len(LED_STATES) - i) for i, s in enumerate(LED_STATES))   # higher wins
_DEFAULT_COLOURS = dict((s[0], s[3:7]) for s in LED_STATES)
# LED effects. The first four work on a single LED; the rest need a strip.
# "rgb" ignores the colour and cycles through all colours (10 s slow, 4 s fast).
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
    """LEDs installed: 0 = no LED service, 1 = single LED, more = strip."""
    if not os.path.exists(LED_ENABLED):
        return 0
    try:
        return max(1, min(300, int((read_file(LED_COUNT) or "1").strip())))
    except ValueError:
        return 1


NETWORKS = ("dcnow", "dcnet")
_COLOUR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
try:
    _TEXT = basestring  # noqa: F821  (Python 2: json gives unicode)
except NameError:
    _TEXT = str


def default_led_config():
    return {"brightness": 0.08,
            "colours": dict((net, dict((st, {"color": c, "effect": e, "speed": sp, "brightness": None,
                                             "enabled": on, "leds": None})
                                       for st, (c, e, sp, on) in _DEFAULT_COLOURS.items()))
                            for net in NETWORKS)}


def clean_led_config(data):
    """Defaults for anything missing or invalid in data."""
    cfg = default_led_config()
    if not isinstance(data, dict):
        return cfg
    try:
        cfg["brightness"] = min(1.0, max(0.0, float(data.get("brightness", cfg["brightness"]))))
    except (TypeError, ValueError):
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


def active_messages(state=None, net_state=None):
    """Enabled LED messages that apply right now, lowest priority first (the
    LED service draws them in this order, so later ones end up on top).
    Each: key, category, color, effect, speed, brightness (effective), leds."""
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
        if net_state.get("ethernet"):
            active.append("ethernet")
        if net_state.get("wifi"):
            active.append("wifi")
    cfg = led_config()
    looks = cfg["colours"]["dcnet" if os.path.exists(FLAG) else "dcnow"]
    out = []
    for key in sorted(set(active), key=lambda k: PRIORITY.get(k, 0)):
        if key not in looks or not looks[key].get("enabled", True):
            continue
        look = dict(looks[key])
        look["key"] = key
        look["category"] = "error" if key in ("no-network", "no-internet", "off", "unknown") else "info"
        if look.get("brightness") is None:
            look["brightness"] = cfg["brightness"]
        out.append(look)
    return out


def status_look(state=None):
    """The most important active message (what a single LED shows), or None
    when every active message is switched off."""
    msgs = active_messages(state)
    return msgs[-1] if msgs else None


def api_state():
    dstate, dtext = dreampi_state()
    mtext, msince = modem_state()
    warnings = []
    problem = hook_problem()
    if problem:
        warnings.append("Add-on not active: %s. Calls are not affected until it is." % problem)
    problem = dcnet_problem()
    if problem:
        warnings.append("DCNET unavailable: %s. All calls go to DCNow!" % problem)
    with _checks_lock:
        checks = json.loads(json.dumps(_checks))
    net = network_state()
    if net and not net.get("network"):
        warnings.append("No network: the Pi has no working network connection.")
    elif net and net.get("internet") is False:
        why = "name lookups (DNS) fail" if "DNS" in checks["internet"]["text"] \
            else "the network works, but the internet can't be reached"
        warnings.append("No internet: %s. Dreamcast games can't get online right now." % why)
    return {"network": "dcnet" if os.path.exists(FLAG) else "dcnow",
            "autoreset": os.path.exists(AUTORESET),
            "default": "dcnet" if os.path.exists(DEFAULT_DCNET) else "dcnow",
            "debug": os.path.exists(DEBUG_DTMF),
            # the dot next to DreamPi previews that status's LED message only;
            # network problems show as warning boxes instead
            "dreampi": {"state": dstate, "text": dtext,
                        "look": (active_messages(dstate, {"network": True}) or [None])[-1]},
            "modem": {"text": mtext, "since": msince},
            "internet": checks["internet"],
            "warnings": warnings, "now": int(time.time())}


PAGE = u"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DreamPi</title>
<style>
 :root{--r:29px;--bw:4px;--dcnow:#e8761c;--dcnow-l:#f6b27a;--dcnet:#1c6fe8;--dcnet-l:#80b1f6;--card:#1b1b1b;--line:#2a2a2a;--muted:#999}
 *{box-sizing:border-box}
 body{font-family:-apple-system,"Segoe UI",Roboto,sans-serif;background:#111;color:#eee;max-width:460px;margin:24px auto;padding:0 16px}
 header{position:relative;margin-bottom:16px} h1{text-align:center;margin:0;font-size:1.9em}
 h2{font-size:.8em;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin:22px 4px 8px;font-weight:600}
 .card{background:var(--card);border-radius:var(--r);padding:6px 20px;margin-bottom:14px}
 .sub{color:#888;font-size:.85em} .note{color:var(--muted);font-size:.85em;margin:8px 4px} a{color:#8bf}
 button{font:inherit;cursor:pointer;border:0;color:#fff}
 .rows{cursor:pointer;user-select:none;border-radius:var(--r);border:var(--bw) solid #3a3a3a;padding:2px 20px}
 .row{display:flex;align-items:baseline;padding:11px 0;border-top:1px solid var(--line)} .row:first-child{border-top:0}
 .row .k{width:84px;color:var(--muted);flex:none} .row .v{flex:1}
 .rows .more{display:none} .rows.open .more{display:flex}
 .arrow{color:#aaa;flex:none;margin-left:8px;transition:transform .15s} .rows.open .arrow{transform:rotate(90deg)}
 .dot{display:inline-block;width:.65em;height:.65em;border-radius:50%;margin-right:8px;background:#888}
 @keyframes blink{50%{opacity:.12}} @keyframes breathe{0%,100%{opacity:.1}50%{opacity:1}}
 @keyframes rgbc{0%,100%{background:#f00}17%{background:#ff0}33%{background:#0f0}50%{background:#0ff}67%{background:#00f}83%{background:#f0f}}
 .ok{background:#2c2} .busy,.warn{background:#e0b400} .call{background:#b04cff} .bad,.off{background:#d33}
 .call-dcnow{background:#ff7a1a} .call-dcnet{background:#2a7bff}
 .warnbox{background:#7a1f1f;border:var(--bw) solid #a84a4a;padding:10px 20px;border-radius:var(--r);margin:0 0 12px;font-size:.9em}
 .now{font-size:1.3em;margin:0 0 16px;padding:14px 24px;border-radius:var(--r);text-align:center;background:#9e4f10;border:var(--bw) solid #c9793a;line-height:1.35}
 .now b{font-size:1.25em} .now.dcnet{background:#1c4f9e;border-color:#5a86cf}
 .pill{display:block;width:100%;margin:0 0 12px;padding:13px;border-radius:var(--r);font-size:1.1em;font-weight:600;letter-spacing:.02em}
 .dcnow-b{background:rgba(232,118,28,.82);border:var(--bw) solid rgba(246,178,122,.82)} .dcnet-b{background:rgba(28,111,232,.82);border:var(--bw) solid rgba(128,177,246,.82)}
 .pill:active{filter:brightness(1.1)}
 .pill-s{display:inline-block;padding:7px 16px;border-radius:999px;background:rgba(42,42,42,.82);border:var(--bw) solid rgba(80,80,80,.85);color:#eee;font-size:.88em}
 .wide{display:flex;align-items:center;justify-content:space-between;width:100%;padding:12px 20px;border-radius:var(--r);background:var(--card);border:var(--bw) solid #3a3a3a;color:#eee;font-size:1em;text-align:left}
 .wide .arrow{margin-left:8px} .wide.open .arrow{transform:rotate(90deg)}
 .bar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:20px 0 0}
 .cog{position:absolute;right:0;top:50%;transform:translateY(-50%);padding:6px;background:transparent;color:#3a3a3a;line-height:0}
 .cog svg{width:30px;height:30px;fill:currentColor;display:block} .cog:hover{color:#5a5a5a}
 #settings{display:none;position:fixed;top:0;right:0;bottom:0;left:0;background:#111;overflow:auto;z-index:10}
 #settings.open{display:block} body.settings-open{overflow:hidden}
 #settings .in{max-width:460px;margin:24px auto;padding:0 16px 40px}
 .srow{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 0;border-top:1px solid var(--line);margin:0}
 .srow:first-child{border-top:0} .srow .sub{display:block;margin-top:2px}
 .switch{position:relative;flex:none;width:104px;height:40px;padding:0;border-radius:var(--r);font-size:.8em;font-weight:bold;
         background:rgba(232,118,28,.82);border:var(--bw) solid rgba(246,178,122,.82);transition:background .2s,border-color .2s}
 .switch .knob{position:absolute;top:4px;left:68px;width:24px;height:24px;border-radius:50%;background:#fff;transition:left .2s;box-shadow:0 1px 3px rgba(0,0,0,.5)}
 .switch .lbl{position:absolute;top:0;bottom:0;left:11px;line-height:32px}
 .switch.dcnet{background:rgba(28,111,232,.82);border-color:rgba(128,177,246,.82)} .switch.dcnet .knob{left:4px} .switch.dcnet .lbl{left:auto;right:12px}
 .cbox{-webkit-appearance:none;appearance:none;flex:none;display:inline-block;width:30px;height:30px;margin:0;padding:0;border-radius:8px;
       border:var(--bw) solid #777;background:transparent center/18px no-repeat;vertical-align:middle;cursor:pointer}
 .cbox.on,.cbox:checked{background-image:url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M5 12.5l4.5 4.5L19 7.5' fill='none' stroke='white' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E\")}
 .cbox.on.dcnow,.cbox.dcnow:checked{background-color:var(--dcnow);border-color:var(--dcnow)}
 .cbox.on.dcnet,.cbox.dcnet:checked{background-color:var(--dcnet);border-color:var(--dcnet)}
 table{width:100%;border-collapse:collapse;font-size:.88em}
 td,th{padding:10px 3px;border-top:1px solid var(--line);vertical-align:top;text-align:left;font-weight:normal}
 tr:first-child td{border-top:0}
 td.n{color:#eee;white-space:nowrap;word-break:keep-all;overflow-wrap:normal;width:1%;padding-right:14px}
 .ledtab td,.ledtab th{vertical-align:middle}
 .ledtab th{color:var(--muted);font-size:.78em;border-top:0;padding:4px 3px 8px;text-align:center} .ledtab th:first-child{text-align:left}
 .ledtab tbody tr:first-child td{border-top:1px solid var(--line)}
 .ledtab td.c{width:1%;padding:8px 4px;text-align:center}
 .tabs{display:flex;gap:8px;padding:10px 0 4px} .tabs button{flex:1;padding:7px 4px;font-size:.85em}
 .tabs .sel.dcnow{background:rgba(232,118,28,.82);border-color:rgba(246,178,122,.82)} .tabs .sel.dcnet{background:rgba(28,111,232,.82);border-color:rgba(128,177,246,.82)}
 .chip{display:inline-block;height:34px;padding:0 4px;border-radius:7px;border:var(--bw) solid #555;background:transparent;color:#ccc;font-size:.72em;line-height:1.1;vertical-align:middle}
 .fx{width:74px} .fx small{display:block;color:#888;font-size:.9em} .lvl{width:52px;color:#777}
 .ledtab td.name{padding-left:0} .ledtab td.name .cbox{margin-right:8px}
 .ledtab tr.grp td{border-top:0;padding:14px 0 4px;color:var(--muted);font-size:.72em;text-transform:uppercase;letter-spacing:.08em}
 .ledtab tr.dis td:not(.name),.ledtab tr.dis .lbl-t{opacity:.35}
 .secrow{display:flex;align-items:center;gap:8px;margin-bottom:12px;flex-wrap:wrap}
 .secrow input[type=number]{width:54px;padding:5px 6px;border-radius:8px;border:var(--bw) solid #555;background:#1a1a1a;color:#eee;font:inherit;font-size:.85em}
 .lvl.on.dcnow{background:var(--dcnow);border-color:var(--dcnow);color:#fff} .lvl.on.dcnet{background:var(--dcnet);border-color:var(--dcnet);color:#fff}
 .in{position:relative}
 .pop{display:none;position:absolute;z-index:20;width:290px;padding:12px 16px;border-radius:var(--r);background:#262626;box-shadow:0 6px 24px rgba(0,0,0,.6)}
 .pop.open{display:block} .pop .t{font-size:.85em;color:#ccc;margin-bottom:8px}
 .pop .range{padding:6px 0 10px} .pop .bar{margin:0;justify-content:space-between}
 .opts{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px} .opts button{padding:6px 12px;font-size:.82em}
 .opts .sel.dcnow,.secrow .sel.dcnow{background:var(--dcnow);border-color:var(--dcnow-l)} .opts .sel.dcnet,.secrow .sel.dcnet{background:var(--dcnet);border-color:var(--dcnet-l)}
 .opts button:disabled{opacity:.35;cursor:default}
 .th-dcnow{color:var(--dcnow-l)!important} .th-dcnet{color:var(--dcnet-l)!important}
 input[type=color]{-webkit-appearance:none;appearance:none;width:34px;height:34px;padding:0;border:var(--bw) solid #555;border-radius:7px;background:none;vertical-align:middle;cursor:pointer}
 input[type=color]::-webkit-color-swatch-wrapper{padding:0} input[type=color]::-webkit-color-swatch{border:0;border-radius:4px}
 input[type=color]::-moz-color-swatch{border:0;border-radius:4px}
 .range{display:flex;align-items:center;gap:12px;padding:12px 0} .range > span:first-child{white-space:nowrap} .range input{flex:1;min-width:60px;accent-color:var(--dcnow)}
 .saved{color:#6c6;font-size:1em;text-transform:none;letter-spacing:0;margin-left:8px;opacity:0;transition:opacity .3s} .saved.show{opacity:1}
 #log{background:#0a0a0a;border:var(--bw) solid var(--line);border-radius:12px;padding:8px;font-size:11px;line-height:1.45;
      height:55vh;overflow:auto;white-space:pre-wrap;word-break:break-all;margin-top:12px}
 #log .dtmf{color:#6f6;font-weight:bold} #log .route{color:#8bf} #log .web{color:#e0b400}
 #log .modem{color:#aaa} #log .dim{color:#555} #log .err{color:#f66}
 #dcbg{display:none;position:fixed;top:0;left:0;width:100vw;height:100vh;height:100lvh;z-index:-1;overflow:hidden;pointer-events:none;
       background:linear-gradient(to bottom,#9cc3dc,#4d639c);transform:translateZ(0)}
 body.dcbg #dcbg{display:block} body.dcbg{background:transparent} html.dcbg{background:#4d639c}
 body.dcbg{--card:rgba(20,20,20,.78)} body.dcbg .rows,body.dcbg .wide{background:rgba(20,20,20,.78)}
 body.dcbg h1{text-shadow:0 1px 4px rgba(0,0,0,.6)}
 body.settings-open > :not(#settings):not(#dcbg){visibility:hidden}
 body.dcbg #settings{background:transparent}
 body.dcbg .note,body.dcbg h2{color:#eee;text-shadow:0 1px 3px rgba(0,0,0,.8)}
</style></head><body>
<div id="dcbg"></div>
<header><h1>DreamPi</h1><button class="cog" id="cog" type="button" title="Settings" aria-label="Settings"><svg viewBox="0 0 24 24" aria-hidden="true"><path fill-rule="evenodd" d="M10.3 1.5h3.4l.5 2.6a8.3 8.3 0 0 1 2.1.9l2.2-1.5 2.4 2.4-1.5 2.2c.4.7.7 1.4.9 2.1l2.6.5v3.4l-2.6.5a8.3 8.3 0 0 1-.9 2.1l1.5 2.2-2.4 2.4-2.2-1.5c-.7.4-1.4.7-2.1.9l-.5 2.6h-3.4l-.5-2.6a8.3 8.3 0 0 1-2.1-.9l-2.2 1.5-2.4-2.4 1.5-2.2a8.3 8.3 0 0 1-.9-2.1l-2.6-.5v-3.4l2.6-.5c.2-.7.5-1.4.9-2.1L3.4 5.9l2.4-2.4L8 5c.7-.4 1.4-.7 2.1-.9zM12 8.2a3.8 3.8 0 1 0 0 7.6 3.8 3.8 0 0 0 0-7.6z"/></svg></button></header>
<div id="warnings"></div>
<div class="card rows" id="rows" title="Show or hide details">
 <div class="row"><span class="k">DreamPi</span><span class="v"><span class="dot" id="d-dot"></span><span id="d-text">...</span></span><span class="arrow">&#9656;</span></div>
 <div class="row more"><span class="k">Modem</span><span class="v"><span id="m-text">...</span> <span class="sub" id="m-since"></span></span></div>
 <div class="row more"><span class="k">Internet</span><span class="v"><span class="dot" id="i-dot"></span><span id="i-text">...</span></span></div>
</div>
<div class="now" id="net">Selected network:<br><b id="net-name">...</b></div>
<form method="post" action="/dcnow"><button class="pill dcnow-b">DCNow! / DreamPi</button></form>
<form method="post" action="/dcnet"><button class="pill dcnet-b">DCNET / FLYCAST</button></form>
<div class="bar" id="debug-bar" style="display:none"><button class="wide" id="show-debug" type="button"><span>Debug log</span><span class="arrow">&#9656;</span></button></div>
<div id="debug" style="display:none">
<div class="note">Records every modem event, DreamPi message and routing decision with
millisecond timing. Turn recording on, then dial.</div>
<div class="bar" style="margin-top:6px"><form method="post" action="/debug"><button class="pill-s" id="debug-b">Recording</button></form>
<span id="log-tools" style="display:none"><form method="post" action="/clearlog" style="display:inline"><button class="pill-s">Clear</button></form>
<a class="pill-s" href="/dtmf" target="_blank" style="text-decoration:none">Newest 256 KB</a>
<a class="pill-s" href="/dtmf?all" target="_blank" style="text-decoration:none">Full log</a>
<label class="sub" style="display:inline-flex;align-items:center;gap:6px;white-space:nowrap;margin-left:4px"><input type="checkbox" class="cbox dcnow" id="follow" checked>Follow</label></span></div>
<pre id="log" style="display:none"></pre>
</div>

<div id="settings" role="dialog" aria-label="Settings"><div class="in">
<header><h1>Settings</h1><button class="cog" id="close-settings" type="button" title="Close" aria-label="Close"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5.6 3.5 12 9.9l6.4-6.4 2.1 2.1-6.4 6.4 6.4 6.4-2.1 2.1-6.4-6.4-6.4 6.4-2.1-2.1 6.4-6.4-6.4-6.4z"/></svg></button></header>
<h2>Network</h2>
<div class="card">
 <form method="post" action="/default" class="srow"><span>Default network<span class="sub">Where Auto reset goes back to</span></span>
  <button class="switch" id="default-b" type="submit"><span class="lbl" id="default-l">DCNow!</span><span class="knob"></span></button></form>
 <form method="post" action="/autoreset" class="srow"><span>Auto reset<span class="sub">Dialing 111-1111 returns to the default network</span></span>
  <button class="cbox" id="reset-b" type="submit" aria-label="Auto reset"></button></form>
 <div class="srow"><span>Debug log<span class="sub">Show the debug log on the main page (this browser only)</span></span>
  <input type="checkbox" class="cbox dcnow" id="dbg-b" aria-label="Show debug log"></div>
</div>

<h2>Phone numbers</h2>
<div class="card">
<table>
<tr><td class="n">111-1111</td><td>Always directs to DCNow! for compatibility with openMenu and standard ISP configs.<br>
<span class="sub">When &quot;Auto reset&quot; is enabled, dialing it also resets the network to the default network.<span id="reset-note"></span></span></td></tr>
<tr><td class="n">222-2222</td><td>Selects DCNow! / DreamPi and connects to it<br>
<span class="sub">Can be set in the Dreamcast ISP config to always connect to DCNow!</span></td></tr>
<tr><td class="n">333-3333</td><td>Selects DCNET / FLYCAST and connects to it<br>
<span class="sub">Can be set in the Dreamcast ISP config to always connect to DCNET.</span></td></tr>
<tr><td class="n">Any other</td><td>Connects to the currently selected network.<br>
<span class="sub">Set your Dreamcast ISP config to any 7-digit number to use this feature.</span></td></tr>
</table>
</div>

<h2>Appearance</h2>
<div class="card">
 <div class="srow"><span>Dreamcast background<span class="sub">Animated, saved in this browser only</span></span>
  <input type="checkbox" class="cbox dcnow" id="bg-b" aria-label="Dreamcast background"></div>
</div>

<div id="led-section" style="display:none;position:relative">
<h2>Status LED<span id="led-count-t"></span> <span class="saved" id="led-saved">Saved &#10003;</span></h2>
<div class="card">
 <div class="range"><span>Global brightness</span><input type="range" id="led-bright" min="0" max="1000" step="1"><span id="led-bright-v" style="width:3em;text-align:right"></span></div>
 <div class="tabs"><button class="pill-s" type="button" id="tab-dcnow">DCNow! selected</button><button class="pill-s" type="button" id="tab-dcnet">DCNET selected</button></div>
 <table class="ledtab"><thead><tr><th>Message</th><th>colour</th><th>effect</th><th>level</th></tr></thead><tbody id="led-rows"></tbody></table>
</div>
<div class="bar" style="margin-top:0"><button class="pill-s" id="led-reset" type="button">Reset LED settings to defaults</button></div>
<div class="note">The tabs choose which selected network the table is for. Tick a message to use it; the LED is off when no ticked message applies. Errors always have higher priority than information. Effect: tap to pick solid, blink, breathe, RGB or (with a strip) an animation, its speed, and with a strip which LEDs it uses (later messages in the list draw underneath earlier ones). Level: its own brightness; grey means the global brightness above. The status dot on the main page previews the most important message.</div>
<div id="fx-pop" class="pop"><div class="t" id="fx-t"></div>
 <div class="opts" id="fx-opts"></div>
 <div class="opts" id="fx-speed" style="align-items:center"><span class="sub" style="margin-right:4px">Speed</span><button class="pill-s" type="button" data-speed="slow">Slow</button><button class="pill-s" type="button" data-speed="fast">Fast</button></div>
 <div class="secrow" id="fx-sec"><span class="sub">LEDs</span>
  <button class="pill-s" type="button" id="sec-all">All</button>
  <input type="number" id="sec-a" min="1" max="300" aria-label="First LED"><span class="sub">to</span><input type="number" id="sec-b" min="1" max="300" aria-label="Last LED"></div>
 <div class="bar" style="justify-content:flex-end"><button class="pill-s" id="fx-done" type="button">Done</button></div></div>
<div id="lvl-pop" class="pop"><div class="t" id="lvl-t"></div>
 <div class="range"><input type="range" id="lvl-r" min="0" max="1000" step="1"><span id="lvl-v" style="width:3em;text-align:right"></span></div>
 <div class="bar"><button class="pill-s" id="lvl-base" type="button">Use global</button><button class="pill-s" id="lvl-done" type="button">Done</button></div></div>
</div>
</div></div>

<script>
function $(id){return document.getElementById(id)}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function ago(t,now){if(!t)return"";var s=Math.max(0,now-t);
 if(s<60)return"("+s+"s ago)";if(s<3600)return"("+Math.floor(s/60)+" min ago)";return"("+Math.floor(s/3600)+" h ago)"}
function dot(el,state){el.className="dot "+(state||"")}
// Status dot preview of the LED effect: [keyframes, slow s, fast s, timing]
var DOT_FX={blink:["blink",1,.4,"steps(1)"],breathe:["breathe",4,1.6,"ease-in-out"],rgb:["rgbc",10,4,"linear"],
 rainbow:["rgbc",10,3,"linear"],scanner:["breathe",3,1.2,"ease-in-out"],comet:["breathe",3,1.2,"ease-in-out"],
 chase:["blink",.6,.24,"steps(1)"],twinkle:["breathe",3,1.2,"ease-in-out"]};
function lookDot(el,look){if(!look){el.className="dot";el.style.background="#333";el.style.animation="none";return}
 var f=DOT_FX[look.effect];el.className="dot";el.style.background=look.color;
 el.style.animation=f?f[0]+" "+(look.speed=="fast"?f[2]:f[1])+"s "+f[3]+" infinite":"none"}
function render(d){
 $("warnings").innerHTML=d.warnings.map(function(w){return '<div class="warnbox">'+esc(w)+'</div>'}).join("");
 lookDot($("d-dot"),d.dreampi.look); $("d-text").textContent=d.dreampi.text;
 $("m-text").textContent=d.modem.text; $("m-since").textContent=ago(d.modem.since,d.now);
 dot($("i-dot"),d.internet.state); $("i-text").textContent=d.internet.text;
 $("net").className="now "+d.network; $("net-name").textContent=d.network=="dcnet"?"DCNET":"DCNow!";
 var defName=d.default=="dcnet"?"DCNET":"DCNow!";
 $("default-b").className="switch "+d.default; $("default-l").textContent=d.default=="dcnet"?"DCNET":"DCNow!";
 $("reset-b").className="cbox "+d.default+(d.autoreset?" on":"");
 $("reset-note").textContent=" (Auto reset is "+(d.autoreset?"on, default: "+defName:"off")+")";
 $("debug-b").innerHTML=(d.debug?"&#9679; Recording":"Recording off");
 $("log-tools").style.display=d.debug?"inline":"none";
 $("log").style.display=(d.debug||logSize)?"block":"none";
 debugOn=d.debug;
}
var logSize=0,debugOn=false,logBusy=false,debugOpen=false;
$("rows").onclick=function(){this.classList.toggle("open")};
function showSettings(open){$("settings").classList.toggle("open",open);
 document.body.classList.toggle("settings-open",open);if(open)loadLed()}
$("cog").onclick=function(){showSettings(true)};
$("close-settings").onclick=function(){showSettings(false)};
document.addEventListener("keydown",function(e){if(e.key=="Escape"){if(lvlCur||fxCur)closePops();else showSettings(false)}});
// Optional Dreamcast background (static/dc-background.js), remembered per browser
function bgWanted(){try{return localStorage.getItem("netswitch-bg")==="on"}catch(e){return false}}
function loadScript(src,done){var sc=document.createElement("script");sc.src=src;sc.onload=done;
 sc.onerror=function(){document.body.classList.remove("dcbg")};document.head.appendChild(sc)}
function setBg(on){
 try{localStorage.setItem("netswitch-bg",on?"on":"off")}catch(e){}
 $("bg-b").checked=on;document.body.classList.toggle("dcbg",on);document.documentElement.classList.toggle("dcbg",on);
 if(!on){if(window.DCBackground)DCBackground.stop();return}
 function go(){if(document.body.classList.contains("dcbg"))DCBackground.start($("dcbg"))}
 if(window.DCBackground)go();
 else if(window.THREE)loadScript("/static/dc-background.js",go);
 else loadScript("/static/three.min.js",function(){loadScript("/static/dc-background.js",go)})}
$("bg-b").onchange=function(){setBg(this.checked)};
if(bgWanted())setBg(true);
// Debug log menu: hidden unless switched on in settings, remembered per browser
function setDebugMenu(on){
 try{localStorage.setItem("netswitch-debug",on?"on":"off")}catch(e){}
 $("dbg-b").checked=on;$("debug-bar").style.display=on?"flex":"none";
 if(!on){debugOpen=false;$("debug").style.display="none";$("show-debug").classList.remove("open")}}
$("dbg-b").onchange=function(){setDebugMenu(this.checked)};
var led=null,ledDefaults=null,ledTimer=null,ledStates=[],ledEffects=[],ledCount=1,ledNet="dcnow";
function loadLed(){var x=new XMLHttpRequest();x.open("GET","/ledconfig",true);
 x.onload=function(){if(x.status!=200)return;var r=JSON.parse(x.responseText);
  led=r.config;ledDefaults=r.defaults;ledStates=r.states;ledEffects=r.effects;ledCount=r.count||1;
  $("led-section").style.display=r.installed?"block":"none";   // only with install.sh --led
  $("led-count-t").textContent=ledCount>1?" ("+ledCount+" LEDs)":"";
  buildLed()};x.send()}
function buildLed(){
 ["dcnow","dcnet"].forEach(function(n){$("tab-"+n).className="pill-s "+n+(n==ledNet?" sel":"")});
 var grp="";
 $("led-rows").innerHTML=ledStates.map(function(s){var st=s[0],h="";
  if(s[2]!=grp){grp=s[2];h='<tr class="grp"><td colspan="4">'+(grp=="error"?"Errors":"Information")+'</td></tr>'}
  return h+'<tr id="r-'+st+'"><td class="name"><input type="checkbox" class="cbox '+ledNet+'" id="e-'+st+'" title="Show this message" aria-label="Show '+esc(s[1])+'"><span class="lbl-t">'+esc(s[1])+'</span></td>'+
  '<td class="c"><input type="color" id="c-'+st+'" data-state="'+st+'" aria-label="Colour"></td>'+
  '<td class="c"><button type="button" class="chip fx" id="f-'+st+'" data-state="'+st+'" data-label="'+esc(s[1])+'"></button></td>'+
  '<td class="c"><button type="button" class="chip lvl" id="l-'+st+'" data-state="'+st+'" data-label="'+esc(s[1])+'"></button></td></tr>'}).join("");
 ledStates.forEach(function(s){var st=s[0];
  $("c-"+st).addEventListener("input",function(){led.colours[ledNet][st].color=this.value;saveLed()});
  $("e-"+st).onchange=function(){led.colours[ledNet][st].enabled=this.checked;showRow(st);saveLed()};
  $("f-"+st).onclick=function(e){e.stopPropagation();openFx(this)};
  $("l-"+st).onclick=function(e){e.stopPropagation();openLvl(this)}});
 showLed()}
["dcnow","dcnet"].forEach(function(n){$("tab-"+n).onclick=function(){ledNet=n;closePops();buildLed()}});
function netName(n){return n=="dcnet"?"DCNET":"DCNow!"}
function effectName(e){for(var i=0;i<ledEffects.length;i++)if(ledEffects[i][0]==e)return ledEffects[i][1];return e}
function showLed(){$("led-bright").value=brightToSlider(led.brightness);$("led-bright-v").textContent=pct(led.brightness);
 ledStates.forEach(function(s){var st=s[0],c=led.colours[ledNet][st];
  $("c-"+st).value=c.color;$("e-"+st).checked=c.enabled!==false;showRow(st);showFx(st);showLvl(st)})}
function showRow(st){$("r-"+st).className=led.colours[ledNet][st].enabled===false?"dis":""}
function showFx(st){var el=$("f-"+st);if(!el)return;var c=led.colours[ledNet][st];
 var sub=[];if(c.effect!="solid")sub.push(c.speed);if(ledCount>1&&c.leds)sub.push(c.leds[0]==c.leds[1]?"LED "+c.leds[0]:c.leds[0]+"-"+c.leds[1]);
 el.innerHTML=esc(effectName(c.effect))+(sub.length?"<small>"+sub.join(" · ")+"</small>":"")}
function showLvl(st){var el=$("l-"+st);if(!el)return;var b=led.colours[ledNet][st].brightness,own=b!==null&&b!==undefined;
 el.className="chip lvl "+ledNet+(own?" on":"");el.textContent=pct(own?b:led.brightness)}
function placePop(pop,el){var box=pop.parentNode.getBoundingClientRect(),r=el.getBoundingClientRect();
 pop.classList.add("open");
 pop.style.left=Math.min(Math.max(r.right-box.left-pop.offsetWidth,0),box.width-pop.offsetWidth)+"px";
 pop.style.top=(r.bottom-box.top+6)+"px"}
var lvlCur=null,fxCur=null;
function closePops(){$("lvl-pop").classList.remove("open");$("fx-pop").classList.remove("open");lvlCur=fxCur=null}
function openFx(el){closePops();var st=el.dataset.state,c=led.colours[ledNet][st];fxCur=st;
 $("fx-t").textContent=el.dataset.label+", "+netName(ledNet)+" selected";
 $("fx-opts").innerHTML=ledEffects.filter(function(e){return !e[2]||ledCount>1||e[0]==c.effect}).map(function(e){
  return '<button type="button" class="pill-s" data-fx="'+e[0]+'">'+esc(e[1])+'</button>'}).join("");
 Array.prototype.forEach.call($("fx-opts").querySelectorAll("button"),function(b){b.onclick=function(){c.effect=b.dataset.fx;fxMark();saveLed()}});
 $("fx-sec").style.display=ledCount>1?"flex":"none";
 $("sec-a").max=$("sec-b").max=ledCount;
 fxMark();placePop($("fx-pop"),el)}
function fxMark(){if(!fxCur)return;var c=led.colours[ledNet][fxCur],fixed=c.effect=="solid";
 Array.prototype.forEach.call($("fx-opts").querySelectorAll("button"),function(b){b.className="pill-s "+ledNet+(b.dataset.fx==c.effect?" sel":"")});
 Array.prototype.forEach.call($("fx-speed").querySelectorAll("button"),function(b){b.disabled=fixed;
  b.className="pill-s "+ledNet+(!fixed&&b.dataset.speed==c.speed?" sel":"")});
 var L=c.leds;$("sec-all").className="pill-s "+ledNet+(L?"":" sel");
 $("sec-a").value=L?L[0]:"";$("sec-b").value=L?L[1]:"";$("sec-a").placeholder="1";$("sec-b").placeholder=ledCount;
 showFx(fxCur)}
$("sec-all").onclick=function(){if(!fxCur)return;led.colours[ledNet][fxCur].leds=null;fxMark();saveLed()};
function secInput(){if(!fxCur)return;var a=parseInt($("sec-a").value,10),b=parseInt($("sec-b").value,10);
 if(isNaN(a)&&isNaN(b))return;if(isNaN(a))a=1;if(isNaN(b))b=ledCount;
 a=Math.max(1,Math.min(ledCount,a));b=Math.max(1,Math.min(ledCount,b));
 led.colours[ledNet][fxCur].leds=[Math.min(a,b),Math.max(a,b)];
 $("sec-all").className="pill-s "+ledNet;showFx(fxCur);saveLed()}
$("sec-a").onchange=$("sec-b").onchange=secInput;
Array.prototype.forEach.call($("fx-speed").querySelectorAll("button"),function(b){b.onclick=function(){
 if(!fxCur)return;led.colours[ledNet][fxCur].speed=b.dataset.speed;fxMark();saveLed()}});
$("fx-done").onclick=closePops;
function openLvl(el){closePops();var st=el.dataset.state,c=led.colours[ledNet][st];
 if(c.brightness===null||c.brightness===undefined){c.brightness=led.brightness;showLvl(st);saveLed()}
 lvlCur=st;
 $("lvl-t").textContent=el.dataset.label+", "+netName(ledNet)+" selected";
 $("lvl-r").style.accentColor=ledNet=="dcnet"?"#1c6fe8":"#e8761c";$("lvl-r").value=brightToSlider(c.brightness);$("lvl-v").textContent=pct(c.brightness);
 placePop($("lvl-pop"),el)}
$("lvl-r").oninput=function(){if(!lvlCur)return;var b=Math.round(sliderToBright(this.value)*1000)/1000;
 led.colours[ledNet][lvlCur].brightness=b;$("lvl-v").textContent=pct(b);showLvl(lvlCur);saveLed()};
$("lvl-base").onclick=function(){if(!lvlCur)return;led.colours[ledNet][lvlCur].brightness=null;showLvl(lvlCur);saveLed();closePops()};
$("lvl-done").onclick=closePops;
$("lvl-pop").onclick=$("fx-pop").onclick=function(e){e.stopPropagation()};
$("settings").addEventListener("click",function(){if(lvlCur||fxCur)closePops()});
function saveLed(){clearTimeout(ledTimer);ledTimer=setTimeout(function(){
 var x=new XMLHttpRequest();x.open("POST","/ledconfig",true);x.setRequestHeader("Content-Type","application/json");
 x.onload=function(){if(x.status!=200)return;var el=$("led-saved");el.classList.add("show");
  setTimeout(function(){el.classList.remove("show")},1200);refresh()};x.send(JSON.stringify(led))},250)}
// Logarithmic slider: the left half covers 0-9 %, where an indicator LED is most useful.
var LOG_BASE=100;
function sliderToBright(p){return (Math.pow(LOG_BASE,p/1000)-1)/(LOG_BASE-1)}
function brightToSlider(b){return Math.round(1000*Math.log(1+b*(LOG_BASE-1))/Math.log(LOG_BASE))}
function pct(b){var v=b*100;return (v<10&&v>0?v.toFixed(1):Math.round(v))+"%"}
$("led-bright").oninput=function(){led.brightness=Math.round(sliderToBright(this.value)*1000)/1000;$("led-bright-v").textContent=pct(led.brightness);
 ledStates.forEach(function(s){showLvl(s[0])});saveLed()};
$("led-reset").onclick=function(){led=JSON.parse(JSON.stringify(ledDefaults));showLed();saveLed()};
$("show-debug").onclick=function(){debugOpen=!debugOpen;
 $("debug").style.display=debugOpen?"block":"none";
 this.classList.toggle("open",debugOpen);
 if(debugOpen){pollLog();var el=$("log");el.scrollTop=el.scrollHeight}};
setDebugMenu((function(){try{return localStorage.getItem("netswitch-debug")==="on"}catch(e){return false}})());
function cls(line){
 if(/modem: DTMF/.test(line))return"dtmf";
 if(/netswitch:|add-on:/.test(line))return"route";
 if(/web page:/.test(line))return"web";
 if(/underrun/.test(line))return"dim";
 if(/fail|error|Couldn't|Unable|No carrier|NO CARRIER/i.test(line))return"err";
 if(/modem/.test(line))return"modem";
 return"";
}
function pollLog(){
 if(!debugOpen||logBusy||(!debugOn&&logSize))return; logBusy=true;
 var x=new XMLHttpRequest();x.open("GET","/log?from="+logSize,true);
 x.onload=function(){logBusy=false;if(x.status!=200)return;var r=JSON.parse(x.responseText);
  var el=$("log");if(r.reset)el.innerHTML="";
  if(r.text){var html=r.text.split(/\\r?\\n/).filter(function(l){return l.length}).map(function(l){
    return '<div class="'+cls(l)+'">'+esc(l)+'</div>'}).join("");
   el.insertAdjacentHTML("beforeend",html);
   if($("follow").checked)el.scrollTop=el.scrollHeight;}
  logSize=r.size;};
 x.onerror=function(){logBusy=false};x.send();
}
function refresh(){var x=new XMLHttpRequest();x.open("GET","/api",true);
 x.onload=function(){if(x.status==200)render(JSON.parse(x.responseText))};x.send()}
Array.prototype.forEach.call(document.forms,function(f){f.onsubmit=function(e){e.preventDefault();
 var x=new XMLHttpRequest();x.open("POST",f.getAttribute("action"),true);
 x.onload=function(){refresh();pollLog()};x.send()}});
refresh(); setInterval(refresh,1000);
pollLog(); setInterval(pollLog,700);
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def send(self, body, ctype):
        if not isinstance(body, bytes):
            body = body.encode("utf-8")
        gz = len(body) > 2000 and "gzip" in (self.headers.get("Accept-Encoding") or "")
        if gz:
            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=5) as z:
                z.write(body)
            body = buf.getvalue()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        if gz:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api":
            self.send(json.dumps(api_state()), "application/json")
        elif self.path.startswith("/log"):
            m = re.search(r"from=(-?\d+)", self.path)
            self.send(json.dumps(read_log(int(m.group(1)) if m else 0)), "application/json")
        elif self.path == "/status":
            d = api_state()
            self.send("network=%s\ndefault=%s\nautoreset=%s\ndreampi=%s\nmodem=%s\ninternet=%s\n" % (
                d["network"], d["default"], "on" if d["autoreset"] else "off", d["dreampi"]["text"],
                d["modem"]["text"], d["internet"]["text"]), "text/plain; charset=utf-8")
        elif self.path.startswith("/static/"):
            name = self.path[len("/static/"):].split("?")[0]
            try:
                if name not in STATIC_FILES:
                    raise IOError(name)
                with open(os.path.join(STATIC_DIR, name), "rb") as f:
                    body = f.read()
            except (IOError, OSError):
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", STATIC_FILES[name])
            self.send_header("Cache-Control", "max-age=86400")   # 600 KB, fetch once a day
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/ledconfig":
            self.send(json.dumps({"config": led_config(), "defaults": default_led_config(),
                                  "states": LED_STATES,
                                  "effects": EFFECTS, "count": led_count(),
                                  "installed": os.path.exists(LED_ENABLED)}), "application/json")
        elif self.path.split("?")[0] == "/dtmf":
            try:
                with open(DTMF_LOG, "rb") as f:
                    f.seek(0, 2)
                    size = f.tell()
                    full = "all" in self.path.split("?", 1)[-1] if "?" in self.path else False
                    start = 0 if full or size <= TEXT_TAIL else size - TEXT_TAIL
                    f.seek(start)
                    body = f.read()
                if start:
                    body = body[body.find(b"\n") + 1:]   # start at a whole line
            except IOError:
                body = b"No debug log yet. Switch on Recording and dial.\n"
            self.send(body, "text/plain; charset=utf-8")
        else:
            self.send(PAGE, "text/html; charset=utf-8")

    def do_POST(self):
        if self.path == "/ledconfig":
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 65536)
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                cfg = save_led_config(data)
            except (ValueError, IOError, OSError) as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(str(e).encode("utf-8"))
                return
            self.send(json.dumps(cfg), "application/json")
            return
        if self.path == "/dcnet":
            open(FLAG, "w").close()
            debug_log("web page: DCNET selected")
        elif self.path == "/dcnow":
            if os.path.exists(FLAG):
                os.remove(FLAG)
            debug_log("web page: DCNow! selected")
        elif self.path == "/default":
            if os.path.exists(DEFAULT_DCNET):
                os.remove(DEFAULT_DCNET)
                debug_log("web page: default network set to DCNow!")
            else:
                open(DEFAULT_DCNET, "w").close()
                debug_log("web page: default network set to DCNET")
        elif self.path == "/autoreset":
            if os.path.exists(AUTORESET):
                os.remove(AUTORESET)
                debug_log("web page: reset on openMenu turned off")
            else:
                open(AUTORESET, "w").close()
                debug_log("web page: reset on openMenu turned on")
        elif self.path == "/debug":
            if os.path.exists(DEBUG_DTMF):
                debug_log("web page: debug log stopped")
                os.remove(DEBUG_DTMF)
            else:
                open(DEBUG_DTMF, "w").close()
                if os.path.exists(DTMF_LOG):
                    os.remove(DTMF_LOG)  # start a fresh log
                debug_log("web page: debug log started (network: %s)" %
                          ("DCNET" if os.path.exists(FLAG) else "DCNow!"))
        elif self.path == "/clearlog":
            if os.path.exists(DTMF_LOG):
                os.remove(DTMF_LOG)
            debug_log("web page: log cleared")
        self.send_response(303)  # back to the page when JavaScript is off
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, *args):
        pass


class Server(ThreadingMixIn, HTTPServer):
    """One thread per request, so a slow client never blocks the page."""
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        pass   # dropped connections, rejected certificates, etc.


class HTTPSServer(Server):
    """Same page over HTTPS. The TLS handshake runs in the request's own
    thread, so a browser still showing the certificate warning can't stall
    other requests."""

    def __init__(self, address, handler, context):
        self.context = context
        Server.__init__(self, address, handler)

    def finish_request(self, request, client_address):
        request.settimeout(15)
        request = self.context.wrap_socket(request, server_side=True)
        Server.finish_request(self, request, client_address)


def start_https():
    if not HTTPS_PORT:
        return
    if not (os.path.exists(CERT) and os.path.exists(KEY)):
        sys.stderr.write("HTTPS off: no certificate at %s (run install.sh)\n" % CERT)
        return
    try:
        protocol = getattr(ssl, "PROTOCOL_TLS_SERVER", ssl.PROTOCOL_SSLv23)
        context = ssl.SSLContext(protocol)
        context.load_cert_chain(CERT, KEY)
        server = HTTPSServer(("", HTTPS_PORT), Handler, context)
    except Exception as e:   # port taken, bad certificate: keep plain HTTP running
        sys.stderr.write("HTTPS off: %s\n" % e)
        return
    t = threading.Thread(target=server.serve_forever)
    t.daemon = True
    t.start()


if __name__ == "__main__":
    t = threading.Thread(target=checker)
    t.daemon = True
    t.start()
    start_https()
    Server(("", PORT), Handler).serve_forever()
