# Base - shared state and settings of the modular dashboard (everything the web service and the services of the modules all read or write).
# What belongs to the project is in project.json (name, page title, data folder, ...) and in its modules. No server, no probing,
# so the small services can import it cheaply. Python 3.
import json
import os
import re
import sys
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
BASE_DIR = PROJECT.get("data_dir", "/opt/dashboard")           # where the project keeps its settings and state
TMP_PREFIX = PROJECT.get("tmp_prefix", "/tmp/dashboard")       # the start of the names of its short-lived state files
PALETTE_CUSTOM = os.path.join(BASE_DIR, "palette_custom.json")   # the user's changes to the list of the palette (Appearance > Colour palette): {"order": [ids], "deleted": [ids], "names": {id: name}, "custom": [{"id", "name", "ui"}]}
PALETTE_FILE = os.path.join(BASE_DIR, "palette.json")             # {"red": {"ui": "#rrggbb"}}: palette colours the user changed
MODULE_TINTS = os.path.join(BASE_DIR, "tints.json")               # {"clock": {"clock": false}}: colours whose background is neutral instead of coloured
MODULE_COLOURS = os.path.join(BASE_DIR, "colours.json")          # {"checkin": {"checkin": "green", ...}}: the global-palette colours each module uses
MODULE_ORDER = os.path.join(BASE_DIR, "module_order.json")      # ["switcher", "numbers", ...]: the order set in the module picker (top = first, wins)
ADDON_COMMIT = os.path.join(BASE_DIR, "version_commit")  # full commit hash of the checkout that was installed (install.sh)
ADDON_SRC = os.path.join(BASE_DIR, "src_dir")            # that checkout's folder, used by the web update
INSTALL_PORTS = os.path.join(BASE_DIR, "install_ports")  # "<http port> <https port>", so an update keeps them
UPDATE_ORIGIN = os.path.join(BASE_DIR, "update_origin")  # the checkout's git origin URL when installed; "Update now" refuses another one
ADMIN_PIN = os.path.join(BASE_DIR, "admin_pin")          # salted hash of the optional PIN for update/restart (install.sh --pin)
ALLOWED_HOSTS = os.path.join(BASE_DIR, "allowed_hosts")  # extra host names the web page answers to, one per line
UPDATE_STATUS = TMP_PREFIX + ".update"          # running / ok / failed, written by the update script
UPDATE_LOG = TMP_PREFIX + ".update.log"
IMAGEBG_FILE = os.path.join(BASE_DIR, "background_image")     # the picture of the Background image module (any of PNG, JPEG, GIF, WebP; its type is in the config)
IMAGEBG_CONFIG = os.path.join(BASE_DIR, "imagebg.json")  # {"fit", "dim", "type", "version"} of the Background image module
SETTINGS_PIN = os.path.join(BASE_DIR, "settings_pin")   # exists = Settings asks for the PIN (when one is set) before it opens and changes anything
SCREEN = os.path.join(BASE_DIR, "screen.json")         # how the page is laid out on a wide screen: max columns, stretch, scale (Settings > Appearance)
HIGHLIGHT = os.path.join(BASE_DIR, "highlight")     # "rainbow" or a palette id: how a highlighted box looks (Settings > Appearance)
CONTACTS = os.path.join(BASE_DIR, "contacts.json")     # {"people": [{id, name, department, role, phone, location, restrictToLocation, active, order}]}: the contacts module's roster (imported from a CSV)
PHOTOS_DIR = os.path.join(BASE_DIR, "photos")           # <person id>.jpg / .png: the small profile photos (uploaded from the status menu, written by the contacts module, read by the check-in board)
CHECKIN = os.path.join(BASE_DIR, "checkin.json")       # {"rev", "config", "statuses", "people": {id: {in, status, detail, at}}}: the check-in module's live state, shared by every screen
CLOCK_CONFIG = os.path.join(BASE_DIR, "clock.json")  # {"format": "24h"|"12h"|"12h-ampm", "beat": bool, "world": bool, "large": bool, "cities": [...]}: the clock module's settings
TIME_ZONE = os.path.join(BASE_DIR, "time_zone")      # the time zone every module may show times in: an IANA name, or empty / missing = the Pi's own (Settings > About)


# ------------------------------------------------------------------ modules
# Everything the page shows is a module: a folder in modules/ with a module.json (and a layout.json, see
# base_modules.py). module.json holds
#   "name"         the title in the module picker                 (older files: "title")
#   "description"  the text under it in the picker
#   "enabled"      on by default when it is first loaded           (older files: "default"); the picker's own choice
#                  (modules.json) overrides it
#   "visible"      false = not in the picker and always on (the system / About module, say)   (default true)
#   optional: "web" (Python entry for the web service), "ui" (page kit version), "order" (where it starts out in the
#   list), "colours" / "primary" (see the colour section below)
# A module is *installed* when its folder is there and *enabled* when it is on in the picker. Its place in the picker
# (module_order.json) is its priority: the first one shows first and wins where two modules want the same thing.
# Everything that has to know - the web page and the services of the modules - asks here.
MODULES_DIR = project_path("modules")
MODULES_STATE = os.path.join(BASE_DIR, "modules.json")     # {"clock": true, "imagebg": false, ...} set from the module picker


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


# ---------------------------------------------------------------- colours
# The page's colours: one global palette of 15 named colours (7 hues, each normal and bright, and "Global main"),
# defined only here. A module never writes a colour of its own; it names one from the palette by its id ("orange",
# "bright-blue" ...), either in module.json  "colours": {"checkin": "green", ...}  (the user can change these in the
# module's own settings, see module_colour()) or as its  "primary"  colour, the one used on its borders and buttons.
# id, name, hue group, page colour, its lighter variant (borders, text).
# "global" is not a fixed colour: Global main, one colour the user picks in Appearance, for boxes that should share it.
PALETTE = (
    ("global", "Global main", "global", "#6f7d99", "#b0b7c7"),
    ("red", "Red", "red", "#d9363e", "#ef8a8f"),
    ("orange", "Orange", "orange", "#e8761c", "#f6b27a"),
    ("yellow", "Yellow", "yellow", "#d9a900", "#f0d36a"),
    ("green", "Green", "green", "#2fa84f", "#8ed9a4"),
    ("cyan", "Cyan", "cyan", "#1fb5c9", "#7fdbe6"),
    ("blue", "Blue", "blue", "#1c6fe8", "#80b1f6"),
    ("purple", "Purple", "purple", "#8a4fd6", "#bf9ae8"),
    ("white", "White", "white", "#b8bec9", "#e6e9ee"),
    ("bright-red", "Bright red", "red", "#ff5a5f", "#ffa6a9"),
    ("bright-green", "Bright green", "green", "#4cd964", "#a6efb6"),
    ("bright-cyan", "Bright cyan", "cyan", "#3de0f5", "#9aeefa"),
    ("bright-blue", "Bright blue", "blue", "#4a90ff", "#9fc4ff"),
    ("bright-purple", "Bright purple", "purple", "#b070ff", "#d3b0ff"),
    ("bright-pink", "Bright pink", "pink", "#ff6ab8", "#ffaad6"),
)
PALETTE_IDS = tuple(c[0] for c in PALETTE)       # the ones the add-on ships; palette_ids() is the list in use (the colour palette editor can delete and add colours)
FIXED_COLOURS = ("global", "orange")   # never deleted: "Global main" is not a colour of its own, orange is the one everything falls back to
# colours that were in the palette once: what a saved choice of them becomes
LEGACY_COLOURS = {"bright-orange": "orange", "bright-yellow": "yellow", "pink": "bright-pink", "teal": "cyan"}
DEFAULT_COLOUR = "orange"


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
    {"order", "deleted", "names", "custom"}. The screen colours the user changed are in palette.json."""
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
            out["custom"].append({"id": c["id"], "name": str(c.get("name") or c["id"])[:24], "ui": c["ui"].lower()})
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
    entries += [(c["id"], c["name"], "custom", c["ui"], lighter(c["ui"])) for c in lay["custom"]]
    entries = [(c[0], lay["names"].get(c[0], c[1])) + tuple(c[2:]) for c in entries]
    rank = dict((i, n) for n, i in enumerate(lay["order"]))
    return sorted(entries, key=lambda c: rank.get(c[0], len(rank)))          # a stable sort: what the order does not name keeps its place at the end


def palette_ids():
    """The ids of the palette in use (see palette_layout())."""
    return tuple(c[0] for c in _palette_entries())


def palette_overrides():
    """{id: {"ui": "#rrggbb"}}: what the user changed in the palette editor (only valid entries)."""
    try:
        with open(PALETTE_FILE) as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        return {}
    out = {}
    ids = palette_ids()
    for ident, v in (data.items() if isinstance(data, dict) else []):
        if ident in ids and isinstance(v, dict):
            keep = dict((k, str(v[k]).lower()) for k in ("ui",) if isinstance(v.get(k), _STR) and _HEX.match(v[k]))
            if keep:
                out[ident] = keep
    return out


def colours():
    """The palette as dicts: id, name, group, ui, ui_l, and the default colour (ui_default) as the add-on ships it."""
    over, out = palette_overrides(), []
    for c in _palette_entries():
        o = over.get(c[0], {})
        ui = o.get("ui", c[3])
        out.append({"id": c[0], "name": c[1], "group": c[2], "ui": ui, "ui_l": lighter(ui) if "ui" in o else c[4],
                    "ui_default": c[3]})
    return out


def set_palette_colour(ident, ui=None):
    """Change a palette colour (ui), "#rrggbb". A value equal to the default is not kept.
    Returns False for an unknown id or a value that is not a colour."""
    if ident not in palette_ids() or any(v is not None and not (isinstance(v, _STR) and _HEX.match(v)) for v in (ui,)):
        return False
    base = [c for c in _palette_entries() if c[0] == ident][0]
    over = palette_overrides()
    entry = over.get(ident, {})
    for key, value, default in (("ui", ui, base[3]),):
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
    """Put one palette colour (or all of them) back to the shipped colour."""
    over = palette_overrides()
    if ident is None:
        over = {}
    else:
        over.pop(ident, None)
    _write_palette(over)


def _write_palette(over):
    """Keep what is changed on screen in palette.json."""
    tmp = PALETTE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(over, f)
    os.rename(tmp, PALETTE_FILE)


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
    """Rename a colour and / or change its colour. False when it does not exist."""
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
    """Take a colour out of the palette. What used it falls back (a module's pick to its default, a highlight to the rainbow). False for one that cannot be deleted (FIXED_COLOURS) or does not exist."""
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
        reset_palette()
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
    reset_palette(ident)
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
    ids = palette_ids()

    def ok(k, v):
        return LEGACY_COLOURS.get(v, v) in ids
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
            used = set()
            for k in uniq:                       # still the same colour twice (a default was deleted from the palette): the first ones that are free
                if out[k] in used:
                    out[k] = ([i for i in ids if i not in used and i != "global"] or [DEFAULT_COLOUR])[0]
                used.add(out[k])
    return out


# ---- highlight: a module can ask for one of its dashboard boxes to stand out for a while (an event starts soon, say): /api
# "highlight" {box id: why}. A neutral box turns its own colour; a coloured box takes the highlight look
# set here, the same for every module: an animated rainbow edge or one palette colour that glows.
HIGHLIGHT_STYLES = ("rainbow",) + PALETTE_IDS        # as shipped; highlight_styles() is the list in use
DEFAULT_HIGHLIGHT = "rainbow"


def highlight_styles():
    return ("rainbow",) + palette_ids()


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


def set_module_colour(name, key, ident):
    """The user gives one of the module's colour keys a palette colour. With "colours_unique", the key that had that
    colour gets the old one (a swap), so they never match. Returns the module's new {key: id}, or None when the
    module, key or colour is unknown."""
    cur = module_colours(name)
    ident = LEGACY_COLOURS.get(ident, ident)
    if key not in cur or ident not in palette_ids():
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


def settings_pin_on():
    return os.path.exists(SETTINGS_PIN)


def save_settings_pin(on):
    if on:
        open(SETTINGS_PIN, "w").close()
    elif os.path.exists(SETTINGS_PIN):
        os.remove(SETTINGS_PIN)


# ---- screen layout: how many columns the dashboard and Settings may use on a wide screen, and whether the boxes stretch to fill it
THEMES = ("dark", "light", "auto")
SCREEN_DEFAULTS = {"dash_cols": 1, "set_cols": 4, "stretch": False, "scale": False, "drag": False, "noscroll": False, "fit": False, "theme": "dark"}
MAX_COLUMNS = 6


def screen_settings():
    """{"dash_cols": 1-6, "set_cols": 1-6, "stretch": bool, "scale": bool}: the saved layout settings over the defaults (a bad or missing
    file gives the defaults). dash_cols / set_cols are the most columns the dashboard / Settings may use; they only get as many as the screen
    fits (about 430 px each). stretch makes the columns fill the screen's width; scale (only with stretch) makes the boxes' content grow
    with their width instead of getting more room; fit scales the main screen up until its bottom meets the bottom of the screen; drag lets the tiles of the main screen be moved (which reorders the modules); noscroll stops the main screen from scrolling; theme is "dark", "light" or "auto" (the device's own setting)."""
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
        for k in ("stretch", "scale", "drag", "noscroll", "fit"):
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
        elif k in ("stretch", "scale", "drag", "noscroll", "fit") and isinstance(v, bool):
            cur[k] = v
        elif k == "theme" and v in THEMES:
            cur[k] = v
    tmp = SCREEN + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cur, f, sort_keys=True)
    os.rename(tmp, SCREEN)
    return cur


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


# ---------------------------------------------------------------- file state

def log(text):
    """A line in the service's log (journalctl -u checkin-board)."""
    sys.stderr.write(text.rstrip("\n") + "\n")


def read_file(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except IOError:
        return None






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
