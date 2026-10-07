# Base - shared state and settings of the modular dashboard (everything the web service and the services of the modules all read or write).
# What belongs to the project is in project.json (name, page title, data folder, ...) and in its modules. No server, no probing,
# so the small services can import it cheaply. Works on Python 3 and 2.7.
import json
import os
import re
import time

_HERE = os.path.dirname(os.path.abspath(__file__))


def project_path(name):
    """A file or folder of the project: next to the base files (installed) or one folder above them (in the repository)."""
    for folder in (_HERE, os.path.dirname(_HERE)):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            return path
    return os.path.join(_HERE, name)


def _read_project():
    try:
        with open(project_path("project.json")) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (IOError, OSError, ValueError):
        return {}


PROJECT = _read_project()      # project.json: {"name", "title" (the page's), "data_dir", "tmp_prefix", "service", "icon", "touch_icon"}
BASE_DIR = PROJECT.get("data_dir", "/opt/dreampi-netswitch")           # where the project keeps its settings and state
TMP_PREFIX = PROJECT.get("tmp_prefix", "/tmp/dreampi-netswitch")       # the start of the names of its short-lived state files
FLAG = os.path.join(BASE_DIR, "dcnet_mode")
PALETTE_CUSTOM = os.path.join(BASE_DIR, "palette_custom.json")   # the user's changes to the list of the palette (Appearance > Colour palette): {"order": [ids], "deleted": [ids], "names": {id: name}, "custom": [{"id", "name", "ui", "led"}]}
LED_COLOURS = os.path.join(BASE_DIR, "led_colours.json")   # {"red": "#rrggbb"}: how the LED shows a palette colour when that is not the default (Status LED > Colours, the LED module's)
PALETTE_FILE = os.path.join(BASE_DIR, "palette.json")             # {"red": {"ui": "#rrggbb"}}: palette colours the user changed on screen (Appearance > Colour palette; the LED colours are in led_colours.json)
MODULE_TINTS = os.path.join(BASE_DIR, "tints.json")               # {"clock": {"clock": false}}: colours whose background is neutral instead of coloured
MODULE_COLOURS = os.path.join(BASE_DIR, "colours.json")          # {"switcher": {"dcnow": "orange", ...}}: the global-palette colours each module uses
MODULE_ORDER = os.path.join(BASE_DIR, "module_order.json")      # ["switcher", "numbers", ...]: the order set in the module picker (top = first, wins)
BOOT_ID = os.path.join(BASE_DIR, "boot_id")              # the kernel's id of the boot the selection was last reset for
KERNEL_BOOT_ID = "/proc/sys/kernel/random/boot_id"
DEBUG_DTMF = os.path.join(BASE_DIR, "debug_dtmf")
ADMIN_PIN = os.path.join(BASE_DIR, "admin_pin")          # salted hash of the optional PIN for update/restart/Wi-Fi (install.sh --pin)
ALLOWED_HOSTS = os.path.join(BASE_DIR, "allowed_hosts")  # extra host names the web page answers to, one per line
PLAYERS_SOURCES = os.path.join(BASE_DIR, "players_sources.json")   # JSON addresses for the optional online-players list
PLAYERS_CACHE = os.path.join(BASE_DIR, "players_cache.json")   # the last list the players module read (shown again after a restart while the new one loads)
PLAYERS_FAVORITES = os.path.join(BASE_DIR, "players_favorites.json")   # {"games": [names], "players": [names]} the user watches
OPENMENU_GAMES = os.path.join(BASE_DIR, "openmenu_games.json")   # {"hash", "time", "games": [...]}: the game list the Dreamcast's openMenu uploaded (openMenu link module)
IMAGEBG_FILE = os.path.join(BASE_DIR, "background_image")     # the picture of the Background image module (any of PNG, JPEG, GIF, WebP; its type is in the config)
IMAGEBG_CONFIG = os.path.join(BASE_DIR, "imagebg.json")  # {"fit", "dim", "type", "version"} of the Background image module
NUMBERS = os.path.join(BASE_DIR, "numbers.json")     # phone numbers per action, edited on the page, read by the hook
CLOCK_MODE = os.path.join(BASE_DIR, "clock_mode")    # older versions: "24h", "12h" or "beat" (read once to carry the choice over to clock.json)
HIGHLIGHT = os.path.join(BASE_DIR, "highlight")     # "rainbow" or a palette id: how a highlighted box looks (Settings > Appearance)
SETTINGS_PIN = os.path.join(BASE_DIR, "settings_pin")   # exists = Settings asks for the PIN (when one is set) before it opens and changes anything
SCREEN = os.path.join(BASE_DIR, "screen.json")         # how the page is laid out on a wide screen: max columns, stretch, scale (Settings > Appearance)
EVENTS_DB = os.path.join(BASE_DIR, "events.db")        # SQLite: the DC99 events imported by the events module
EVENTS_CONFIG = os.path.join(BASE_DIR, "events.json")   # its settings: reminder lead time, time zone, sync interval, picked events, series
EVENT_REMINDERS = os.path.join(BASE_DIR, "event_reminders.json")   # the DC99 events the user asked to be reminded of (events module, read by the LEDs)
CLOCK_CONFIG = os.path.join(BASE_DIR, "clock.json")  # {"format": "24h"|"12h"|"12h-ampm", "beat": bool, "world": bool, "large": bool, "cities": [...]}: the clock module's settings
TIME_ZONE = os.path.join(BASE_DIR, "time_zone")      # the time zone every module may show times in: an IANA name, or empty / missing = the Pi's own (Settings > About)
STATUS = TMP_PREFIX + ".active"
STATE = TMP_PREFIX + ".state"
MODEM = TMP_PREFIX + ".modem"
DTMF_LOG = TMP_PREFIX + "-dtmf.log"
# Wi-Fi setup (netswitch_buttons.py, install.sh --wifi); the buttons themselves are always installed
WIFI_DEMO = os.path.join(BASE_DIR, "wifi_demo")        # exists = Wi-Fi setup runs on dummy networks (install.sh --wifi-demo)
WIFI_START = os.path.join(BASE_DIR, "wifi_start")   # touched to ask netswitch_buttons.py to start
WIFI_STOP = os.path.join(BASE_DIR, "wifi_stop")     # touched to ask it to stop / cancel
WIFI_CONNECT = os.path.join(BASE_DIR, "wifi_connect")   # {"ssid":..., "password":...}, an alternative
                                                         # to the setup access point's own /connect -
                                                         # lets the regular page pick a network too,
                                                         # useful when it's reachable some other way
                                                         # (e.g. Ethernet) while Wi-Fi is being set up
WIFI_STATE = TMP_PREFIX + ".wifi"          # written by netswitch_buttons.py
WIFI_STALE = 30       # ignore WIFI_STATE when older than this (the service is down)
WIFI_AP_SSID = "DreamPi WiFi Config"
NET_STATE = TMP_PREFIX + ".net"   # shared with the LED service
NET_STALE = 20        # ignore NET_STATE when older than this (web service down)
POKE_PREFIX = TMP_PREFIX + ".poke."   # poke(name): "measure it again now", see poke()
PLAYERS_WATCH = TMP_PREFIX + ".players"   # {"time", "games": [favourite games being played], "friends": [favourite players online]}, written by the players module for the LEDs
PLAYERS_WATCH_STALE = 300     # ignore it when older than this (web service down / list not reachable)


# ------------------------------------------------------------------ modules
# Everything the page shows is a module: a folder in modules/ with a module.json (and a layout.json, see
# base_modules.py). module.json holds
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
MODULES_DIR = project_path("modules")
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


def module_actions():
    """The actions the enabled modules announce (module.json "actions": [{"id", "label", "sub"}]), in picker order, as
    [{"value": "<module>.<id>", "label", "sub", "group": <the module's title>}]. A module's hook file does them inside DreamPi
    (see netswitch_hook.py); the phone numbers module offers them in its rows."""
    out, state = [], modules_state()
    for name in module_names():
        manifest = module_manifest(name) or {}
        if not module_enabled(name, state):
            continue
        for a in manifest.get("actions") or []:
            if isinstance(a, dict) and re.match(r"^[a-z][a-z0-9_]*$", str(a.get("id") or "")):
                out.append({"value": "%s.%s" % (name, a["id"]), "label": str(a.get("label") or a["id"]),
                            "sub": str(a.get("sub") or ""), "group": module_title(name, manifest)})
    return out


def module_led_messages():
    """The messages the enabled modules announce for the LEDs (module.json "led_messages": [{"id", "label", "group", "description"}]),
    in picker order, as [{"key", "label", "group", "description", "module"}]. The LED module lists them as the triggers a row can
    have; a message of a module that is off is not offered and never lights. The first module to announce a key owns it."""
    out, seen, state = [], set(), modules_state()
    for name in module_names():
        manifest = module_manifest(name) or {}
        if not module_enabled(name, state):
            continue
        for m in manifest.get("led_messages") or []:
            key = str((m or {}).get("id") or "") if isinstance(m, dict) else ""
            if re.match(r"^[a-z][a-z0-9-]*$", key) and key not in seen:
                seen.add(key)
                out.append({"key": key, "label": str(m.get("label") or key), "group": str(m.get("group") or module_title(name, manifest)),
                            "description": str(m.get("description") or ""), "module": name})
    return out


def saved_module_order():
    try:
        with open(MODULE_ORDER) as f:
            data = json.load(f)
        return [n for n in data if isinstance(n, type(u""))] if isinstance(data, list) else []
    except (IOError, OSError, ValueError):
        return []


_layout_groups = {}


def module_group(name):
    """0 = a module with a dashboard box (with or without settings), 1 = settings only (or nothing to show), 2 = a background. The picker
    lists the groups in this order, whatever the user's own order says inside each of them (read from the module's layout.json)."""
    path = os.path.join(MODULES_DIR, name, "layout.json")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return 1
    cached = _layout_groups.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with open(path) as f:
            lay = json.load(f)
    except (IOError, OSError, ValueError):
        lay = {}
    lay = lay if isinstance(lay, dict) else {}
    group = 2 if "background" in lay else (0 if lay.get("dashboard") else 1)
    _layout_groups[path] = (mtime, group)
    return group


def module_names():
    """Names of the installed modules (folders with a readable module.json), in picker order: the order the user set
    (module_order.json) first, then any module not in it by its manifest's "order" hint and name; then grouped: the modules with a
    dashboard box first, then the settings-only ones, then the backgrounds (module_group()), each group in that order."""
    try:
        names = [n for n in os.listdir(MODULES_DIR) if module_manifest(n)]
    except OSError:
        return []
    saved = [n for n in saved_module_order() if n in names]
    rest = sorted((n for n in names if n not in saved), key=lambda n: (module_manifest(n).get("order", 100), n))
    return sorted(saved + rest, key=module_group)             # a stable sort: inside a group the order is unchanged


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


def save_dashboard_order(names):
    """The tiles of the main screen were moved: `names` are modules, in the order their tiles now have. They take the places that
    those modules had in the picker order, in that sequence (the others stay where they are). Returns the new order, or None."""
    if not isinstance(names, list) or not all(isinstance(n, type(u"")) for n in names):
        return None
    cur = module_names()
    moved = [n for n in names if n in cur]
    moved = [n for i, n in enumerate(moved) if n not in moved[:i]]
    slots = [i for i, n in enumerate(cur) if n in moved]
    new = list(cur)
    for i, n in zip(slots, moved):
        new[i] = n
    return save_module_order(new)


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
# The page's colours: one global palette of 15 named colours (8 hues, each normal and bright, like a terminal's 16, and "Global main"),
# defined only here (the user can edit it in Settings > Appearance > Colour palette). A module never writes a colour of its own; it names one from the palette by its id ("orange",
# "bright-blue" ...), either in module.json  "colours": {"dcnow": "orange", ...}  (the user can change these in the
# module's own settings, see module_colour()) or as its  "primary"  colour, the one used on its borders and buttons.
# id, name, hue group, page colour, its lighter variant (borders, text), LED colour (the LED's own tuning: a screen
# colour looks different lit on a NeoPixel).
# "global" (Global main) is not a fixed colour: one colour the user picks, for boxes that should share it. A module can add a colour
# of its own to what a colour pick offers (module.json "colour_tokens"; see colour_tokens()): the network switcher adds "network"
# (Selected network: whichever colour DCNow! or DCNET has right now, it follows the switch). Those are not part of the palette.
PALETTE = (
    ("global", "Global main", "global", "#6f7d99", "#b0b7c7", "#8090ff"),
    ("red", "Red", "red", "#d9363e", "#ef8a8f", "#ff0000"),
    ("orange", "Orange", "orange", "#e8761c", "#f6b27a", "#ff8c00"),
    ("yellow", "Yellow", "yellow", "#d9a900", "#f0d36a", "#ffd000"),
    ("green", "Green", "green", "#2fa84f", "#8ed9a4", "#00ff00"),
    ("cyan", "Cyan", "cyan", "#1fb5c9", "#7fdbe6", "#00c8ff"),
    ("blue", "Blue", "blue", "#1c6fe8", "#80b1f6", "#0046ff"),
    ("purple", "Purple", "purple", "#8a4fd6", "#bf9ae8", "#aa00ff"),
    ("white", "White", "white", "#b8bec9", "#e6e9ee", "#ffffff"),
    ("bright-red", "Bright red", "red", "#ff5a5f", "#ffa6a9", "#ff5050"),
    ("bright-green", "Bright green", "green", "#4cd964", "#a6efb6", "#50ff70"),
    ("bright-cyan", "Bright cyan", "cyan", "#3de0f5", "#9aeefa", "#70e0ff"),
    ("bright-blue", "Bright blue", "blue", "#4a90ff", "#9fc4ff", "#5080ff"),
    ("bright-purple", "Bright purple", "purple", "#b070ff", "#d3b0ff", "#cc66ff"),
    ("bright-pink", "Bright pink", "pink", "#ff6ab8", "#ffaad6", "#ff70b0"),
)
PALETTE_IDS = tuple(c[0] for c in PALETTE)       # the ones the add-on ships; palette_ids() is the list in use (the colour palette editor can delete and add colours)
FIXED_COLOURS = ("global", "orange")   # never deleted: "Global main" is not a colour of its own, orange is the one everything falls back to
# colours that were in the palette once: what a saved choice of them becomes
LEGACY_COLOURS = {"bright-orange": "orange", "bright-yellow": "yellow", "pink": "bright-pink"}
DEFAULT_COLOUR = "orange"
# The switcher's two network colours (module.json "colours" keys "dcnow" / "dcnet"). Only these are real colours (never "Selected
# network", which would be a circle) and, with "colours_unique", never the same; the module's other colour keys are free.
NETWORKS = ("dcnow", "dcnet")


def _network_key(name, key):
    return name == "switcher" and key in NETWORKS


_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
try:
    _STR = basestring  # noqa: F821  (Python 2: json gives unicode)
except NameError:
    _STR = str


def lighter(ui, share=0.45):
    """The lighter variant of a page colour (borders, text): the colour mixed with white."""
    return "#%02x%02x%02x" % tuple(int(round(int(ui[i:i + 2], 16) + (255 - int(ui[i:i + 2], 16)) * share)) for i in (1, 3, 5))


_CUSTOM_ID = re.compile(r"^[a-z][a-z0-9-]{0,23}$")
MAX_CUSTOM_COLOURS = 40


def palette_layout():
    """The user's changes to the list of the palette (Settings > Appearance > Colour palette) over the shipped palette, made safe:
    {"order", "deleted", "names", "custom"}. The screen colours the user changed are in palette.json, the LED colours in led_colours.json."""
    out = {"order": [], "deleted": [], "names": {}, "custom": []}
    try:
        with open(PALETTE_CUSTOM) as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        return out
    if not isinstance(data, dict):
        return out
    seen = set(PALETTE_IDS)
    for c in data.get("custom") if isinstance(data.get("custom"), list) else []:
        if (isinstance(c, dict) and isinstance(c.get("id"), _STR) and _CUSTOM_ID.match(c["id"]) and c["id"] not in seen and isinstance(c.get("ui"), _STR)
                and _HEX.match(c["ui"]) and len(out["custom"]) < MAX_CUSTOM_COLOURS):
            seen.add(c["id"])
            led = c.get("led") if isinstance(c.get("led"), _STR) and _HEX.match(c.get("led")) else c["ui"]
            out["custom"].append({"id": c["id"], "name": str(c.get("name") or c["id"])[:24], "ui": c["ui"].lower(), "led": led.lower()})
    if isinstance(data.get("deleted"), list):
        out["deleted"] = [i for i in data["deleted"] if i in PALETTE_IDS and i not in FIXED_COLOURS]
    if isinstance(data.get("names"), dict):
        out["names"] = dict((k, str(v).strip()[:24]) for k, v in data["names"].items() if k in seen and isinstance(v, _STR) and str(v).strip())
    if isinstance(data.get("order"), list):
        out["order"] = [i for i in data["order"] if isinstance(i, _STR)]
    return out


def _palette_entries():
    """The palette in use as tuples like PALETTE: the shipped colours that were not deleted and the custom ones, renamed and in the user's order."""
    lay = palette_layout()
    entries = [c for c in PALETTE if c[0] not in lay["deleted"]]
    entries += [(c["id"], c["name"], "custom", c["ui"], lighter(c["ui"]), c["ui"]) for c in lay["custom"]]          # its LED colour starts out as its screen colour
    entries = [(c[0], lay["names"].get(c[0], c[1])) + tuple(c[2:]) for c in entries]
    rank = dict((i, n) for n, i in enumerate(lay["order"]))
    return sorted(entries, key=lambda c: rank.get(c[0], len(rank)))          # a stable sort: what the order does not name keeps its place at the end


def palette_ids():
    """The ids of the palette in use (see palette_layout())."""
    return tuple(c[0] for c in _palette_entries())


def _read_dict(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def colour_tokens():
    """[{"id", "name", "module"}]: colours that the enabled modules add to what a colour pick offers (module.json "colour_tokens": [{"id", "name"}]), after
    the palette. Not part of the palette: it cannot be edited or deleted. The switcher's "network" (Selected network) follows the selected network."""
    out, seen = [], set(PALETTE_IDS)
    state = modules_state()
    for name in module_names():
        if not module_enabled(name, state):
            continue
        for t in (module_manifest(name) or {}).get("colour_tokens") or []:
            if isinstance(t, dict) and isinstance(t.get("id"), _STR) and _CUSTOM_ID.match(t["id"]) and t["id"] not in seen:
                seen.add(t["id"])
                out.append({"id": t["id"], "name": str(t.get("name") or t["id"])[:24], "module": name})
    return out


def colour_ids():
    """Every id a colour pick may hold: the palette's and the modules' colours (colour_tokens())."""
    return palette_ids() + tuple(t["id"] for t in colour_tokens())


def palette_overrides():
    """{id: {"ui": "#rrggbb", "led": "#rrggbb"}}: what the user changed in a palette colour, on screen (palette.json: the colour palette editor) and on the
    LED (led_colours.json: the LED module); only valid entries. An older palette.json that also holds "led" values still counts for them."""
    ids, out = palette_ids(), {}
    for ident, v in _read_dict(PALETTE_FILE).items():
        if ident in ids and isinstance(v, dict):
            keep = dict((k, str(v[k]).lower()) for k in ("ui", "led") if isinstance(v.get(k), _STR) and _HEX.match(v[k]))
            if keep:
                out[ident] = keep
    for ident, v in _read_dict(LED_COLOURS).items():
        if ident in ids and isinstance(v, _STR) and _HEX.match(v):
            out.setdefault(ident, {})["led"] = v.lower()
    return out


def colours():
    """The palette as dicts: id, name, group, ui, ui_l, led, and the defaults (ui_default, led_default) as the add-on ships them."""
    over, out = palette_overrides(), []
    for c in _palette_entries():
        o = over.get(c[0], {})
        ui = o.get("ui", c[3])
        out.append({"id": c[0], "name": c[1], "group": c[2], "ui": ui, "ui_l": lighter(ui) if "ui" in o else c[4],
                    "led": o.get("led", c[5]), "ui_default": c[3], "led_default": c[5]})
    # the modules' own colours (colour_tokens()); "network" (Selected network) is the colour of the selected network, as it is now (the switcher's pick for it)
    sel = "dcnet" if os.path.exists(FLAG) else "dcnow"
    pick = module_colours("switcher").get(sel) or {"dcnow": "orange", "dcnet": "blue"}[sel]
    base = ([c for c in out if c["id"] == pick] or [c for c in out if c["id"] == DEFAULT_COLOUR] or out)[0]
    for t in colour_tokens():
        out.append(dict(base, id=t["id"], name=t["name"], group="token", ui_default=base["ui"], led_default=base["led"], token=True))
    return out


def set_palette_colour(ident, ui=None, led=None):
    """Change a palette colour on screen (ui) and / or on the LED (led), "#rrggbb". A value equal to the default is not kept.
    Returns False for an unknown id or a value that is not a colour."""
    if ident not in palette_ids() or any(v is not None and not (isinstance(v, _STR) and _HEX.match(v)) for v in (ui, led)):
        return False
    base = [c for c in _palette_entries() if c[0] == ident][0]
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
    """Put one palette colour (or all of them) back to the shipped values, on screen and on the LED."""
    over = palette_overrides()
    if ident is None:
        over = {}
    else:
        over.pop(ident, None)
    _write_palette(over)


def reset_palette_ui(ident=None):
    """The same for how the colour looks on screen only (the colour palette editor); what the LED shows is left alone."""
    over = palette_overrides()
    for i in ([ident] if ident else list(over)):
        if i in over:
            over[i].pop("ui", None)
            if not over[i]:
                del over[i]
    _write_palette(over)


def reset_led_colours(ident=None):
    """The same for how the LED shows the colour only (the LED module); how it looks on screen is left alone."""
    over = palette_overrides()
    for i in ([ident] if ident else list(over)):
        if i in over:
            over[i].pop("led", None)
            if not over[i]:
                del over[i]
    _write_palette(over)


def set_led_colour(ident, led):
    """How the LED shows a palette colour, "#rrggbb" (what is asked for, before the white balance and the brightness)."""
    return set_palette_colour(ident, led=led)


def _write_palette(over):
    """Keep what is changed: the screen colours in palette.json, the LED colours in led_colours.json (two owners, two files)."""
    for path, key in ((PALETTE_FILE, "ui"), (LED_COLOURS, "led")):
        part = dict((i, v[key]) for i, v in over.items() if key in v)
        if key == "ui":
            part = dict((i, {"ui": u}) for i, u in part.items())
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(part, f)
        os.rename(tmp, path)


# ---- the changes the colour palette editor makes (see palette_layout())
def _raw_layout():
    try:
        with open(PALETTE_CUSTOM) as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    for key, empty in (("order", []), ("deleted", []), ("custom", []), ("names", {})):
        if not isinstance(data.get(key), type(empty)):
            data[key] = empty
    return data


def _write_layout(data):
    tmp = PALETTE_CUSTOM + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.rename(tmp, PALETTE_CUSTOM)


def palette_add(name, ui):
    """A new colour at the end of the palette. Returns its id, or None for a bad colour or when there are too many."""
    if not (isinstance(ui, _STR) and _HEX.match(ui)):
        return None
    data = _raw_layout()
    if len(data["custom"]) >= MAX_CUSTOM_COLOURS:
        return None
    name = re.sub(r"\s+", " ", str(name or "")).strip()[:24] or "New colour"
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:18]
    base = slug if slug and slug[0].isalpha() else "colour-" + slug if slug else "colour"
    taken = set(PALETTE_IDS) | set(c.get("id") for c in data["custom"] if isinstance(c, dict))
    ident, n = base, 1
    while ident in taken or not _CUSTOM_ID.match(ident):
        n += 1
        ident = "%s-%d" % (base, n)
    data["custom"].append({"id": ident, "name": name, "ui": ui.lower()})
    _write_layout(data)
    return ident


def palette_edit(ident, name=None, ui=None):
    """Rename a colour and / or change its colour on screen (what the LED shows is the LED module's). "Selected network" cannot change colour, only be
    renamed. False when it does not exist."""
    if ident not in palette_ids():
        return False
    data = _raw_layout()
    custom = [c for c in data["custom"] if isinstance(c, dict) and c.get("id") == ident]
    if name is not None:
        name = re.sub(r"\s+", " ", str(name)).strip()[:24]
        if name:
            if custom:
                custom[0]["name"] = name
            else:
                data["names"][ident] = name
            _write_layout(data)
    if ui is not None:
        if custom:
            if not (isinstance(ui, _STR) and _HEX.match(ui)):
                return False
            custom[0]["ui"] = ui.lower()
            _write_layout(data)
        elif not set_palette_colour(ident, ui):
            return False
    return True


def palette_delete(ident):
    """Take a colour out of the palette. What used it falls back (a module's pick to its default, a highlight to the rainbow, an LED row to
    orange). False for one that cannot be deleted (FIXED_COLOURS) or does not exist."""
    if ident in FIXED_COLOURS or ident not in palette_ids():
        return False
    over = palette_overrides()                  # read while the colour is still in the palette: its changes go with it
    data = _raw_layout()
    if ident in PALETTE_IDS:
        if ident not in data["deleted"]:
            data["deleted"].append(ident)
    else:
        data["custom"] = [c for c in data["custom"] if not (isinstance(c, dict) and c.get("id") == ident)]
    data["names"].pop(ident, None)
    data["order"] = [i for i in data["order"] if i != ident]
    _write_layout(data)
    if over.pop(ident, None) is not None:
        _write_palette(over)
    picks = _saved_module_colours()
    changed = False
    for mod in list(picks):
        if isinstance(picks[mod], dict):
            for key in [k for k, v in picks[mod].items() if v == ident]:
                del picks[mod][key]
                changed = True
    if changed:
        tmp = MODULE_COLOURS + ".tmp"
        with open(tmp, "w") as f:
            json.dump(picks, f, sort_keys=True)
        os.rename(tmp, MODULE_COLOURS)
    if (read_file(HIGHLIGHT) or "").strip() == ident:
        save_highlight_style("rainbow")
    return True


def palette_order(ids):
    """The order of the palette: a list of ids (the ones it does not name keep their place after them). Returns False for something else."""
    if not isinstance(ids, list) or not all(isinstance(i, _STR) for i in ids):
        return False
    data = _raw_layout()
    data["order"] = [i for n, i in enumerate(ids) if i in palette_ids() and i not in ids[:n]]
    _write_layout(data)
    return True


def palette_reset(ident=None):
    """Back to the colours the add-on ships: the whole palette (all colours, names, order, screen colours) or one shipped colour (its name and screen
    colour). What the LED shows for a colour is the LED module's and stays."""
    if ident is None:
        reset_palette_ui()
        try:
            os.remove(PALETTE_CUSTOM)
        except OSError:
            pass
        return True
    if ident not in PALETTE_IDS or ident not in palette_ids():
        return False
    data = _raw_layout()
    data["names"].pop(ident, None)
    _write_layout(data)
    reset_palette_ui(ident)
    return True


def palette_version():
    """A short tag of the palette as the page draws it (ids, names, colours): the page asks for the palette again only when it changes."""
    import hashlib
    text = json.dumps([[c["id"], c["name"], c["ui"], c["ui_l"]] for c in colours()], sort_keys=True)
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:10]


def colour(ident):
    """One palette entry as a dict (orange when the id is unknown)."""
    ident = LEGACY_COLOURS.get(ident, ident)
    every = colours()
    for c in every:
        if c["id"] == ident:
            return c
    for c in every:
        if c["id"] == DEFAULT_COLOUR:
            return c
    return every[0]


def colours_css():
    """CSS for the palette: --c-<id>, --c-<id>-l and their -rgb triples on :root, and a class  .c-<id>  that makes
    an element (and what is inside it) use that colour as its --primary. The page's own :root has the defaults."""
    def rgb(h):
        return "%d,%d,%d" % (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))
    root, classes, light = ":root{", "", ""
    for c in colours():
        i = c["id"]
        root += "--c-%s:%s;--c-%s-l:%s;--c-%s-rgb:%s;--c-%s-l-rgb:%s;" % (i, c["ui"], i, c["ui_l"], i, rgb(c["ui"]), i, rgb(c["ui_l"]))
        light += "--c-%s-l:%s;--c-%s-l-rgb:%s;" % (i, c["ui"], i, rgb(c["ui"]))        # the light theme has no pale variant: text and borders in the colour itself
        classes += ".c-%s{--primary:var(--c-%s);--primary-l:var(--c-%s-l);--primary-rgb:var(--c-%s-rgb);--primary-l-rgb:var(--c-%s-l-rgb)}\n" % (i, i, i, i, i)
    return root + "}\nhtml[data-theme=light]:not(.dark-only){" + light + "}\n" + classes


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
    ids = colour_ids()

    def ok(k, v):       # the network colours cannot be "the selected network's" (that would be a circle)
        v = LEGACY_COLOURS.get(v, v)
        return v in ids and not (_network_key(name, k) and v == "network")
    out = dict((k, LEGACY_COLOURS.get(v, v) if ok(k, v) else DEFAULT_COLOUR) for k, v in wanted.items())
    mine = _saved_module_colours().get(name)
    if isinstance(mine, dict):
        for k in out:
            if ok(k, mine.get(k)):
                out[k] = LEGACY_COLOURS.get(mine[k], mine[k])
    if manifest.get("colours_unique"):
        uniq = [k for k in out if _network_key(name, k)] or list(out)
        if len(set(out[k] for k in uniq)) < len(uniq):
            for k in uniq:
                out[k] = LEGACY_COLOURS.get(wanted[k], wanted[k]) if ok(k, wanted[k]) else DEFAULT_COLOUR
            used = set()
            for k in uniq:                       # still the same colour twice (a default was deleted from the palette): the first ones that are free
                if out[k] in used:
                    out[k] = ([i for i in ids if i not in used and i not in ("global", "network")] or [DEFAULT_COLOUR])[0]
                used.add(out[k])
    return out


# ---- highlight: a module can ask for one of its dashboard boxes to stand out for a while (an event starts soon, say): /api
# "highlight" {box id: why}. A grey box (the Dreamcast background) turns its own colour; a coloured box takes the highlight look
# set here, the same for every module: an animated rainbow edge or one palette colour that glows.
HIGHLIGHT_STYLES = ("rainbow",) + PALETTE_IDS        # as shipped; highlight_styles() is the list in use
DEFAULT_HIGHLIGHT = "rainbow"


def highlight_styles():
    return ("rainbow",) + colour_ids()


def highlight_style():
    s = (read_file(HIGHLIGHT) or "").strip()
    return s if s in highlight_styles() else DEFAULT_HIGHLIGHT


def save_highlight_style(value):
    value = str(value or "").strip()
    if value not in highlight_styles():
        value = DEFAULT_HIGHLIGHT
    tmp = HIGHLIGHT + ".tmp"
    with open(tmp, "w") as f:
        f.write(value)
    os.rename(tmp, HIGHLIGHT)
    return value


def settings_pin_on():
    return os.path.exists(SETTINGS_PIN)


def save_settings_pin(on):
    if on:
        open(SETTINGS_PIN, "w").close()
    elif os.path.exists(SETTINGS_PIN):
        os.remove(SETTINGS_PIN)


# ---- screen layout: how many columns the dashboard and Settings may use on a wide screen, and whether the boxes stretch to fill it
THEMES = ("dark", "light", "auto")
SCREEN_DEFAULTS = {"dash_cols": 1, "set_cols": 4, "stretch": False, "scale": False, "drag": False, "fit": False, "theme": "dark"}
MAX_COLUMNS = 6


def screen_settings():
    """{"dash_cols": 1-6, "set_cols": 1-6, "stretch": bool, "scale": bool}: the saved layout settings over the defaults (a bad or missing
    file gives the defaults). dash_cols / set_cols are the most columns the dashboard / Settings may use; they only get as many as the screen
    fits (about 430 px each). stretch makes the columns fill the screen's width; scale (only with stretch) makes the boxes' content grow
    with their width instead of getting more room; fit scales the main screen up until its bottom meets the bottom of the screen; drag lets the tiles of the main screen be moved (which reorders the modules); theme is "dark", "light" or "auto" (the device's own setting)."""
    out = dict(SCREEN_DEFAULTS)
    try:
        with open(SCREEN) as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        data = {}
    if isinstance(data, dict):
        for k in ("dash_cols", "set_cols"):
            v = data.get(k)
            if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= MAX_COLUMNS:
                out[k] = v
        for k in ("stretch", "scale", "drag", "fit"):
            if isinstance(data.get(k), bool):
                out[k] = data[k]
        if data.get("theme") in THEMES:
            out["theme"] = data["theme"]
    return out


def save_screen_settings(changes):
    """Change some of the layout settings ({key: value}; unknown keys and bad values are ignored). Returns the new settings."""
    cur = screen_settings()
    for k, v in (changes or {}).items():
        if k in ("dash_cols", "set_cols"):
            try:
                v = int(v)
            except (TypeError, ValueError):
                continue
            if 1 <= v <= MAX_COLUMNS:
                cur[k] = v
        elif k in ("stretch", "scale", "drag", "fit") and isinstance(v, bool):
            cur[k] = v
        elif k == "theme" and v in THEMES:
            cur[k] = v
    tmp = SCREEN + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cur, f, sort_keys=True)
    os.rename(tmp, SCREEN)
    return cur


def set_module_colour(name, key, ident):
    """The user gives one of the module's colour keys a palette colour. With "colours_unique", the key that had that
    colour gets the old one (a swap), so they never match. Returns the module's new {key: id}, or None when the
    module, key or colour is unknown."""
    cur = module_colours(name)
    ident = LEGACY_COLOURS.get(ident, ident)
    if key not in cur or ident not in colour_ids() or (_network_key(name, key) and ident == "network"):
        return None
    if (module_manifest(name) or {}).get("colours_unique"):
        uniq = [k for k in cur if _network_key(name, k)] or list(cur)
        for k, v in list(cur.items()):
            if k != key and v == ident and key in uniq and k in uniq:
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


def time_zone():
    """The common time zone setting: an IANA name from base_tz.ZONE_CHOICES, or "" = the Pi's own. Any module that shows a
    time of day reads it here (the clock does; the events module still has a zone of its own). Older installs kept it in clock.json."""
    import base_tz as tz
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
    import base_tz as tz
    value = value if value in tz.ZONE_CHOICES else ""
    tmp = TIME_ZONE + ".tmp"
    with open(tmp, "w") as f:
        f.write(value)
    os.rename(tmp, TIME_ZONE)
    return value


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
    text = read_file(path) or ""
    section = re.search(r"^\[DCNet\](.*?)(?=^\[|\Z)", text, re.M | re.S)
    if not section or not re.search(r"^\s*enabled\s*=\s*yes\s*$", section.group(1), re.M):
        return "disabled", "DCNET is not enabled in " + path + " ([DCNet] enabled = yes)"
    return None, None


def dcnet_problem():
    """None when DreamPi's DCNET support is switched on, else a reason."""
    return _dcnet_check()[1]


def dcnet_code():
    """"ok" when DreamPi's DCNET support is switched on, else a short code for why not (see _dcnet_check()), "inactive" when DreamPi is
    not running the add-on (nothing is being switched then). openMenu gets it in the DCNET line of the poll."""
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


def next_event(now=None):
    """The soonest DC99 event that has not ended its reminder window yet, or None: {"id", "title", "start"}. The events module writes the
    next few into EVENT_REMINDERS ("upcoming", soonest first) whenever it changes, so the openMenu answer needs no page and no events code."""
    now = time.time() if now is None else now
    try:
        with open(EVENT_REMINDERS) as f:
            data = json.load(f)
        after = float(data.get("after", 10)) * 60
        coming = [i for i in data.get("upcoming") or [] if i["start"] + after > now]
    except (IOError, OSError, ValueError, AttributeError, KeyError, TypeError):
        return None
    return min(coming, key=lambda i: i["start"]) if coming else None


def poke(name):
    """Ask whoever measures `name` ("internet") to do it again now instead of when its timer runs out. Works from any process: the
    message is a file that is replaced (a new inode), and the receiver looks at poke_stamp() often, which costs next to nothing."""
    path = POKE_PREFIX + re.sub(r"[^a-z0-9_]", "", str(name).lower())
    tmp = path + ".tmp%d" % os.getpid()
    try:
        with open(tmp, "w") as f:
            f.write("%f" % time.time())
        os.rename(tmp, path)
    except (IOError, OSError):
        pass


def poke_stamp(name):
    """Changes every time poke(name) is called (None before the first)."""
    try:
        st = os.stat(POKE_PREFIX + re.sub(r"[^a-z0-9_]", "", str(name).lower()))
        return (st.st_mtime, st.st_ino)
    except OSError:
        return None


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


