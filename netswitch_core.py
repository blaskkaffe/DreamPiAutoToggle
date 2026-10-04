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
PALETTE_FILE = os.path.join(BASE_DIR, "palette.json")             # {"red": {"ui": "#rrggbb", "led": "#rrggbb"}}: palette colours the user changed (on screen, on the LED)
LINKS = os.path.join(BASE_DIR, "links.json")                    # {"links": [{"from": "numbers.call_dcnow", "to": "switcher.select_network", "params": {...}}]}: what an output of one module does (see netswitch_bus.py)
NOTICES = "/tmp/dreampi-netswitch.notices"                       # banners that the "Show a notice" input put up: [{"id", "text", "until"}]
PROFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile.json")   # the app's standard settings, shipped with the code: which modules start on, which links are made
MODULE_TINTS = os.path.join(BASE_DIR, "tints.json")               # {"clock": {"clock": false}}: colours whose background is neutral instead of coloured
MODULE_COLOURS = os.path.join(BASE_DIR, "colours.json")          # {"switcher": {"dcnow": "orange", ...}}: the global-palette colours each module uses
MODULE_ORDER = os.path.join(BASE_DIR, "module_order.json")      # ["switcher", "numbers", ...]: the order set in the module picker (top = first, wins)
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
UPDATE_INFO = "/tmp/dreampi-netswitch.updateinfo"        # {"addon": bool|None, "dreampi": bool, "time"}: the latest check, written by the update module for the LEDs
REBOOT_MARK = "/tmp/dreampi-netswitch.reboot"            # unix time a reboot was asked for (the LEDs show "about to reboot")
PLAYERS_SOURCES = os.path.join(BASE_DIR, "players_sources.json")   # JSON addresses for the optional online-players list
PLAYERS_FAVORITES = os.path.join(BASE_DIR, "players_favorites.json")   # {"games": [names], "players": [names]} the user watches
NUMBERS = os.path.join(BASE_DIR, "numbers.json")     # phone numbers per action, edited on the page, read by the hook
CLOCK_MODE = os.path.join(BASE_DIR, "clock_mode")    # older versions: "24h", "12h" or "beat" (read once to carry the choice over to clock.json)
HIGHLIGHT = os.path.join(BASE_DIR, "highlight")     # "rainbow" or a palette id: how a highlighted box looks (Settings > Appearance)
EVENTS_DB = os.path.join(BASE_DIR, "events.db")        # SQLite: the DC99 events imported by the events module
EVENTS_CONFIG = os.path.join(BASE_DIR, "events.json")   # its settings: reminder lead time, time zone, sync interval, picked events, series
EVENT_REMINDERS = os.path.join(BASE_DIR, "event_reminders.json")   # the DC99 events the user asked to be reminded of (events module, read by the LEDs)
CLOCK_CONFIG = os.path.join(BASE_DIR, "clock.json")  # {"format": "24h"|"12h", "beat": bool, "world": bool}: the clock module's settings
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
PLAYERS_WATCH = "/tmp/dreampi-netswitch.players"   # {"time", "games": [favourite games being played], "friends": [favourite players online]}, written by the players module for the LEDs
PLAYERS_WATCH_STALE = 300     # ignore it when older than this (web service down / list not reachable)


# ------------------------------------------------------------------ modules
# Everything the page shows is a module: a folder in modules/ with a module.json (and a layout.json, see
# netswitch_modules.py). module.json holds
#   "name"         the title in the module picker                 (older files: "title")
#   "description"  the text under it in the picker
#   "enabled"      on by default when it is first loaded           (older files: "default"); the picker's own choice
#                  (modules.json) overrides it
#   "visible"      false = not in the picker and always on (the network switcher, say)   (default true)
#   optional: "web" (Python entry for the web service), "ui" (page kit version), "order" (where it starts out in the
#   list), "colours" / "primary" (see the colour section below)
# A module is *installed* when its folder is there and *enabled* when it is on in the picker. Its place in the picker
# (module_order.json) is its priority: the first one shows first and wins where two modules want the same thing.
# Everything that has to know - the web page, the LED service, the buttons service - asks here.
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


def profile():
    """The app's standard settings (profile.json next to the code): {"modules": {name: on}, "links": [...]}. {} when there is none."""
    try:
        with open(PROFILE) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (IOError, OSError, ValueError):
        return {}


def module_default_enabled(manifest, name=None):
    """Whether a module starts out on: the profile's choice for it, else its manifest's (the user's own choice, in modules.json, wins over both)."""
    chosen = (profile().get("modules") or {}).get(name) if name else None
    if isinstance(chosen, bool):
        return chosen
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
    return state.get(name, module_default_enabled(manifest, name))


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


# ---------------------------------------------------------------- colours
# The page's colours: one global palette of 16 named colours (8 hues, each normal and bright, like a terminal's 16),
# defined only here. A module never writes a colour of its own; it names one from the palette by its id ("orange",
# "bright-blue" ...), either in module.json  "colours": {"dcnow": "orange", ...}  (the user can change these in the
# module's own settings, see module_colour()) or as its  "primary"  colour, the one used on its borders and buttons.
# id, name, hue group, page colour, its lighter variant (borders, text), LED colour (the LED's own tuning: a screen
# colour looks different lit on a NeoPixel).
# Two of the 16 are not fixed colours: "global" (Global main, one colour the user picks in Appearance, for boxes that should
# share it) and "network" (Selected network: whichever colour DCNow! or DCNET has right now, it follows the switch).
PALETTE = (
    ("global", "Global main", "global", "#6f7d99", "#b0b7c7", "#8090ff"),
    ("red", "Red", "red", "#d9363e", "#ef8a8f", "#ff0000"),
    ("orange", "Orange", "orange", "#e8761c", "#f6b27a", "#ff8c00"),
    ("yellow", "Yellow", "yellow", "#d9a900", "#f0d36a", "#ffd000"),
    ("green", "Green", "green", "#2fa84f", "#8ed9a4", "#00ff00"),
    ("cyan", "Cyan", "cyan", "#1fb5c9", "#7fdbe6", "#00c8ff"),
    ("blue", "Blue", "blue", "#1c6fe8", "#80b1f6", "#0046ff"),
    ("purple", "Purple", "purple", "#8a4fd6", "#bf9ae8", "#aa00ff"),
    ("network", "Selected network", "network", "#e8761c", "#f6b27a", "#ff8c00"),
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
        if ident in PALETTE_IDS and ident != "network" and isinstance(v, dict):
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
    # "Selected network" is the colour of the selected network, as it is now (the network switcher's pick for it)
    sel = "dcnet" if os.path.exists(FLAG) else "dcnow"
    pick = module_colours("switcher").get(sel) or {"dcnow": "orange", "dcnet": "blue"}[sel]
    base = [c for c in out if c["id"] == (pick if pick != "network" else DEFAULT_COLOUR)][0]
    for i, c in enumerate(out):
        if c["id"] == "network":
            out[i] = dict(base, id="network", name=c["name"], group="network", ui_default=base["ui"], led_default=base["led"])
    return out


def set_palette_colour(ident, ui=None, led=None):
    """Change a palette colour on screen (ui) and / or on the LED (led), "#rrggbb". A value equal to the default is not kept.
    Returns False for an unknown id or a value that is not a colour."""
    if ident not in PALETTE_IDS or ident == "network" or any(v is not None and not (isinstance(v, _STR) and _HEX.match(v)) for v in (ui, led)):
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
    def ok(v):          # the network switcher's own colours cannot be "the selected network's" (that would be a circle)
        v = LEGACY_COLOURS.get(v, v)
        return v in PALETTE_IDS and not (name == "switcher" and v == "network")
    out = dict((k, LEGACY_COLOURS.get(v, v) if ok(v) else DEFAULT_COLOUR) for k, v in wanted.items())
    mine = _saved_module_colours().get(name)
    if isinstance(mine, dict):
        for k in out:
            if ok(mine.get(k)):
                out[k] = LEGACY_COLOURS.get(mine[k], mine[k])
    if manifest.get("colours_unique") and len(set(out.values())) < len(out):
        out = dict((k, LEGACY_COLOURS.get(v, v) if ok(v) else DEFAULT_COLOUR) for k, v in wanted.items())
    return out


# ---- highlight: a module can ask for one of its dashboard boxes to stand out for a while (an event starts soon, say): /api
# "highlight" {box id: why}. A grey box (the Dreamcast background) turns its own colour; a coloured box takes the highlight look
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
    if key not in cur or ident not in PALETTE_IDS or (name == "switcher" and ident == "network"):
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
    (the network buttons and similar buttons), the boxes on the main page start neutral."""
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


def network_colour(net):
    """The palette entry (dict: id, name, group, ui, ui_l, led) the network switcher gave "dcnow" or "dcnet". The LED
    service and the page's status dot ask for the network colours here; without the switcher module they are orange
    and blue."""
    ident = module_colours("switcher").get(net) or {"dcnow": "orange", "dcnet": "blue"}.get(net, DEFAULT_COLOUR)
    return colour(ident)


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


def players_watch():
    """{"games": [...], "friends": [...]} of favourites that are online now, written by the players module; empty when stale."""
    try:
        with open(PLAYERS_WATCH) as f:
            data = json.load(f)
        if time.time() - data.get("time", 0) > PLAYERS_WATCH_STALE:
            return {"games": [], "friends": []}
        return {"games": list(data.get("games") or []), "friends": list(data.get("friends") or [])}
    except (IOError, OSError, ValueError, AttributeError, TypeError):
        return {"games": [], "friends": []}


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


def update_status():
    """running / ok / failed, or idle. A finished result is only reported for 10 minutes, so an old update isn't
    announced for ever (the update module and the LEDs both ask)."""
    text = (read_file(UPDATE_STATUS) or "").strip()
    if text not in ("running", "ok", "failed"):
        return "idle"
    try:
        if text != "running" and time.time() - os.path.getmtime(UPDATE_STATUS) > 600:
            return "idle"
    except OSError:
        return "idle"
    return text


def write_update_info(addon, dreampi):
    """The update module tells the LEDs what its latest check found (addon: True = a newer add-on exists)."""
    tmp = UPDATE_INFO + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump({"addon": addon, "dreampi": bool(dreampi), "time": time.time()}, f)
        os.rename(tmp, UPDATE_INFO)
    except (IOError, OSError):
        pass


def update_info():
    """{"addon": bool|None, "dreampi": bool} from the latest manual check, {} when there is none (the file is in /tmp: a reboot clears
    it). Nothing checks for updates by itself, so the answer is kept until the next check."""
    try:
        with open(UPDATE_INFO) as f:
            data = json.load(f)
        return data
    except (IOError, OSError, ValueError, AttributeError):
        return {}


def event_reminder(now=None):
    """The reminded DC99 event that is due now, or None: {"id", "title", "start"}. The events module writes EVENT_REMINDERS
    ({"lead": minutes before, "after": minutes after the start, "items": [{"id", "title", "start"}], "dismissed": [ids]}) whenever
    it changes, so the LEDs know without the page being open. Due = from lead minutes before the start until after minutes after it."""
    now = time.time() if now is None else now
    try:
        with open(EVENT_REMINDERS) as f:
            data = json.load(f)
        lead, after = float(data.get("lead", 15)) * 60, float(data.get("after", 10)) * 60
        gone = set(data.get("dismissed") or [])
        due = [i for i in data.get("items") or [] if i.get("id") not in gone and i["start"] - lead <= now < i["start"] + after]
    except (IOError, OSError, ValueError, AttributeError, KeyError, TypeError):
        return None
    return min(due, key=lambda i: i["start"]) if due else None


def mark_reboot():
    try:
        with open(REBOOT_MARK, "w") as f:
            f.write("%f" % time.time())
    except (IOError, OSError):
        pass


def reboot_pending():
    """True for a minute after a reboot was asked for (the Pi is about to go down)."""
    try:
        return time.time() - float(read_file(REBOOT_MARK) or "0") < 60
    except ValueError:
        return False


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
