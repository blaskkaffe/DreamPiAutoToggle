# DreamPi Netswitch add-on - DC Bridge module, web side. The bridge is an RP2040 on the Dreamcast's serial port, plugged into the Pi by
# USB (firmware/dcbridge): it gives the Dreamcast a virtual SD card (openMenu's serial VMU saves), a serial PPP link and a virtual W5500
# network adapter. The Pi's side runs in this module's own service, dcbridge-saves (dcbridge_saves/, the disk server, the save history and the
# save manager's web page and JSON API on 127.0.0.1:8085), and dcbridge-net (the routing of the two Dreamcast links).
#
# This file is what the dashboard shows of it:
#   api()            /api "dcbridge": the Dreamcast's link mode, the virtual card and the network links (read from the service by start()'s thread,
#                    so a slow or missing service never slows /api down)
#   GET  /dcbridge-view  the same as JSON
#   GET  /dcbridge/  the save manager page, and GET /dcbridge/api/... its JSON API and downloads
#   POST /dcbridge/api/...   its changes (uploads, labels, deletes, restores: PUT and DELETE come as POST with ?_method=, the page's own header is
#                    needed and, while Settings is locked with the PIN, the PIN)
#   POST /dcbridge-setup/install | /remove   the Install / Uninstall buttons of Settings > DC Bridge: they run system/dcbridge-setup as root in a
#                    transient systemd unit (this service may not write to /etc or /usr); its state and log are shown in the box (PIN when one is set)
# They are passed on to the service on 127.0.0.1, so the saves need no port of their own on the LAN. Works on Python 3.
import http.client
import json
import os
import re
import subprocess
import threading
import time

import base_core as core

HOST, PORT = "127.0.0.1", 8085       # dcbridge-saves.service: serve --host 127.0.0.1 --port 8085
POLL = 2.0                           # seconds between looks at the service
STALE = 8.0                          # a look older than this is not shown as current
MAX_BODY = 131072 + 4096             # a VMU save is 128 KB
ALLOWED = re.compile(r"^/(api/(?!.*\.\.)[A-Za-z0-9._/%+-]*)?$")

SETUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "system", "dcbridge-setup")
INSTALLED = "/etc/systemd/system/dcbridge-saves.service"      # written by dcbridge-setup install, removed by remove: exists = the Pi's side is set up
SETUP_STATUS = core.TMP_PREFIX + ".dcbridge"                  # running / ok / failed, written by dcbridge-setup
SETUP_LOG = core.TMP_PREFIX + ".dcbridge.log"
SETUP_TIMEOUT = 1800                                          # a "running" older than this (the script never started or died) is shown as failed
PROTECTED = ("/dcbridge-setup/install", "/dcbridge-setup/remove")      # run as root: the PIN is asked for when one is set

_seen = {"time": 0.0, "bridge": None, "status": None, "up": False}
_lock = threading.Lock()


def _call(method, path, body=None, headers=None, timeout=3.0):
    """(status, headers, body) from the service, or None when it does not answer."""
    try:
        c = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
        try:
            c.request(method, path, body=body, headers=headers or {})
            r = c.getresponse()
            return r.status, r.getheaders(), r.read()
        finally:
            c.close()
    except (OSError, http.client.HTTPException):
        return None


def _json(path):
    got = _call("GET", path, timeout=3.0)
    if got is None or got[0] != 200:
        return None
    try:
        return json.loads(got[2].decode("utf-8"))
    except ValueError:
        return None


def poll():
    """One look at the service: the bridge's status and the card's."""
    bridge, status = _json("/api/bridge"), _json("/api/status")
    with _lock:
        _seen.update(time=time.time(), bridge=bridge, status=status, up=status is not None)


def _loop():
    while True:
        try:
            poll()
        except Exception:
            pass
        time.sleep(POLL)


def start():
    """Called once by the web service: look at the bridge service every few seconds."""
    t = threading.Thread(target=_loop)
    t.daemon = True
    t.start()


def _ago(t, now):
    if not t:
        return ""
    s = max(0, int(now - t))
    return "%ds ago" % s if s < 60 else "%d min ago" % (s // 60) if s < 3600 else "%d h ago" % (s // 3600)


def installed():
    return os.path.exists(INSTALLED)


def setup_state():
    """idle / running / ok / failed: what dcbridge-setup last did (its status file, which only exists until the next reboot)."""
    text = (core.read_file(SETUP_STATUS) or "").strip()
    if text not in ("running", "ok", "failed"):
        return "idle"
    try:
        if text == "running" and time.time() - os.path.getmtime(SETUP_STATUS) > SETUP_TIMEOUT:
            return "failed"
    except OSError:
        pass
    return text


def setup_log(limit=40):
    """The last lines of the setup's output."""
    text = core.read_file(SETUP_LOG) or ""
    return text.splitlines()[-limit:]


def setup_view():
    """What the Settings box shows: installed, state, text (one line), log (lines)."""
    here, state = installed(), setup_state()
    if state == "running":
        text = "Working... this takes a few minutes (packages are downloaded)."
    elif state == "failed":
        text = "The last install or removal failed. Details below."
    elif here:
        text = "Installed."
    else:
        text = "Not installed: the Pi has no bridge services yet."
    return {"installed": here, "not_installed": not here, "state": state, "running": state == "running", "text": text, "log": setup_log() if state != "idle" else []}


def _spawn(cmd):
    """Run cmd as root outside this service. Replaced by the tests."""
    if os.path.exists("/run/systemd/system"):
        subprocess.Popen(["systemd-run", "--unit=dcbridge-setup-%d" % int(time.time()), "--no-block", "--collect"] + cmd,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        subprocess.Popen(["setsid"] + cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


_setup_lock = threading.Lock()


def start_setup(action):
    """Begin 'install' or 'remove'; returns (started, message). One at a time."""
    with _setup_lock:
        if setup_state() == "running":
            return False, "The bridge setup is already running."
        if action == "install" and installed():
            return False, "The bridge is already installed."
        if action == "remove" and not installed():
            return False, "The bridge is not installed."
        if not os.path.exists(SETUP):
            return False, "The setup script is missing (%s)." % SETUP
        try:
            for path in (SETUP_STATUS, SETUP_LOG):
                if os.path.islink(path):
                    os.remove(path)
            with open(SETUP_STATUS, "w") as f:
                f.write("running\n")                  # the page shows it at once; the script rewrites it when it is done
            with open(SETUP_LOG, "w") as f:
                f.write("")
            _spawn(["sh", SETUP, action, SETUP_STATUS, SETUP_LOG])
        except (OSError, ValueError) as e:
            try:
                os.remove(SETUP_STATUS)
            except OSError:
                pass
            return False, "Could not start the setup (%s)." % e
        core.debug_log("web page: DC Bridge %s started" % action)
        return True, "Installing the bridge..." if action == "install" else "Removing the bridge..."


def _no_board(bridge):
    """Why the service has no status line from the board (it adds what it could find out)."""
    if bridge.get("usb") is False:
        return "Board not on USB (check cable / firmware)"
    devices = bridge.get("devices") or {}
    if bridge.get("usb") and not devices.get("ctl"):
        return "Board on USB, but no udev names"
    if devices.get("ctl"):
        return "Board found, no status from it"
    return "Bridge board not connected"


def view(now=None):
    """What /api carries (the texts and dots the layout shows): {"up", "dreamcast": {state, text}, "card": {state, text, sub}, "net": {state, text}}."""
    now = time.time() if now is None else now
    with _lock:
        seen = dict(_seen)
    fresh = seen["time"] and now - seen["time"] < STALE
    here = installed()
    status, bridge = (seen["status"], seen["bridge"]) if fresh and here else (None, None)
    if status is None:
        gone = {"state": "bad", "text": "The bridge service is not running"} if here else {"state": "unknown", "text": "Not installed (Settings > DC Bridge > Install)"}
        return {"up": False, "dreamcast": gone, "card": {"state": "unknown", "text": "-", "sub": ""}, "net": {"state": "unknown", "text": "-"}}
    fw = (bridge or {}).get("firmware")
    if not fw:
        dreamcast = {"state": "warn", "text": _no_board((bridge or {}))}
    else:
        text = (bridge or {}).get("summary") or "idle"
        under = fw.get("underruns") or 0
        if under:
            text += " (%d timing underruns)" % under
        dreamcast = {"state": "warn" if under else "ok", "text": text}
    queued = int(status.get("pending") or 0)
    sub = ("%d edit%s queued" % (queued, "" if queued == 1 else "s")) if queued else ""
    used = _ago(status.get("last_session"), now)
    if used:
        sub = (sub + " • " if sub else "") + "card used " + used
    card = {"state": "ok" if status.get("connected") else "warn", "text": "Virtual SD card online" if status.get("connected") else "Virtual SD card offline", "sub": sub}
    links = (bridge or {}).get("links") or {}
    parts = []
    for key, label in (("w5500", "W5500"), ("ppp", "PPP")):
        dc = (links.get(key) or {}).get("dreamcast")
        if dc:
            parts.append("%s %s" % (label, dc))
    net = {"state": "ok" if parts else "unknown", "text": ", ".join(parts) if parts else "No Dreamcast on the network links"}
    return {"up": True, "dreamcast": dreamcast, "card": card, "net": net}


def api(d, warnings):
    v = view()
    v["setup"] = setup_view()
    v["installed"] = v["setup"]["installed"]
    d["dcbridge"] = v
    if not v["up"] and v["installed"] and not v["setup"]["running"]:
        warnings.append("DC Bridge: its service is not running (sudo systemctl status dcbridge-saves).")


# ------------------------------------------------------------------ the save manager, passed on

def _reply(h, status, headers, body):
    h.send_response(status)
    for k, v in headers:
        h.send_header(k, v)
    h.send_header("Content-Length", str(len(body)))
    h.send_header("Cache-Control", "no-store")
    h.send_header("X-Frame-Options", "DENY")
    h.send_header("Content-Security-Policy", "frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'")
    h.send_header("X-Content-Type-Options", "nosniff")
    h.end_headers()
    h.wfile.write(body)


def _forward(h, method, path, query, body=None):
    if not ALLOWED.match(path):
        return h.send("Not found\n", "text/plain; charset=utf-8", status=404)
    headers = {}
    if body is not None and h.headers.get("Content-Type"):
        headers["Content-Type"] = h.headers.get("Content-Type")
    got = _call(method, path + ("?" + query if query else ""), body, headers, timeout=15.0)
    if got is None:
        return h.send("The bridge service is not running (sudo systemctl status dcbridge-saves)\n", "text/plain; charset=utf-8", status=502)
    status, rheaders, rbody = got
    keep = [(k, v) for k, v in rheaders if k.lower() in ("content-type", "content-disposition")]
    _reply(h, status, keep, rbody)


def _split(h):
    path, _, query = h.path.partition("?")
    return path[len("/dcbridge"):] or "/", query


def _get(h):
    path, query = _split(h)
    _forward(h, "GET", path, query)


def _post(h):
    """A change: POST, or PUT / DELETE sent as POST with ?_method= (the dashboard's service only takes POST)."""
    path, query = _split(h)
    method = "POST"
    kept = []
    for part in query.split("&"):
        if part.startswith("_method="):
            if part[8:] in ("PUT", "DELETE"):
                method = part[8:]
        elif part:
            kept.append(part)
    body = h._body(MAX_BODY)
    _forward(h, method, path, "&".join(kept), body)
    return True


def _get_view(h):
    out = view()
    out["setup"] = setup_view()
    out["installed"] = out["setup"]["installed"]
    h.send(json.dumps(out), "application/json")


def _post_setup(h):
    """POST /dcbridge-setup/install and /remove: {"started": bool, "message": text, "setup": {...}} like the update."""
    started, message = start_setup("install" if h.path.split("?")[0].endswith("/install") else "remove")
    h.send(json.dumps({"started": started, "message": message, "setup": setup_view()}), "application/json")
    return True


GET = {"/dcbridge/": _get, "/dcbridge-view": _get_view}
GET_PREFIX = {"/dcbridge/": _get}
POST = {"/dcbridge-setup/install": _post_setup, "/dcbridge-setup/remove": _post_setup}
POST_PREFIX = {"/dcbridge/": _post}
