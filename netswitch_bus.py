# DreamPi Netswitch add-on - connections between modules (the "bus"). Works on Python 3 and 2.7, so the DreamPi hook can use it.
#
# A module can say, in its module.json, which OUTPUTS it has (things that happen: a number was dialed, the network was switched)
# and which INPUTS it takes (things it can do: select a network, start Wi-Fi setup). It never calls another module. What an
# output does is a LINK, a line in links.json that the user makes on the page ("when X happens, do Y"). Every module works
# without the others: an output with no link does nothing, and a link to a module that is not there (or switched off) is skipped.
#
#   module.json  "outputs": [{"id": "call", "label": "A call number was dialed"}],
#                "inputs":  [{"id": "select_network", "label": "Select a network", "summary": "Select {network}", "params": [PARAM ...]}],
#                             ("summary" is the short name of the input with its settings, {key} = the value picked: "Select DCNow!")
#                "io": "netswitch_xyz_io"          the file in the module's folder that has the handlers (below)
#   PARAM        {"key", "label", "type": "select" | "text" | "number", "options": [[value, label] ...], "default"}
#   io file      INPUTS = {"select_network": fn(params, ctx)}; Python 2 and 3, imports only the base (core, bus) and uses files, so
#                ANY process can run it: the web service, the hook inside DreamPi, the buttons service. ctx says who is asking.
#                To make something happen the module calls  netswitch_bus.emit("mymodule.call", {"number": "123"}, ctx).
#   links.json   {"links": [{"from": "numbers.call_dcnow", "to": "switcher.select_network", "params": {"network": "dcnow"}}]}
#   profile.json (next to the code, shipped with the add-on) the app's standard settings: the links used until the user changes them.
#
# The base has a few common inputs of its own, so a module needs nothing else to be heard: "app.notice" (a banner on the page) and
# "app.highlight" (a box on the page stands out), "app.colour" (give a module's colour a palette colour); and the output
# "app.started" (the add-on started).
import json
import os
import re
import sys
import time

import netswitch_core as core

try:
    _TEXT = basestring  # noqa: F821  (Python 2)
except NameError:
    _TEXT = str

APP = "app"
MAX_LINKS = 64
MAX_DEPTH = 4                 # a handler that emits an output that runs a handler ...: stop after this many
NOTICE_SECONDS = 30
_depth = [0]
_seq = [0]                    # makes the ids of notices made in the same millisecond differ
_io_cache = {}


# ---------------------------------------------------------------- what exists
def _param(p):
    """One parameter declaration made safe, or None."""
    if not isinstance(p, dict) or not isinstance(p.get("key"), _TEXT) or not re.match(r"^[a-z][a-z0-9_]*$", p["key"]):
        return None
    kind = p.get("type") if p.get("type") in ("select", "text", "number") else "text"
    out = {"key": str(p["key"]), "label": str(p.get("label") or p["key"]), "type": kind}
    if kind == "select":
        opts = []
        for o in p.get("options") or []:
            if isinstance(o, (list, tuple)) and len(o) == 2 and isinstance(o[0], _TEXT):
                opts.append([str(o[0]), str(o[1])])
        if not opts:
            return None
        out["options"] = opts
    if "default" in p:
        out["default"] = p["default"]
    elif kind == "select":
        out["default"] = out["options"][0][0]
    return out


def _item(module, title, d):
    params = [q for q in (_param(p) for p in d.get("params") or []) if q]
    return {"id": "%s.%s" % (module, d["id"]), "module": module, "module_title": title, "label": str(d["label"]), "params": params,
            "summary": str(d.get("summary") or "")}


def _valid_declaration(d):
    return isinstance(d, dict) and isinstance(d.get("id"), _TEXT) and re.match(r"^[a-z][a-z0-9_]*$", d["id"]) and d.get("label")


def _colour_targets():
    """[["module.key", "Module: key"]]: the colours the loaded modules have (the target of app.colour)."""
    out = []
    for name in core.module_names():
        if not core.module_enabled(name):
            continue
        for key in sorted(core.module_colours(name)):
            out.append(["%s.%s" % (name, key), "%s: %s" % (core.module_title(name), key)])
    return out


def _dashboard_boxes():
    """[["box id", "Module: box"]]: the boxes the loaded modules have on the main page (read from their layout.json)."""
    out = []
    for name in core.module_names():
        if not core.module_enabled(name):
            continue
        try:
            with open(os.path.join(core.MODULES_DIR, name, "layout.json")) as f:
                boxes = json.load(f).get("dashboard") or []
        except (IOError, OSError, ValueError, AttributeError):
            continue
        for box in boxes:
            if isinstance(box, dict) and isinstance(box.get("box"), _TEXT):
                ident = box["box"].lower()
                if ident not in [o[0] for o in out]:
                    out.append([ident, "%s: %s" % (core.module_title(name), box["box"])])
    return out


def common():
    """The base's own outputs and inputs (the "app" module)."""
    palette = [[c["id"], c["name"]] for c in core.colours()]
    targets = _colour_targets()
    inputs = [
        {"id": "notice", "label": "Show a notice on the page",
         "params": [{"key": "text", "label": "Text", "type": "text", "default": "Hello"},
                    {"key": "seconds", "label": "For how many seconds", "type": "number", "default": NOTICE_SECONDS}]},
    ]
    boxes = _dashboard_boxes()
    if boxes:
        inputs.append({"id": "highlight", "label": "Make a box stand out", "summary": "Highlight a box",
                       "params": [{"key": "box", "label": "Which box", "type": "select", "options": boxes, "default": boxes[0][0]},
                                  {"key": "seconds", "label": "For how many seconds", "type": "number", "default": NOTICE_SECONDS},
                                  {"key": "why", "label": "Why (shown on the box)", "type": "text", "default": "Raised by a connection"}]})
    if targets:
        inputs.append({"id": "colour", "label": "Change a colour",
                       "params": [{"key": "target", "label": "Which", "type": "select", "options": targets, "default": targets[0][0]},
                                  {"key": "colour", "label": "To", "type": "select", "options": palette, "default": palette[0][0]}]})
    outputs = [{"id": "started", "label": "The add-on started"}]
    title = "Add-on"
    return ([_item(APP, title, d) for d in outputs], [_item(APP, title, d) for d in inputs])


def declarations(installed=False):
    """{"outputs": [...], "inputs": [...]} of the loaded modules (installed=True: every module that is there, switched off or not)
    and the base's own."""
    outs, ins = [], []
    for name in core.module_names():
        manifest = core.module_manifest(name) or {}
        if not installed and not core.module_enabled(name):
            continue
        title = core.module_title(name, manifest)
        outs.extend(_item(name, title, d) for d in (manifest.get("outputs") or []) if _valid_declaration(d))
        ins.extend(_item(name, title, d) for d in (manifest.get("inputs") or []) if _valid_declaration(d))
    c_out, c_in = common()
    return {"outputs": c_out + outs, "inputs": c_in + ins}


# ---------------------------------------------------------------- links
def _clean_value(param, value):
    """A parameter value that fits its declaration, or the default."""
    kind = param["type"]
    if kind == "select":
        ok = [o[0] for o in param["options"]]
        return value if isinstance(value, _TEXT) and value in ok else param.get("default", ok[0])
    if kind == "number":
        try:
            return min(3600.0, max(0.0, float(value)))
        except (TypeError, ValueError):
            return param.get("default", 0)
    return str(value)[:120] if isinstance(value, _TEXT) else str(param.get("default", ""))


def summary(item, params):
    """A short text for an input with its settings picked: "Select DCNow!" (its "summary" with the values in it, else its label and the values)."""
    shown = {}
    for p in item["params"]:
        value = (params or {}).get(p["key"])
        if p["type"] == "select":
            value = dict(p["options"]).get(value, value)
        shown[p["key"]] = "" if value is None else str(value)
    text = item.get("summary") or ""
    if text:
        for k, v in shown.items():
            text = text.replace("{%s}" % k, v)
        return text
    vals = [v for v in shown.values() if v]
    return item["label"] + (" (%s)" % ", ".join(vals) if vals else "")


def clean_links(data, decl=None):
    """The links made safe: both ends must exist (in an installed module), parameters fit the input, no repeats."""
    decl = decl or declarations(installed=True)
    outs = dict((o["id"], o) for o in decl["outputs"])
    ins = dict((i["id"], i) for i in decl["inputs"])
    out, seen = [], set()
    for link in data if isinstance(data, list) else []:
        if not isinstance(link, dict) or link.get("from") not in outs or link.get("to") not in ins:
            continue
        target = ins[link["to"]]
        given = link.get("params") if isinstance(link.get("params"), dict) else {}
        params = dict((p["key"], _clean_value(p, given.get(p["key"], p.get("default")))) for p in target["params"])
        key = json.dumps([link["from"], link["to"], params], sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append({"from": link["from"], "to": link["to"], "params": params})
        if len(out) >= MAX_LINKS:
            break
    return out


def default_links(decl=None):
    return clean_links(core.profile().get("links"), decl)


def links(decl=None):
    """The links in force: the user's (links.json), or the standard ones while there is no such file."""
    try:
        with open(core.LINKS) as f:
            data = json.load(f)
        return clean_links(data.get("links") if isinstance(data, dict) else None, decl)
    except (IOError, OSError, ValueError):
        return default_links(decl)


def save_links(data):
    cleaned = clean_links(data)
    tmp = core.LINKS + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"links": cleaned}, f, indent=1)
    os.rename(tmp, core.LINKS)
    return cleaned


def reset_links():
    """Back to the standard links."""
    try:
        os.remove(core.LINKS)
    except OSError:
        pass


# ---------------------------------------------------------------- running them
def _io_module(name):
    """The module's io file (the handlers), or None."""
    manifest = core.module_manifest(name) or {}
    modname = manifest.get("io")
    if not isinstance(modname, _TEXT) or not re.match(r"^[A-Za-z0-9_]+$", modname):
        return None
    folder = os.path.join(core.MODULES_DIR, name)
    key = (folder, modname)
    if key not in _io_cache:
        sys.path.insert(0, folder)
        try:
            _io_cache[key] = __import__(modname)
        except Exception as e:
            _io_cache[key] = False
            _log("could not load %s: %s" % (modname, e))
        finally:
            try:
                sys.path.remove(folder)
            except ValueError:
                pass
    return _io_cache[key] or None


def _log(text):
    try:
        core.debug_log("connections: " + text)
    except Exception:
        pass


def _fill(params, data):
    """Text parameters may use what the output tells ("Switched to {network}")."""
    out = {}
    for k, v in params.items():
        if isinstance(v, _TEXT) and "{" in v:
            for dk, dv in (data or {}).items():
                v = v.replace("{%s}" % dk, str(dv))
        out[k] = v
    return out


def run_input(target, params=None, ctx=None):
    """Do one input ("switcher.select_network") now, in this process. Returns {"to", "ok", "result" | "error"}."""
    module, _dot, name = (target or "").partition(".")
    params = params or {}
    ctx = ctx or {}
    try:
        if module == APP:
            handler = _COMMON.get(name)
        elif core.module_enabled(module):
            io = _io_module(module)
            handler = (getattr(io, "INPUTS", None) or {}).get(name) if io else None
        else:
            return {"to": target, "ok": False, "error": "module is off"}
        if handler is None:
            return {"to": target, "ok": False, "error": "no such input here"}
        return {"to": target, "ok": True, "result": handler(params, ctx)}
    except Exception as e:
        _log("%s failed: %s" % (target, e))
        return {"to": target, "ok": False, "error": str(e)}


def emit(output, data=None, ctx=None):
    """Something happened: run every link from this output. Never raises. Returns the results, one per link that ran."""
    results = []
    if _depth[0] >= MAX_DEPTH:
        return results
    _depth[0] += 1
    try:
        for link in links():
            if link["from"] != output:
                continue
            res = run_input(link["to"], _fill(link["params"], data), ctx)
            res["from"] = output
            results.append(res)
            _log("%s -> %s %s" % (output, link["to"], "ok" if res["ok"] else "skipped (%s)" % res.get("error")))
    except Exception as e:
        _log("%s failed: %s" % (output, e))
    finally:
        _depth[0] -= 1
    return results


# ---------------------------------------------------------------- the base's own inputs
def _read_notices():
    try:
        with open(core.NOTICES) as f:
            data = json.load(f)
        return [n for n in data if isinstance(n, dict)] if isinstance(data, list) else []
    except (IOError, OSError, ValueError):
        return []


def _write_notices(items):
    tmp = core.NOTICES + ".tmp"
    with open(tmp, "w") as f:
        json.dump(items, f)
    os.rename(tmp, core.NOTICES)


def _notice(params, ctx):
    now = time.time()
    try:
        seconds = float(params.get("seconds", NOTICE_SECONDS))
    except (TypeError, ValueError):
        seconds = NOTICE_SECONDS
    items = [n for n in _read_notices() if n.get("until", 0) > now][-9:]
    _seq[0] += 1
    items.append({"id": "n%d-%d-%d" % (int(now * 1000), os.getpid(), _seq[0]), "text": str(params.get("text") or "")[:200], "until": now + max(1.0, seconds)})
    _write_notices(items)
    return {"shown": True}


def active_notices():
    """The notices that are showing, as the page's banners ({"id", "text", "post"}); dismissing one POSTs {"id"} to /bus/dismiss."""
    now = time.time()
    return [{"id": n["id"], "text": n.get("text", ""), "post": "/bus/dismiss"} for n in _read_notices()
            if isinstance(n.get("id"), _TEXT) and n.get("until", 0) > now]


def dismiss_notice(ident):
    items = _read_notices()
    keep = [n for n in items if n.get("id") != ident]
    if len(keep) != len(items):
        _write_notices(keep)


def _highlight(params, ctx):
    now = time.time()
    try:
        seconds = float(params.get("seconds", NOTICE_SECONDS))
    except (TypeError, ValueError):
        seconds = NOTICE_SECONDS
    box = str(params.get("box") or "").lower()
    if not box:
        raise ValueError("no box")
    items = _read_highlights()
    items[box] = {"until": now + max(1.0, seconds), "why": str(params.get("why") or "")[:200]}
    _write_highlights(items)
    return {"box": box}


def _read_highlights():
    now = time.time()
    try:
        with open(core.HIGHLIGHTS) as f:
            data = json.load(f)
        return dict((k, v) for k, v in data.items() if isinstance(v, dict) and v.get("until", 0) > now) if isinstance(data, dict) else {}
    except (IOError, OSError, ValueError):
        return {}


def _write_highlights(items):
    tmp = core.HIGHLIGHTS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(items, f)
    os.rename(tmp, core.HIGHLIGHTS)


def active_highlights():
    """{box id: why} of the boxes a link asked to stand out, for the page's "highlight"."""
    return dict((k, v.get("why") or "") for k, v in _read_highlights().items())


def _colour(params, ctx):
    module, _dot, key = str(params.get("target") or "").partition(".")
    if core.set_module_colour(module, key, params.get("colour")) is None:
        raise ValueError("not a colour of a module that is there")
    return {"changed": True}


_COMMON = {"notice": _notice, "highlight": _highlight, "colour": _colour}
