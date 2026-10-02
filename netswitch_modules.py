# DreamPi Netswitch add-on - loads the optional modules for the web service.
#
# A module is a folder in modules/ with a module.json (see netswitch_core.module_manifest()). The web
# service runs the Python part of every *enabled* module (the "web" entry in its manifest) and builds the
# module's page files into the page:
#   page.html  fragments for named slots of page/index.html, written as  <!--slot:NAME-->  sections
#   page.css   added to the page's styles
#   page.js    added to the page's script (it runs after page.js, in the same scope)
# A module's web entry may define
#   GET = {"/path": fn(handler)}    POST = {"/path": fn(handler)}   answer a request itself (handler.send(...)); a
#                                                                    POST function returns True once it has answered
#   api(d, warnings)                add to the /api answer (d is its dict) and to the warning boxes
# Nothing outside this file and the web service knows which modules exist. A module whose folder is missing,
# that is switched off, or whose Python fails to import is simply absent. Works on Python 3 and 2.7.
import importlib
import io
import os
import re
import sys
import threading

import netswitch_core as core

SLOTS = ("main", "about_top", "sections_a", "buttons_rows", "sections_b")   # the @@SLOT:name@@ markers in index.html
_PAGE_FILES = ("page.html", "page.css", "page.js")
_lock = threading.Lock()
_state = {"sig": None, "loaded": [], "errors": {}, "get": {}, "post": {}, "api": []}


def _read(path):
    with io.open(path, encoding="utf-8", newline="") as f:
        return f.read()


def signature():
    """Changes whenever a module is added, removed, switched or edited."""
    parts = [core.MODULES_DIR]
    try:
        parts.append(os.path.getmtime(core.MODULES_STATE))
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
        loaded, errors, get, post, api = [], {}, {}, {}, []
        state = core.modules_state()
        for name in core.module_names():
            if not core.module_enabled(name, state):
                continue
            manifest = core.module_manifest(name)
            try:
                web = _import_web(name, manifest)
            except Exception as e:      # a broken module must not take the page down with it
                errors[name] = "%s: %s" % (e.__class__.__name__, e)
                sys.stderr.write("module %s not loaded: %s\n" % (name, errors[name]))
                continue
            loaded.append({"name": name, "manifest": manifest, "web": web})
            if web is not None:
                get.update(getattr(web, "GET", None) or {})
                post.update(getattr(web, "POST", None) or {})
                if callable(getattr(web, "api", None)):
                    api.append(web.api)
        _state.update(sig=sig, loaded=loaded, errors=errors, get=get, post=post, api=api)
        return True


def get(name):
    """The imported web entry of an enabled module, or None."""
    for m in _state["loaded"]:
        if m["name"] == name:
            return m["web"]
    return None


def route(method, path):
    return (_state["get"] if method == "GET" else _state["post"]).get(path)


def apply_api(d, warnings):
    for fn in _state["api"]:
        try:
            fn(d, warnings)
        except Exception as e:
            sys.stderr.write("module api hook failed: %s\n" % e)


def listing():
    """What the Modules menu shows: every installed module, on or off."""
    state = core.modules_state()
    out = []
    for name in core.module_names():
        m = core.module_manifest(name)
        out.append({"name": name, "title": m.get("title", name), "description": m.get("description", ""),
                    "note": m.get("note", ""), "enabled": core.module_enabled(name, state),
                    "default": bool(m.get("default", True)), "error": _state["errors"].get(name)})
    return out


def page_parts():
    """{"slots": {name: html}, "css": text, "js": text} of the loaded modules, in menu order."""
    slots, css, js = dict((s, "") for s in SLOTS), [], []
    for m in _state["loaded"]:
        folder = os.path.join(core.MODULES_DIR, m["name"])
        paths = dict((f, os.path.join(folder, f)) for f in _PAGE_FILES)
        if os.path.exists(paths["page.html"]):
            for slot, text in re.findall(r"<!--slot:(\w+)-->\n?(.*?)(?=<!--slot:|\Z)", _read(paths["page.html"]), re.S):
                if slot in slots:
                    slots[slot] += text
        if os.path.exists(paths["page.css"]):
            css.append("/* module %s */\n%s" % (m["name"], _read(paths["page.css"])))
        if os.path.exists(paths["page.js"]):
            js.append("// module %s\n%s" % (m["name"], _read(paths["page.js"])))
    return {"slots": slots, "css": "\n".join(css), "js": "\n".join(js)}
