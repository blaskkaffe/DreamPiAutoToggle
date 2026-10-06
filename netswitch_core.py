# Check-in add-on - shared state and settings.
# Everything the web service and the modules read or write: file paths, the module state, the colour palette, the time
# zone and the Wi-Fi setup state files. No server, no probing, so small services can import it cheaply. Python 3.
import json
import os
import re
import sys
import time

BASE_DIR = "/opt/dreampi-netswitch"
PALETTE_FILE = os.path.join(BASE_DIR, "palette.json")             # {"red": {"ui": "#rrggbb", "led": "#rrggbb"}}: palette colours the user changed (on screen, on the LED)
MODULE_TINTS = os.path.join(BASE_DIR, "tints.json")               # {"clock": {"clock": false}}: colours whose background is neutral instead of coloured
MODULE_COLOURS = os.path.join(BASE_DIR, "colours.json")          # {"checkin": {"checkin": "green", ...}}: the global-palette colours each module uses
MODULE_ORDER = os.path.join(BASE_DIR, "module_order.json")      # ["switcher", "numbers", ...]: the order set in the module picker (top = first, wins)
ADDON_COMMIT = os.path.join(BASE_DIR, "version_commit")  # full commit hash of the checkout that was installed (install.sh)
ADDON_SRC = os.path.join(BASE_DIR, "src_dir")            # that checkout's folder, used by the web update
INSTALL_PORTS = os.path.join(BASE_DIR, "install_ports")  # "<http port> <https port>", so an update keeps them
UPDATE_ORIGIN = os.path.join(BASE_DIR, "update_origin")  # the checkout's git origin URL when installed; "Update now" refuses another one
ADMIN_PIN = os.path.join(BASE_DIR, "admin_pin")          # salted hash of the optional PIN for update/restart/Wi-Fi (install.sh --pin)
ALLOWED_HOSTS = os.path.join(BASE_DIR, "allowed_hosts")  # extra host names the web page answers to, one per line
UPDATE_STATUS = "/tmp/dreampi-netswitch.update"          # running / ok / failed, written by the update script
UPDATE_LOG = "/tmp/dreampi-netswitch.update.log"
HIGHLIGHT = os.path.join(BASE_DIR, "highlight")     # "rainbow" or a palette id: how a highlighted box looks (Settings > Appearance)
CONTACTS = os.path.join(BASE_DIR, "contacts.json")     # {"people": [{id, name, department, role, phone, location, restrictToLocation, active, order}]}: the contacts module's roster (imported from a CSV)
PHOTOS_DIR = os.path.join(BASE_DIR, "photos")           # <person id>.jpg / .png: the small profile photos (uploaded from the status menu, written by the contacts module, read by the check-in board)
CHECKIN = os.path.join(BASE_DIR, "checkin.json")       # {"rev", "config", "statuses", "people": {id: {in, status, detail, at}}}: the check-in module's live state, shared by every screen
CLOCK_CONFIG = os.path.join(BASE_DIR, "clock.json")  # {"format": "24h"|"12h"|"12h-ampm", "beat": bool, "world": bool, "large": bool, "cities": [...]}: the clock module's settings
TIME_ZONE = os.path.join(BASE_DIR, "time_zone")      # the time zone every module may show times in: an IANA name, or empty / missing = the Pi's own (Settings > About)
# Wi-Fi setup (the wifi module, install.sh --wifi)
WIFI_DEMO = os.path.join(BASE_DIR, "wifi_demo")        # exists = Wi-Fi setup runs on dummy networks (install.sh --wifi-demo)
WIFI_START = os.path.join(BASE_DIR, "wifi_start")   # touched to ask the Wi-Fi service to start
WIFI_STOP = os.path.join(BASE_DIR, "wifi_stop")     # touched to ask it to stop / cancel
WIFI_CONNECT = os.path.join(BASE_DIR, "wifi_connect")   # {"ssid":..., "password":...}, an alternative
                                                         # to the setup access point's own /connect -
                                                         # lets the regular page pick a network too,
                                                         # useful when it's reachable some other way
                                                         # (e.g. Ethernet) while Wi-Fi is being set up
WIFI_STATE = "/tmp/dreampi-netswitch.wifi"          # written by the Wi-Fi service
WIFI_STALE = 30       # ignore WIFI_STATE when older than this (the service is down)
WIFI_AP_SSID = "CheckIn WiFi Config"


# ------------------------------------------------------------------ modules
# Everything the page shows is a module: a folder in modules/ with a module.json (and a layout.json, see
# netswitch_modules.py). module.json holds
#   "name"         the title in the module picker                 (older files: "title")
#   "description"  the text under it in the picker
#   "enabled"      on by default when it is first loaded           (older files: "default"); the picker's own choice
#                  (modules.json) overrides it
#   "visible"      false = not in the picker and always on (the system / About module, say)   (default true)
#   optional: "web" (Python entry for the web service), "ui" (page kit version), "order" (where it starts out in the
#   list), "colours" / "primary" (see the colour section below)
# A module is *installed* when its folder is there and *enabled* when it is on in the picker. Its place in the picker
# (module_order.json) is its priority: the first one shows first and wins where two modules want the same thing.
# Everything that has to know - the web service and the services of the modules - asks here.
MODULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules")
MODULES_STATE = os.path.join(BASE_DIR, "modules.json")     # {"led": true, "wifi": false, ...} set from the module picker


_manifests = {}     # path -> (mtime, parsed): module.json is asked for many times a second, it changes almost never


def module_manifest(name):
    """The module's module.json as a dict, or None when it isn't installed."""
    if not re.match(r"^[a-z][a-z0-9_]*$", name or ""):
        return None
    path = os.path.join(MODULES_DIR, name, "module.json")
    try:
        mtime = os.path.getmtime(path)
        cached = _manifests.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        with open(path) as f:
            data = json.load(f)
        data = data if isinstance(data, dict) else None
        _manifests[path] = (mtime, data)
        return data
    except (IOError, OSError, ValueError):
        return None


def module_title(name, manifest=None):
    m = manifest if manifest is not None else (module_manifest(name) or {})
    return str(m.get("name") or m.get("title") or name)


def module_visible(name, manifest=None):
    """False for a module that is not in the picker (and so can't be switched off)."""
    m = manifest if manifest is not None else (module_manifest(name) or {})
    return m.get("visible", True) is not False


def module_default_enabled(manifest):
    return bool(manifest.get("enabled", manifest.get("default", True)))


def saved_module_order():
    try:
        with open(MODULE_ORDER) as f:
            data = json.load(f)
        return [n for n in data if isinstance(n, type(u""))] if isinstance(data, list) else []
    except (IOError, OSError, ValueError):
        return []


def module_names():
    """Names of the installed modules (folders with a readable module.json), in picker order: the order the user set
    (module_order.json) first, then any module not in it by its manifest's "order" hint and name."""
    try:
        names = [n for n in os.listdir(MODULES_DIR) if module_manifest(n)]
    except OSError:
        return []
    saved = [n for n in saved_module_order() if n in names]
    rest = sorted((n for n in names if n not in saved), key=lambda n: (module_manifest(n).get("order", 100), n))
    return saved + rest


def save_module_order(order):
    """Remember the picker order: a list of module names (unknown ones are dropped, missing ones keep their place at
    the end). Returns the new order, or None when the input is not a list of names."""
    if not isinstance(order, list) or not all(isinstance(n, type(u"")) for n in order):
        return None
    names = module_names()
    new = [n for n in order if n in names]
    new += [n for n in names if n not in new]
    tmp = MODULE_ORDER + ".tmp"
    with open(tmp, "w") as f:
        json.dump(new, f)
    os.rename(tmp, MODULE_ORDER)
    return new


def modules_state():
    try:
        with open(MODULES_STATE) as f:
            data = json.load(f)
        return dict((k, v) for k, v in data.items() if isinstance(v, bool)) if isinstance(data, dict) else {}
    except (IOError, OSError, ValueError):
        return {}


def module_enabled(name, state=None):
    """Installed and switched on (a module that is not visible in the picker is always on).
    state: modules_state() already read (saves a file read per module)."""
    manifest = module_manifest(name)
    if manifest is None:
        return False
    if not module_visible(name, manifest):
        return True
    state = modules_state() if state is None else state
    return state.get(name, module_default_enabled(manifest))


def save_module_enabled(name, on):
    """Switch a module on or off from the module picker. False when it isn't installed or can't be switched."""
    manifest = module_manifest(name)
    if manifest is None or not module_visible(name, manifest):
        return False
    state = modules_state()
    state[name] = bool(on)
    tmp = MODULES_STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    os.rename(tmp, MODULES_STATE)
    return True


# ---------------------------------------------------------------- colours
# The page's colours: one global palette of 16 named colours (8 hues, each normal and bright, like a terminal's 16),
# defined only here. A module never writes a colour of its own; it names one from the palette by its id ("orange",
# "bright-blue" ...), either in module.json  "colours": {"checkin": "green", ...}  (the user can change these in the
# module's own settings, see module_colour()) or as its  "primary"  colour, the one used on its borders and buttons.
# id, name, hue group, page colour, its lighter variant (borders, text), LED colour (the LED's own tuning: a screen
# colour looks different lit on a strip of LEDs; no module uses it at the moment).
# "global" is not a fixed colour: Global main, one colour the user picks in Appearance, for boxes that should share it.
PALETTE = (
    ("global", "Global main", "global", "#6f7d99", "#b0b7c7", "#8090ff"),
    ("red", "Red", "red", "#d9363e", "#ef8a8f", "#ff0000"),
    ("orange", "Orange", "orange", "#e8761c", "#f6b27a", "#ff8c00"),
    ("yellow", "Yellow", "yellow", "#d9a900", "#f0d36a", "#ffd000"),
    ("green", "Green", "green", "#2fa84f", "#8ed9a4", "#00ff00"),
    ("cyan", "Cyan", "cyan", "#1fb5c9", "#7fdbe6", "#00c8ff"),
    ("blue", "Blue", "blue", "#1c6fe8", "#80b1f6", "#0046ff"),
    ("purple", "Purple", "purple", "#8a4fd6", "#bf9ae8", "#aa00ff"),
    ("teal", "Teal", "cyan", "#17a398", "#7fd9d0", "#00d0a0"),
    ("white", "White", "white", "#b8bec9", "#e6e9ee", "#ffffff"),
    ("bright-red", "Bright red", "red", "#ff5a5f", "#ffa6a9", "#ff5050"),
    ("bright-green", "Bright green", "green", "#4cd964", "#a6efb6", "#50ff70"),
    ("bright-cyan", "Bright cyan", "cyan", "#3de0f5", "#9aeefa", "#70e0ff"),
    ("bright-blue", "Bright blue", "blue", "#4a90ff", "#9fc4ff", "#5080ff"),
    ("bright-purple", "Bright purple", "purple", "#b070ff", "#d3b0ff", "#cc66ff"),
    ("bright-pink", "Bright pink", "pink", "#ff6ab8", "#ffaad6", "#ff70b0"),
)
PALETTE_IDS = tuple(c[0] for c in PALETTE)
# colours that were in the palette once: what a saved choice of them becomes
LEGACY_COLOURS = {"bright-orange": "orange", "bright-yellow": "yellow", "pink": "bright-pink"}
DEFAULT_COLOUR = "orange"


_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
try:
    _STR = basestring  # noqa: F821  (Python 2: json gives unicode)
except NameError:
    _STR = str


def lighter(ui, share=0.45):
    """The lighter variant of a page colour (borders, text): the colour mixed with white."""
    return "#%02x%02x%02x" % tuple(int(round(int(ui[i:i + 2], 16) + (255 - int(ui[i:i + 2], 16)) * share)) for i in (1, 3, 5))


def palette_overrides():
    """{id: {"ui": "#rrggbb", "led": "#rrggbb"}}: what the user changed in the palette editor (only valid entries)."""
    try:
        with open(PALETTE_FILE) as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        return {}
    out = {}
    for ident, v in (data.items() if isinstance(data, dict) else []):
        if ident in PALETTE_IDS and isinstance(v, dict):
            keep = dict((k, str(v[k]).lower()) for k in ("ui", "led") if isinstance(v.get(k), _STR) and _HEX.match(v[k]))
            if keep:
                out[ident] = keep
    return out


def colours():
    """The palette as dicts: id, name, group, ui, ui_l, led, and the defaults (ui_default, led_default) as the add-on ships them."""
    over, out = palette_overrides(), []
    for c in PALETTE:
        o = over.get(c[0], {})
        ui = o.get("ui", c[3])
        out.append({"id": c[0], "name": c[1], "group": c[2], "ui": ui, "ui_l": lighter(ui) if "ui" in o else c[4],
                    "led": o.get("led", c[5]), "ui_default": c[3], "led_default": c[5]})
    return out


def set_palette_colour(ident, ui=None, led=None):
    """Change a palette colour on screen (ui) and / or on the LED (led), "#rrggbb". A value equal to the default is not kept.
    Returns False for an unknown id or a value that is not a colour."""
    if ident not in PALETTE_IDS or any(v is not None and not (isinstance(v, _STR) and _HEX.match(v)) for v in (ui, led)):
        return False
    base = [c for c in PALETTE if c[0] == ident][0]
    over = palette_overrides()
    entry = over.get(ident, {})
    for key, value, default in (("ui", ui, base[3]), ("led", led, base[5])):
        if value is None:
            continue
        if value.lower() == default.lower():
            entry.pop(key, None)
        else:
            entry[key] = value.lower()
    if entry:
        over[ident] = entry
    else:
        over.pop(ident, None)
    _write_palette(over)
    return True


def reset_palette(ident=None):
    """Put one palette colour (or all of them) back to the shipped values."""
    over = palette_overrides()
    if ident is None:
        over = {}
    else:
        over.pop(ident, None)
    _write_palette(over)


def _write_palette(over):
    tmp = PALETTE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(over, f)
    os.rename(tmp, PALETTE_FILE)


def colour(ident):
    """One palette entry as a dict (orange when the id is unknown)."""
    ident = LEGACY_COLOURS.get(ident, ident)
    for c in colours():
        if c["id"] == ident:
            return c
    return colour(DEFAULT_COLOUR)


def colours_css():
    """CSS for the palette: --c-<id>, --c-<id>-l and their -rgb triples on :root, and a class  .c-<id>  that makes
    an element (and what is inside it) use that colour as its --primary. The page's own :root has the defaults."""
    def rgb(h):
        return "%d,%d,%d" % (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))
    root, classes = ":root{", ""
    for c in colours():
        i = c["id"]
        root += "--c-%s:%s;--c-%s-l:%s;--c-%s-rgb:%s;--c-%s-l-rgb:%s;" % (i, c["ui"], i, c["ui_l"], i, rgb(c["ui"]), i, rgb(c["ui_l"]))
        classes += ".c-%s{--primary:var(--c-%s);--primary-l:var(--c-%s-l);--primary-rgb:var(--c-%s-rgb);--primary-l-rgb:var(--c-%s-l-rgb)}\n" % (i, i, i, i, i)
    return root + "}\n" + classes


def _saved_module_colours():
    try:
        with open(MODULE_COLOURS) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (IOError, OSError, ValueError):
        return {}


def module_colours(name):
    """{key: palette id} for a module: the defaults from its manifest "colours", with the user's picks over them.
    A module that asks for unique colours (manifest "colours_unique": true) never gets two keys with one colour."""
    manifest = module_manifest(name) or {}
    wanted = manifest.get("colours")
    if not isinstance(wanted, dict):
        return {}
    def ok(k, v):
        return LEGACY_COLOURS.get(v, v) in PALETTE_IDS
    out = dict((k, LEGACY_COLOURS.get(v, v) if ok(k, v) else DEFAULT_COLOUR) for k, v in wanted.items())
    mine = _saved_module_colours().get(name)
    if isinstance(mine, dict):
        for k in out:
            if ok(k, mine.get(k)):
                out[k] = LEGACY_COLOURS.get(mine[k], mine[k])
    if manifest.get("colours_unique"):
        if len(set(out.values())) < len(out):
            for k in out:
                out[k] = LEGACY_COLOURS.get(wanted[k], wanted[k]) if ok(k, wanted[k]) else DEFAULT_COLOUR
    return out


# ---- highlight: a module can ask for one of its dashboard boxes to stand out for a while (an event starts soon, say): /api
# "highlight" {box id: why}. A neutral box turns its own colour; a coloured box takes the highlight look
# set here, the same for every module: an animated rainbow edge or one palette colour that glows.
HIGHLIGHT_STYLES = ("rainbow",) + PALETTE_IDS
DEFAULT_HIGHLIGHT = "rainbow"


def highlight_style():
    s = (read_file(HIGHLIGHT) or "").strip()
    return s if s in HIGHLIGHT_STYLES else DEFAULT_HIGHLIGHT


def save_highlight_style(value):
    value = str(value or "").strip()
    if value not in HIGHLIGHT_STYLES:
        value = DEFAULT_HIGHLIGHT
    tmp = HIGHLIGHT + ".tmp"
    with open(tmp, "w") as f:
        f.write(value)
    os.rename(tmp, HIGHLIGHT)
    return value


def set_module_colour(name, key, ident):
    """The user gives one of the module's colour keys a palette colour. With "colours_unique", the key that had that
    colour gets the old one (a swap), so they never match. Returns the module's new {key: id}, or None when the
    module, key or colour is unknown."""
    cur = module_colours(name)
    ident = LEGACY_COLOURS.get(ident, ident)
    if key not in cur or ident not in PALETTE_IDS:
        return None
    if (module_manifest(name) or {}).get("colours_unique"):
        for k, v in list(cur.items()):
            if k != key and v == ident:
                cur[k] = cur[key]
    cur[key] = ident
    data = _saved_module_colours()
    data[name] = cur
    tmp = MODULE_COLOURS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, sort_keys=True)
    os.rename(tmp, MODULE_COLOURS)
    return cur


def module_tints(name):
    """{colour key: True | False} for a module: whether the background of what has that colour is highlighted, i.e. coloured (True) or
    neutral (False). The default is the module's manifest "tints" ({"clock": false}); anything it does not name is highlighted
    (the buttons and similar), the boxes on the main page start neutral."""
    manifest = module_manifest(name) or {}
    defaults = manifest.get("tints") if isinstance(manifest.get("tints"), dict) else {}
    try:
        with open(MODULE_TINTS) as f:
            saved = json.load(f).get(name)
    except (IOError, OSError, ValueError, AttributeError):
        saved = None
    saved = saved if isinstance(saved, dict) else {}
    return dict((k, saved[k] if isinstance(saved.get(k), bool) else defaults.get(k) is not False) for k in module_colours(name))


def set_module_tint(name, key, coloured):
    """The user turns the highlight (a coloured background) of one of the module's colours on or off. Returns the module's
    {key: bool}, or None for an unknown module or key."""
    if key not in module_colours(name) or not isinstance(coloured, bool):
        return None
    try:
        with open(MODULE_TINTS) as f:
            data = json.load(f)
        data = data if isinstance(data, dict) else {}
    except (IOError, OSError, ValueError):
        data = {}
    mine = data.get(name) if isinstance(data.get(name), dict) else {}
    default = ((module_manifest(name) or {}).get("tints") or {}).get(key) is not False
    if coloured == default:
        mine.pop(key, None)                  # only what differs from the default is kept
    else:
        mine[key] = coloured
    data[name] = mine
    tmp = MODULE_TINTS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, sort_keys=True)
    os.rename(tmp, MODULE_TINTS)
    return module_tints(name)


def time_zone():
    """The common time zone setting: an IANA name from netswitch_tz.ZONE_CHOICES, or "" = the Pi's own. Any module that shows a
    time of day reads it here (the clock does; the events module still has a zone of its own). Older installs kept it in clock.json."""
    import netswitch_tz as tz
    zone = read_file(TIME_ZONE)
    if zone is None:
        try:
            with open(CLOCK_CONFIG) as f:
                zone = json.load(f).get("zone")
        except (IOError, OSError, ValueError, AttributeError):
            zone = ""
    return zone if zone in tz.ZONE_CHOICES else ""


def save_time_zone(value):
    """Save the common time zone ("" = the Pi's own; anything not in the list is the Pi's own too). Returns what is now set."""
    import netswitch_tz as tz
    value = value if value in tz.ZONE_CHOICES else ""
    tmp = TIME_ZONE + ".tmp"
    with open(tmp, "w") as f:
        f.write(value)
    os.rename(tmp, TIME_ZONE)
    return value


# ---------------------------------------------------------------- file state

def log(text):
    """A line in the service's log (journalctl -u dreampi-netswitch)."""
    sys.stderr.write(text.rstrip("\n") + "\n")


def read_file(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except IOError:
        return None






def wifi_state():
    """Latest Wi-Fi setup state written by the Wi-Fi service: state (idle /
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


def update_status():
    """running / ok / failed, or idle. A finished result is only reported for 10 minutes, so an old update isn't
    announced for ever."""
    text = (read_file(UPDATE_STATUS) or "").strip()
    if text not in ("running", "ok", "failed"):
        return "idle"
    try:
        if text != "running" and time.time() - os.path.getmtime(UPDATE_STATUS) > 600:
            return "idle"
    except OSError:
        return "idle"
    return text
