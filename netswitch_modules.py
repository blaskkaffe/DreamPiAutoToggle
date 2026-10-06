# Check-in add-on - loads the optional modules for the web service.
#
# A module is a folder in modules/ with a module.json (see netswitch_core.module_manifest()). The web
# service runs the Python part of every *enabled* module (the "web" entry in its manifest) and builds the
# module's files into the page:
#   layout.json  what the module shows (below), drawn by the standard widgets of page/widgets.js
#   page.css   added to the page's styles (only for what the page kit has nothing for)
#   page.js    added to the page's script (it runs after the base scripts, in the same scope): custom widgets, hooks, a background
# A module's web entry may define
#   GET = {"/path": fn(handler)}    POST = {"/path": fn(handler)}   answer a request itself (handler.send(...)); a
#                                                                    POST function returns True once it has answered
#   api(d, warnings)                add to the /api answer (d is its dict) and to the warning boxes
#   PROTECTED = ("/path", ...)      POST paths that need the PIN when one is set (they run as root)
#   GET_PREFIX / POST_PREFIX        {"/api/events/": fn}: a path that starts with it (and goes on) and no exact path matched
#   start()                         called once, when the web service itself starts (start_background()) or when the module is
#                                   switched on later: for background work that should run without anyone viewing the page
# module.json "ui": N is the page kit version the module was written for (see UI_KIT); a newer one is not loaded.
# A module may have a layout.json: what it shows, as data, which the base page turns into HTML (see layout()):
#   {"dashboard": [BOX, ...], "settings": [BOX, ...], "data": {...}}       or, for a background module only, {"background": {...}}
#   BOX = {"box": "check-in", "title": "Check-in board", "items": [WIDGET, ...]}
# Modules that name the same box (case-insensitive) share it: their items come one after the other in picker order and
# the first module (in that order) that gives a title names it. A WIDGET is {"type": ..., ...} from WIDGETS below.
# A background module (type "fullscreen" or "part") has a background and nothing else; the top one in picker order is
# drawn and, if it is fullscreen, nothing below it is.
# Nothing outside this file and the web service knows which modules exist. A module whose folder is missing,
# that is switched off, or whose Python fails to import is simply absent. Works on Python 3 and 2.7.
import importlib
import io
import json
import os
import re
import sys
import threading

import netswitch_core as core

UI_KIT = 2       # the version of the page kit (ui in page/page.js, the kit block in page.css); a module may ask for an older one
_PAGE_FILES = ("page.css", "page.js")
# the standard widgets the page can draw from a layout (docs/modules.md, "Layout"); "custom" hands a box to the module's own page.js
WIDGETS = ("text", "row", "button", "toggle", "swatches", "colourpick", "link", "form", "infobox", "status", "bar", "carousel", "worldmap", "triggers",
           "picker", "list", "links", "console", "info", "roster", "custom")
CONTROLS = ("select", "choice", "number", "text", "toggle", "colour", "slider", "range")      # what a form field may hold (W.form, control() in page/widgets.js)
SECTIONS = ("dashboard", "settings")
BACKGROUND_TYPES = ("fullscreen", "part")
_LAYOUT_KEYS = SECTIONS + ("background", "data")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_lock = threading.Lock()
_state = {"sig": None, "loaded": [], "errors": {}, "get": {}, "post": {}, "api": [], "protected": set(), "background": False, "started": set()}


def _read(path):
    with io.open(path, encoding="utf-8", newline="") as f:
        return f.read()


def signature():
    """Changes whenever a module is added, removed, switched or edited."""
    parts = [core.MODULES_DIR]
    for path in (core.MODULES_STATE, core.MODULE_ORDER, core.MODULE_COLOURS, core.MODULE_TINTS, core.PALETTE_FILE):       # what the picker, the colour pickers and the palette editor write
        try:
            parts.append(os.path.getmtime(path))
        except OSError:
            parts.append(None)
    try:
        names = sorted(os.listdir(core.MODULES_DIR))
    except OSError:
        names = []
    for name in names:
        folder = os.path.join(core.MODULES_DIR, name)
        try:
            for f in sorted(os.listdir(folder)):
                parts.append((name, f, os.path.getmtime(os.path.join(folder, f))))
        except OSError:
            pass
    return tuple(parts)


def _import_web(name, manifest):
    folder = os.path.join(core.MODULES_DIR, name)
    if folder not in sys.path:
        sys.path.insert(0, folder)
    entry = manifest.get("web")
    return importlib.import_module(entry) if entry else None


def refresh(force=False):
    """Follow the files: load the enabled modules again when something changed. Returns True if it did."""
    sig = signature()
    if sig == _state["sig"] and not force:
        return False
    with _lock:
        sig = signature()
        if sig == _state["sig"] and not force:
            return False
        loaded, errors, get, post, api, protected = [], {}, {}, {}, [], set()
        state = core.modules_state()
        for name in core.module_names():
            if not core.module_enabled(name, state):
                continue
            manifest = core.module_manifest(name)
            need = manifest.get("ui", 1)
            if not isinstance(need, int) or need > UI_KIT:      # written for a newer page kit than this one has
                errors[name] = "needs page kit %s, this page has %d" % (need, UI_KIT)
                continue
            try:
                layout = read_layout(name)
            except ValueError as e:
                errors[name] = "layout.json: %s" % e
                continue
            try:
                web = _import_web(name, manifest)
            except Exception as e:      # a broken module must not take the page down with it
                errors[name] = "%s: %s" % (e.__class__.__name__, e)
                sys.stderr.write("module %s not loaded: %s\n" % (name, errors[name]))
                continue
            loaded.append({"name": name, "manifest": manifest, "web": web, "layout": layout})
            if web is not None:
                get.update(getattr(web, "GET", None) or {})
                post.update(getattr(web, "POST", None) or {})
                for k, fn in (getattr(web, "GET_PREFIX", None) or {}).items():     # "/api/events/" answers /api/events/<anything>
                    get["prefix:" + k] = fn
                for k, fn in (getattr(web, "POST_PREFIX", None) or {}).items():
                    post["prefix:" + k] = fn
                protected.update(getattr(web, "PROTECTED", None) or ())
                if callable(getattr(web, "api", None)):
                    api.append(web.api)
        _state.update(sig=sig, loaded=loaded, errors=errors, get=get, post=post, api=api, protected=protected)
        if _state["background"]:
            _start_new()
        return True


def _check_widget(w, where):
    """A widget is a dict with a known "type". Widgets nested inside one are checked too: a row's control, the items of an
    bar, a form field's controls, an infobox row's value, an infobox's actions. (The items of a carousel or a
    list are data, not widgets.)"""
    if not isinstance(w, dict):
        raise ValueError("%s: a widget must be an object" % where)
    t = w.get("type")
    if t not in WIDGETS:
        raise ValueError("%s: unknown widget type %r" % (where, t))
    for key in ("control", "value"):
        if isinstance(w.get(key), dict):
            _check_widget(w[key], "%s.%s" % (where, key))
    for key in (("items",) if t == "bar" else ("actions",) if t == "infobox" else ()):
        if key in w:
            if not isinstance(w[key], list):
                raise ValueError("%s.%s must be a list" % (where, key))
            for i, sub in enumerate(w[key]):
                _check_widget(sub, "%s.%s[%d]" % (where, key, i))
    for key in ("fields", "rows"):          # entries that are not widgets themselves but hold some
        if key in w:
            if not isinstance(w[key], list):
                raise ValueError("%s.%s must be a list" % (where, key))
            for i, sub in enumerate(w[key]):
                if not isinstance(sub, dict):
                    raise ValueError("%s.%s[%d] must be an object" % (where, key, i))
                for k2 in ("control", "value"):
                    if isinstance(sub.get(k2), dict):
                        _check_widget(sub[k2], "%s.%s[%d].%s" % (where, key, i, k2))
                if "controls" in sub:
                    if not isinstance(sub["controls"], list):
                        raise ValueError("%s.%s[%d].controls must be a list" % (where, key, i))
                    for j, c in enumerate(sub["controls"]):
                        if not isinstance(c, dict) or c.get("type") not in CONTROLS:
                            raise ValueError("%s.%s[%d].controls[%d]: a form control is one of %s" % (where, key, i, j, ", ".join(CONTROLS)))


def _check_layout(layout):
    if not isinstance(layout, dict):
        raise ValueError("must be an object")
    for key in layout:
        if key not in _LAYOUT_KEYS:
            raise ValueError("unknown key %r (use %s)" % (key, ", ".join(_LAYOUT_KEYS)))
    if "background" in layout:
        if any(k in layout for k in SECTIONS + ("data",)):
            raise ValueError("a background module can only have a background, no dashboard or settings boxes")
        bg = layout["background"]
        if not isinstance(bg, dict) or bg.get("type") not in BACKGROUND_TYPES:
            raise ValueError("background.type must be one of %s" % ", ".join(BACKGROUND_TYPES))
        return
    for sec in SECTIONS:
        if sec not in layout:
            continue
        boxes = layout[sec]
        if not isinstance(boxes, list):
            raise ValueError("%s must be a list of boxes" % sec)
        for i, box in enumerate(boxes):
            where = "%s[%d]" % (sec, i)
            if not isinstance(box, dict) or not isinstance(box.get("box"), type(u"")) or not box["box"].strip():
                raise ValueError('%s needs a "box" name' % where)
            if not isinstance(box.get("items", []), list):
                raise ValueError("%s.items must be a list" % where)
            for j, w in enumerate(box.get("items", [])):
                _check_widget(w, "%s.items[%d]" % (where, j))
    data = layout.get("data", {})
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    for ns, spec in data.items():
        if not _NAME_RE.match(ns) or not isinstance(spec, dict) or not isinstance(spec.get("url"), type(u"")) or not spec["url"].startswith("/"):
            raise ValueError('data %r needs a name like "players" and a "url" starting with /' % ns)


def read_layout(name):
    """The parsed, checked layout.json of a module, or None when it has none. ValueError says what is wrong."""
    path = os.path.join(core.MODULES_DIR, name, "layout.json")
    if not os.path.exists(path):
        return None
    try:
        layout = json.loads(_read(path))
    except ValueError as e:
        raise ValueError("not valid JSON (%s)" % e)
    _check_layout(layout)
    return layout


def _primary_of(name, manifest):
    """The palette id a module always uses as its primary colour (manifest "primary": a palette id, or one of its own
    colour keys), or None. A module can change it while running through its api hook (d["primary"][name])."""
    want = manifest.get("primary")
    cols = core.module_colours(name)
    if want in cols:
        return cols[want]
    return want if want in core.PALETTE_IDS else None


def _module_file(name, filename):
    """The text of a file in the module's folder (no sub-folders), or "" when it isn't there."""
    if not re.match(r"^[A-Za-z0-9_.-]+$", filename or "") or filename.startswith("."):
        return ""
    try:
        return _read(os.path.join(core.MODULES_DIR, name, filename))
    except (IOError, OSError):
        return ""


def _add_box(out, boxes, sec, key, title, name):
    b = boxes[sec].get(key)
    if b is None:
        b = boxes[sec][key] = {"id": key, "title": "", "mods": [], "items": []}
        out[sec].append(b)
    if not b["title"] and title:
        b["title"] = title
    if name not in b["mods"]:
        b["mods"].append(name)
    return b


def layout():
    """What the page draws, from the enabled modules in picker order:
    {"modules": [names], "dashboard": [box], "settings": [box], "backgrounds": [{"mod", "type", ...}],
     "data": {namespace: {"url", "every", "mod"}}, "primary": {name: palette id}, "colours": {name: {key: id}}}
    box = {"id": lower-case name, "title", "mods": [names], "items": [widget + "mod"]}.
    A module whose module.json has "toggle_box": "appearance" also gets a row with its on/off switch in that Settings box,
    even while it is off (a switched-off module has no layout of its own to put one in): a background-only module uses it."""
    out = {"modules": [], "dashboard": [], "settings": [], "backgrounds": [], "data": {}, "primary": {}, "primary_key": {}, "colours": {}, "tints": {}}
    boxes = dict((sec, {}) for sec in SECTIONS)
    covered = False                       # a fullscreen background above hides every one below it
    loaded = dict((m["name"], m) for m in _state["loaded"])
    for name in core.module_names():
        manifest = core.module_manifest(name) or {}
        toggle_box = manifest.get("toggle_box")
        if toggle_box and core.module_visible(name, manifest):
            b = _add_box(out, boxes, "settings", str(toggle_box).strip().lower(), str(toggle_box).strip().capitalize(), name)
            b["items"].append({"type": "row", "title": core.module_title(name, manifest), "sub": manifest.get("description", ""), "mod": name,
                               "control": {"type": "toggle", "module": name, "label": core.module_title(name, manifest)}})
        m = loaded.get(name)
        if m is None:
            continue
        lay = m.get("layout") or {}
        out["modules"].append(name)
        prim = _primary_of(name, m["manifest"])
        if prim:
            out["primary"][name] = prim
            if m["manifest"].get("primary") in core.module_colours(name):
                out["primary_key"][name] = m["manifest"]["primary"]        # which of its colours it is: that one's background setting counts
        cols = core.module_colours(name)
        if cols:
            out["colours"][name] = cols
            out["tints"][name] = core.module_tints(name)
        if "background" in lay:
            if not covered:
                out["backgrounds"].append(dict(lay["background"], mod=name))
                covered = lay["background"]["type"] == "fullscreen"
            continue
        for sec in SECTIONS:
            for box in lay.get(sec, []):
                b = _add_box(out, boxes, sec, box["box"].strip().lower(), box.get("title"), name)
                for w in box.get("items", []):
                    w = dict(w, mod=name)
                    if w.get("type") == "custom" and w.get("html_file"):         # the markup of a custom widget lives in a file of the module
                        w["html"] = _module_file(name, w.pop("html_file"))
                    b["items"].append(w)
        for ns, spec in (lay.get("data") or {}).items():
            out["data"].setdefault(ns, dict(spec, mod=name))      # the first module to ask for a name keeps it
    out["settings"].sort(key=lambda b: b["id"] == "system")   # System (the module picker, Wi-Fi, update, reboot) is always the last box of Settings, whatever the picker order (a stable sort: the others keep theirs)
    return out


def errors():
    """{module: why} for every module that could not be loaded (a missing or broken layout, a Python error)."""
    return dict(_state["errors"])


def enabled_map():
    """{module: on or off} for every installed module (in every /api answer: the picker's switches and the toggle rows follow it)."""
    state = core.modules_state()
    return dict((n, core.module_enabled(n, state)) for n in core.module_names())


def live_tints():
    """{module: {key: bool}} like live_colours(): whether the background of each colour is coloured (True) or neutral."""
    return dict((m["name"], core.module_tints(m["name"])) for m in _state["loaded"] if m["manifest"].get("colours"))


def live_colours():
    """{module: {key: palette id}} for the enabled modules that have colours of their own (in every /api answer, so a change
    made on another device shows at once)."""
    return dict((m["name"], core.module_colours(m["name"])) for m in _state["loaded"] if m["manifest"].get("colours"))


def _start_new():
    for m in _state["loaded"]:
        web = m["web"]
        if m["name"] not in _state["started"] and web is not None and callable(getattr(web, "start", None)):
            _state["started"].add(m["name"])
            try:
                web.start()
            except Exception as e:
                sys.stderr.write("module %s start() failed: %s\n" % (m["name"], e))


def start_background():
    """The web service calls this once it runs: every enabled module's start() runs, now and for modules switched on later."""
    _state["background"] = True
    _start_new()


def get(name):
    """The imported web entry of an enabled module, or None."""
    for m in _state["loaded"]:
        if m["name"] == name:
            return m["web"]
    return None


def route(method, path):
    """The function of an enabled module that answers this path: an exact path (GET / POST) first, else the longest prefix
    (GET_PREFIX / POST_PREFIX; the function reads the rest of handler.path itself)."""
    table = _state["get"] if method == "GET" else _state["post"]
    fn = table.get(path)
    if fn is None:
        best = ""
        for k in table:
            if k.startswith("prefix:") and path.startswith(k[7:]) and len(path) > len(k) - 7 and len(k) - 7 > len(best):
                best, fn = k[7:], table[k]
    return fn


def protected(path):
    """True for a POST path that an enabled module marked PROTECTED: it needs the page's own header and, when one is
    set, the PIN (rebooting, updating, joining a Wi-Fi network)."""
    return path in _state["protected"]


def apply_api(d, warnings):
    for fn in _state["api"]:
        try:
            fn(d, warnings)
        except Exception as e:
            sys.stderr.write("module api hook failed: %s\n" % e)


def shows_something(name):
    """True when the module's layout.json has a dashboard box, a settings box or a background (also while it is switched off):
    such a module is always in the picker, so it can be put in its place."""
    try:
        lay = json.loads(_read(os.path.join(core.MODULES_DIR, name, "layout.json")))
    except (IOError, OSError, ValueError):
        return False
    return isinstance(lay, dict) and bool(lay.get("dashboard") or lay.get("settings") or lay.get("background"))


def listing():
    """What the module picker shows: every installed module in priority order, on or off. One that can't be switched
    (visible false in its module.json, like the network switcher) is listed too, with "visible": false and no switch on the
    page, so it can still be moved."""
    state = core.modules_state()
    out = []
    for name in core.module_names():
        m = core.module_manifest(name)
        if not core.module_visible(name, m) and not shows_something(name):
            continue                       # a module with no box and no background (a plain service) has nothing to move
        out.append({"name": name, "visible": core.module_visible(name, m), "title": core.module_title(name, m), "description": m.get("description", ""),
                    "note": m.get("note", ""), "enabled": core.module_enabled(name, state),
                    "default": core.module_default_enabled(m), "error": _state["errors"].get(name)})
    return out


def page_parts():
    """{"css": text, "js": text} of the loaded modules, in picker order: their page.css and page.js (a module only needs
    them for what the standard widgets can't do: custom widgets, hooks, a background). The page of a background module
    that is not drawn (another one is on top of it) is left out."""
    drawn = set(b["mod"] for b in layout()["backgrounds"])
    css, js = [], []
    for m in _state["loaded"]:
        if "background" in (m.get("layout") or {}) and m["name"] not in drawn:
            continue
        folder = os.path.join(core.MODULES_DIR, m["name"])
        paths = dict((f, os.path.join(folder, f)) for f in _PAGE_FILES)
        if os.path.exists(paths["page.css"]):
            css.append("/* module %s */\n%s" % (m["name"], _read(paths["page.css"])))
        if os.path.exists(paths["page.js"]):
            js.append("// module %s\n%s" % (m["name"], _read(paths["page.js"])))
    return {"css": "\n".join(css), "js": "\n".join(js)}
