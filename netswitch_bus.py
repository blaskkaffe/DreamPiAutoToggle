# DreamPi Netswitch add-on - connections between modules (the "bus"). Works on Python 3 and 2.7, so the DreamPi hook can use it.
#
# Think LEGO bricks or a modular synthesizer. A module has JACKS, and every jack carries one simple on / off value:
#   OUTPUT  something the module says: "DCNET is selected", "a number was dialed", "the Wi-Fi setup is running".
#   INPUT   something the module can do while it is on: "select DCNET", "show alert A on the LEDs", "start a timer".
# A module never talks to another module. The user plugs CABLES (a line in links.json: "numbers.call_dcnow -> switcher.select_dcnow")
# and every module still works on its own. An input is OFF until something turns it on; it is on while ANY of its cables carries
# "on" (a cable can invert, "on when the output is off"), or while another module has turned it on through the API (set_input).
# A module reacts when its input CHANGES: it is told "on" or "off" once, not over and over.
#
#   module.json  "outputs": [{"id": "dcnet_selected", "label": "DCNET is selected"}],
#                "inputs":  [{"id": "select_dcnet", "label": "Select DCNET", "params": [KNOB ...]}],
#                "io": "netswitch_xyz_io"          the file in the module's folder with the code behind the jacks (below)
#   KNOB         a setting of an input (not a cable): {"key", "label", "type": "select" | "text" | "number", "options": [[value, label] ...],
#                "default"}; the user sets it in Settings > System > Connections and the handler gets it
#   io file      INPUTS  = {"select_dcnet": fn(on, knobs, ctx)}       runs when the input changes (on is True or False)
#                OUTPUTS = {"dcnet_selected": fn() -> bool}           an output that is simply a fact about the module: the bus asks
#                                                                      (about once a second, and after bus.refresh(id)) and passes changes on
#                An output without a function is one the module sets itself: bus.set_output(id, True / False) or bus.pulse(id, seconds).
#                Python 2 and 3, imports only the base (core, bus) and uses files, so ANY process can run it: the web service, the hook
#                inside DreamPi, the buttons service. ctx says who is asking.
#   links.json   {"links": [{"from": "numbers.call_dcnow", "to": "switcher.select_dcnow", "invert": false}], "knobs": {"input id": {...}}}
#   profile.json (next to the code, shipped with the add-on) the app's standard settings: the cables used until the user changes them,
#                and which modules start on.
#
# The state of every jack is kept in files in core.SIGNALS (a directory in /tmp: after a reboot everything is off), so the processes
# agree and nothing needs a server: an output is a file "out.<id>" that exists while it is on; an input has a file "in.<id>.<who>"
# for each thing that holds it on, and "ih.<id>" says the module has been told it is on.
#
# The base has a few jacks of its own, so a module needs nothing else to be heard: the "app" brick (a constant "on", "started", three
# notices, three highlights, three colour changes, two timers).
import json
import os
import re
import sys
import threading
import time

import netswitch_core as core

try:
    _TEXT = basestring  # noqa: F821  (Python 2)
except NameError:
    _TEXT = str

APP = "app"
SLOTS = ("a", "b", "c")
TIMERS = (1, 2)
MAX_LINKS = 64
NOTICE_SECONDS = 30
PULSE_SECONDS = 1.0
_io_cache = {}
_ran = []                      # the inputs that were switched on by the call in progress (what pulse() / set_output() return)
_depth = [0]
MAX_DEPTH = 6                  # a handler that sets an output that ...: stop after this many


# ---------------------------------------------------------------- what exists
def _param(p):
    """One knob declaration made safe, or None."""
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
    return {"id": "%s.%s" % (module, d["id"]), "module": module, "module_title": title, "label": str(d["label"]), "params": params}


def _valid_declaration(d):
    return isinstance(d, dict) and isinstance(d.get("id"), _TEXT) and re.match(r"^[a-z][a-z0-9_]*$", d["id"]) and d.get("label")


def _colour_targets():
    """[["module.key", "Module: key"]]: the colours the loaded modules have."""
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
    """The base's own jacks (the "app" brick)."""
    palette = [[c["id"], c["name"]] for c in core.colours()]
    targets, boxes = _colour_targets(), _dashboard_boxes()
    outputs = [{"id": "on", "label": "Always on"}, {"id": "started", "label": "The add-on has just started"}]
    inputs = []
    for s in SLOTS:
        label = s.upper()
        inputs.append({"id": "notice_" + s, "label": "Show notice " + label, "params": [
            {"key": "text", "label": "Text", "type": "text", "default": "Hello"},
            {"key": "seconds", "label": "For how many seconds", "type": "number", "default": NOTICE_SECONDS}]})
        if boxes:
            inputs.append({"id": "highlight_" + s, "label": "Make a box stand out " + label, "params": [
                {"key": "box", "label": "Which box", "type": "select", "options": boxes, "default": boxes[0][0]},
                {"key": "why", "label": "Why (shown on the box)", "type": "text", "default": "Raised by a connection"}]})
        if targets:
            inputs.append({"id": "colour_" + s, "label": "Change a colour " + label, "params": [
                {"key": "target", "label": "Which", "type": "select", "options": targets, "default": targets[0][0]},
                {"key": "colour", "label": "To", "type": "select", "options": palette, "default": palette[0][0]}]})
    for n in TIMERS:
        inputs.append({"id": "timer%d_start" % n, "label": "Start timer %d" % n,
                       "params": [{"key": "seconds", "label": "Runs for how many seconds", "type": "number", "default": 10}]})
        outputs.append({"id": "timer%d_running" % n, "label": "Timer %d is running" % n})
    return ([_item(APP, "Add-on", d) for d in outputs], [_item(APP, "Add-on", d) for d in inputs])


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


# ---------------------------------------------------------------- cables and knobs
def _clean_value(param, value):
    """A knob value that fits its declaration, or the default."""
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


def clean_links(data, decl=None):
    """The cables made safe: both ends must exist (in an installed module), no repeats."""
    decl = decl or declarations(installed=True)
    outs = set(o["id"] for o in decl["outputs"])
    ins = set(i["id"] for i in decl["inputs"])
    out, seen = [], set()
    for link in data if isinstance(data, list) else []:
        if not isinstance(link, dict) or link.get("from") not in outs or link.get("to") not in ins:
            continue
        item = {"from": link["from"], "to": link["to"], "invert": link.get("invert") is True}
        key = (item["from"], item["to"], item["invert"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= MAX_LINKS:
            break
    return out


def clean_knobs(data, decl=None):
    """{input id: {key: value}} for the inputs that have knobs, every knob with a value that fits."""
    decl = decl or declarations(installed=True)
    data = data if isinstance(data, dict) else {}
    out = {}
    for item in decl["inputs"]:
        if not item["params"]:
            continue
        given = data.get(item["id"]) if isinstance(data.get(item["id"]), dict) else {}
        out[item["id"]] = dict((p["key"], _clean_value(p, given.get(p["key"], p.get("default")))) for p in item["params"])
    return out


def _read_file():
    try:
        with open(core.LINKS) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (IOError, OSError, ValueError):
        return None


def default_links(decl=None):
    return clean_links(core.profile().get("links"), decl)


def links(decl=None):
    """The cables in force: the user's (links.json), or the standard ones while there is no such file."""
    data = _read_file()
    return clean_links(data.get("links"), decl) if data is not None else default_links(decl)


def knobs(decl=None):
    """The settings of the inputs (the user's, else the defaults)."""
    data = _read_file()
    return clean_knobs((data or {}).get("knobs"), decl)


def knobs_for(iid):
    return knobs().get(iid, {})


def save_links(data, knob_values=None):
    """Save the cables (and the knobs, when given); the jacks follow at once."""
    decl = declarations(installed=True)
    cleaned = clean_links(data, decl)
    kn = clean_knobs(knob_values if knob_values is not None else knobs(decl), decl)
    tmp = core.LINKS + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"links": cleaned, "knobs": kn}, f, indent=1)
    os.rename(tmp, core.LINKS)
    resync()
    return cleaned


def reset_links():
    """Back to the standard cables and knobs."""
    try:
        os.remove(core.LINKS)
    except OSError:
        pass
    resync()


# ---------------------------------------------------------------- the state of the jacks (files)
def _dir():
    d = core.SIGNALS
    if not os.path.isdir(d):
        try:
            os.makedirs(d)
        except OSError:
            pass
    return d


def _safe(text):
    return re.sub(r"[^A-Za-z0-9_.:-]", "_", str(text))


def _out_path(oid):
    return os.path.join(_dir(), "out." + _safe(oid))


def _ih_path(iid):
    return os.path.join(_dir(), "ih." + _safe(iid))


def _cable(link):
    """The name under which a cable holds its input on."""
    return "c-%s%s" % (_safe(link["from"]), "-inv" if link["invert"] else "")


def _in_path(iid, source):
    return os.path.join(_dir(), "in.%s.%s" % (_safe(iid), _safe(source)))


def _contributions(iid):
    prefix = "in.%s." % _safe(iid)
    try:
        return [n for n in os.listdir(_dir()) if n.startswith(prefix)]
    except OSError:
        return []


def _write(path, text=""):
    tmp = path + ".tmp%d" % os.getpid()
    with open(tmp, "w") as f:
        f.write(text)
    os.rename(tmp, path)


def _remove(path):
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def _until(path):
    try:
        with open(path) as f:
            return float(f.read().strip() or 0)
    except (IOError, OSError, ValueError):
        return 0.0


def input_level(iid):
    """True while the input is on: any cable or API call holds it on."""
    return bool(_contributions(iid))


def _io_module(name):
    """The module's io file (the code behind its jacks), or None."""
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


def _reader(oid):
    """The function that tells an output's value (a computed output), or None (a stored one)."""
    module, _dot, name = oid.partition(".")
    if module == APP:
        return _APP_READERS.get(name)
    if not core.module_enabled(module):
        return None
    io = _io_module(module)
    return (getattr(io, "OUTPUTS", None) or {}).get(name) if io else None


def output_level(oid):
    """True while the output is on."""
    reader = _reader(oid)
    if reader is not None:
        try:
            return bool(reader())
        except Exception:
            return False
    path = _out_path(oid)
    if not os.path.exists(path):
        return False
    until = _until(path)
    return until == 0 or until > time.time()


# ---------------------------------------------------------------- changing them
def _handler(iid):
    """(available, function): available is False while the module is off; function may be None (a level input read from the state)."""
    module, _dot, name = iid.partition(".")
    if module == APP:
        return True, _APP_INPUTS.get(name)
    if not core.module_enabled(module):
        return False, None
    io = _io_module(module)
    return True, (getattr(io, "INPUTS", None) or {}).get(name) if io else None


def _reconcile(iid, ctx):
    """Tell the module when its input changed: on when something holds it on, off when nothing does."""
    level = input_level(iid)
    handled = os.path.exists(_ih_path(iid))
    if level == handled:
        return
    available, fn = _handler(iid)
    if not available:
        return                                     # the module is off: it hears about it when it comes back (poll())
    if level:
        _write(_ih_path(iid))
    else:
        _remove(_ih_path(iid))
    if level:
        _ran.append(iid)
    if fn is None:
        return
    try:
        fn(level, knobs_for(iid), ctx or {})
    except Exception as e:
        _log("%s failed: %s" % (iid, e))


def _run(fn):
    """Run something that may switch inputs; returns the inputs it switched on (handlers may set outputs in turn, a few levels deep)."""
    if _depth[0] >= MAX_DEPTH:
        return []
    outer = _depth[0] == 0
    if outer:
        del _ran[:]
    _depth[0] += 1
    try:
        fn()
    except Exception as e:
        _log("failed: %s" % e)
    finally:
        _depth[0] -= 1
    return list(_ran) if outer else []


def _drive(iid, source, on, ctx):
    path = _in_path(iid, source)
    if on:
        _write(path)
    else:
        _remove(path)
    _reconcile(iid, ctx)


def set_input(iid, on, source, ctx=None):
    """Turn an input on or off from code (a module that wants another module's input on): source is who asks, an input is on while
    any source holds it on. Returns the inputs that were switched on by it."""
    return _run(lambda: _drive(iid, "api-" + _safe(source), bool(on), ctx))


def _propagate(oid, on, ctx):
    for link in links():
        if link["from"] == oid:
            _drive(link["to"], _cable(link), on != link["invert"], ctx)


def set_output(oid, on, ctx=None, until=0.0):
    """Turn an output on or off (the module's own, one without a function in OUTPUTS). The cables carry the change to the inputs.
    until: a time after which it is off again (poll() takes care of it). Returns the inputs this switched on."""
    def go():
        path = _out_path(oid)
        before = os.path.exists(path)
        if on:
            _write(path, "%f" % until if until else "")
        else:
            _remove(path)
        if before != bool(on):
            _propagate(oid, bool(on), ctx)
    return _run(go)


def pulse(oid, seconds=PULSE_SECONDS, ctx=None):
    """An output that is on for a moment (a number was dialed, the add-on started). Pulsing twice quickly counts twice. Returns the
    inputs that were switched on, so the caller can say what happened."""
    def lower():
        if _until(_out_path(oid)) <= time.time() + 0.05:
            set_output(oid, False, ctx)
    if os.path.exists(_out_path(oid)):
        set_output(oid, False, ctx)
    ran = set_output(oid, True, ctx, until=time.time() + seconds)
    timer = threading.Timer(seconds, lower)
    timer.daemon = True
    timer.start()
    return ran


def refresh(oid, ctx=None):
    """An output that is a fact (it has a function in OUTPUTS) may have changed: pass it on if it did."""
    def go():
        reader = _reader(oid)
        if reader is None:
            return
        try:
            now = bool(reader())
        except Exception:
            now = False
        path = _out_path(oid)
        before = os.path.exists(path)
        if now != before:
            if now:
                _write(path)
            else:
                _remove(path)
            _propagate(oid, now, ctx)
    return _run(go)


def resync(ctx=None):
    """Make every input agree with the cables now (after the cables changed, at start): the cables' own holds are rebuilt from the
    outputs' levels."""
    def go():
        for n in _listing():
            if n.startswith("in.") and ".c-" in n:
                _remove(os.path.join(_dir(), n))
        for link in links():
            if output_level(link["from"]) != link["invert"]:
                _write(_in_path(link["to"], _cable(link)))
        decl = declarations()
        for item in decl["inputs"]:
            _reconcile(item["id"], ctx)
        for item in decl["outputs"]:
            if _reader(item["id"]) is not None:
                refresh(item["id"], ctx)
    return _run(go)


def _listing():
    try:
        return os.listdir(_dir())
    except OSError:
        return []


def poll(ctx=None):
    """About once a second (the web service does it): let timers and pulses run out, pass on the outputs that are facts, and tell modules
    that have come back about the inputs that are on."""
    now = time.time()
    for n in _listing():
        if n.startswith("out."):
            until = _until(os.path.join(_dir(), n))
            if until and until <= now:
                set_output(n[4:], False, ctx)
    decl = declarations()
    for item in decl["outputs"]:
        if _reader(item["id"]) is not None:
            refresh(item["id"], ctx)
    for item in decl["inputs"]:
        _run(lambda i=item["id"]: _reconcile(i, ctx))


def levels():
    """{"outputs": {id: bool}, "inputs": {id: bool}} for the page."""
    decl = declarations(installed=True)
    return {"outputs": dict((o["id"], output_level(o["id"])) for o in decl["outputs"]),
            "inputs": dict((i["id"], input_level(i["id"])) for i in decl["inputs"])}


# ---------------------------------------------------------------- the base's own jacks
def _read_notices():
    try:
        with open(core.NOTICES) as f:
            data = json.load(f)
        return [n for n in data if isinstance(n, dict)] if isinstance(data, list) else []
    except (IOError, OSError, ValueError):
        return []


def _write_notices(items):
    _write(core.NOTICES, json.dumps(items))


_seq = [0]


def _notice(on, kn, ctx):
    if not on:
        return
    now = time.time()
    try:
        seconds = float(kn.get("seconds", NOTICE_SECONDS))
    except (TypeError, ValueError):
        seconds = NOTICE_SECONDS
    items = [n for n in _read_notices() if n.get("until", 0) > now][-9:]
    _seq[0] += 1
    items.append({"id": "n%d-%d-%d" % (int(now * 1000), os.getpid(), _seq[0]), "text": str(kn.get("text") or "")[:200],
                  "until": now + max(1.0, seconds)})
    _write_notices(items)


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


def active_highlights():
    """{box id: why}: the boxes whose "make a box stand out" input is on, for the page's "highlight"."""
    out = {}
    kn = knobs()
    for s in SLOTS:
        iid = "app.highlight_" + s
        if input_level(iid) and kn.get(iid, {}).get("box"):
            out[kn[iid]["box"]] = kn[iid].get("why") or ""
    return out


def _colour(on, kn, ctx):
    if not on:
        return
    module, _dot, key = str(kn.get("target") or "").partition(".")
    if core.set_module_colour(module, key, kn.get("colour")) is None:
        raise ValueError("not a colour of a module that is there")


def _timer(n):
    def fn(on, kn, ctx):
        if on:
            try:
                seconds = max(1.0, float(kn.get("seconds", 10)))
            except (TypeError, ValueError):
                seconds = 10.0
            set_output("app.timer%d_running" % n, True, ctx, until=time.time() + seconds)
    return fn


_APP_INPUTS = {}
for _s in SLOTS:
    _APP_INPUTS["notice_" + _s] = _notice
    _APP_INPUTS["colour_" + _s] = _colour
    _APP_INPUTS["highlight_" + _s] = None           # a level input: the page reads it (active_highlights)
for _n in TIMERS:
    _APP_INPUTS["timer%d_start" % _n] = _timer(_n)
_APP_READERS = {"on": lambda: True}
