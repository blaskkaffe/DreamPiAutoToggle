# DreamPi Netswitch add-on - OPTIONAL "openMenu link" module (page kit 2: the box is declared in layout.json).
# openMenu (the Dreamcast menu) asks this service two things over the PPP link, and the page shows the result:
#   GET  /openmenu/poll?v=1&n=<games>&h=<hash>   openMenu's heartbeat. Answers "openmenu 1", then "NEED games" when the Pi
#                                                 has no copy of the SD card's game list, and "LAUNCH <product>" once when
#                                                 someone picked a game on the phone page.
#   POST /openmenu/games                          the game list: "#openmenu-games 1 <hash> <count>" then one game per line,
#                                                 tab separated: product, slot, disc, region, folder, name.
# The page uses:
#   GET  /openmenu/view                           the box's data source: status, note, a hash of the game list (small).
#   GET  /openmenu/games                          the game list for the games widget (read again when the hash changes).
#   POST /openmenu/launch  {"product": "..."}     asks openMenu to start that game the next time it polls.
# Events are not handled here: the events module owns them (GET /api/events/upcoming). Nothing is pushed to the Dreamcast:
# a launch waits until openMenu asks. Works on Python 3 and 2.7.
import json
import os
import re
import threading
import time

import netswitch_core as core

SEEN_WINDOW = 15          # seconds: openMenu polls every 3, so it is "connected" while it was heard this recently
LAUNCH_TTL = 60           # a launch nobody collected within this time is dropped
MAX_BODY = 2000000
MAX_GAMES = 5000

_lock = threading.Lock()
_state = {"seen": 0.0, "pending": None, "pending_time": 0.0, "launched": None, "launched_time": 0.0, "games": None}


# ------------------------------------------------------------------ game list
def _clean(text, limit):
    return re.sub(r"[\x00-\x1f]", " ", text).strip()[:limit]


def parse_games(text):
    """(hash, games) from openMenu's upload, or None when it isn't one."""
    lines = text.splitlines()
    if not lines or not lines[0].startswith("#openmenu-games 1 "):
        return None
    parts = lines[0].split()
    if len(parts) < 3:
        return None
    games, seen = [], set()
    for line in lines[1:]:
        f = line.split("\t")
        if len(f) < 6 or not f[0].strip():
            continue
        product = _clean(f[0], 11)
        if not re.match(r"^[A-Za-z0-9_-]+$", product):
            continue
        try:
            slot = int(f[1])
        except ValueError:
            slot = 0
        key = (product, f[2])
        if key in seen:
            continue
        seen.add(key)
        games.append({"product": product, "slot": slot, "disc": _clean(f[2], 7), "region": _clean(f[3], 3),
                      "folder": _clean(f[4], 120), "name": _clean(f[5], 100)})
        if len(games) >= MAX_GAMES:
            break
    games.sort(key=lambda g: (g["name"].lower(), g["disc"]))
    return parts[2], games


def _load_games():
    try:
        with open(core.OPENMENU_GAMES) as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("games"), list):
            return data
    except (IOError, OSError, ValueError):
        pass
    return {"hash": "", "time": 0, "games": []}


def games():
    with _lock:
        if _state["games"] is None:
            _state["games"] = _load_games()
        return _state["games"]


def save_games(h, glist):
    data = {"hash": h, "time": int(time.time()), "games": glist}
    tmp = core.OPENMENU_GAMES + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.rename(tmp, core.OPENMENU_GAMES)
    with _lock:
        _state["games"] = data


# ------------------------------------------------------------------ the launch handshake
def poll_reply(headers_query):
    """What openMenu is told. headers_query: the query string of GET /openmenu/poll."""
    q = dict(p.split("=", 1) for p in headers_query.split("&") if "=" in p)
    now = time.time()
    lines = ["openmenu 1"]
    with _lock:
        _state["seen"] = now
        if _state["pending"] and now - _state["pending_time"] > LAUNCH_TTL:
            _state["pending"] = None
        if _state["pending"]:
            lines.append("LAUNCH " + _state["pending"])
            _state["launched"], _state["launched_time"] = _state["pending"], now
            _state["pending"] = None
    have = games()
    if q.get("h", "") != have.get("hash", "") or not have["games"]:
        lines.append("NEED games")
    return "\n".join(lines) + "\n"


def request_launch(product):
    """(ok, message). The product must be on the card and openMenu must have been heard lately."""
    if not any(g["product"] == product for g in games()["games"]):
        return False, "That game is not on the card's list."
    with _lock:
        if time.time() - _state["seen"] > SEEN_WINDOW:
            return False, "The Dreamcast is not connected to openMenu right now."
        _state["pending"], _state["pending_time"] = product, time.time()
    core.debug_log("openMenu link: launch %s requested" % product)
    return True, "Sent. The Dreamcast starts it within a few seconds."


def _name(product):
    for g in games()["games"]:
        if g["product"] == product:
            return g["name"]
    return product


def view():
    """GET /openmenu/view: what the box binds to (title, note, connected, count, hash)."""
    have = games()
    now = time.time()
    with _lock:
        seen_ago = int(now - _state["seen"]) if _state["seen"] else None
        pending = _state["pending"] if _state["pending"] and now - _state["pending_time"] <= LAUNCH_TTL else None
        launched = _state["launched"] if now - _state["launched_time"] <= 30 else None
    connected = seen_ago is not None and seen_ago <= SEEN_WINDOW
    count = len(have["games"])
    if pending:
        note = "Waiting for the Dreamcast to start %s..." % _name(pending)
    elif launched:
        note = "Starting %s on the Dreamcast." % _name(launched)
    elif not count:
        note = "No game list yet. It arrives when openMenu connects with DC Now! on."
    else:
        note = "%d games on the card" % count
    return {"title": "Connected" if connected else ("Not connected" if seen_ago is not None else "Not seen yet"),
            "connected": connected, "note": note, "count": count, "hash": have.get("hash", ""), "busy": bool(pending)}


# ---------------------------------------------------------------- the web service's side
def _poll(h):
    query = h.path.split("?", 1)[1] if "?" in h.path else ""
    h.send(poll_reply(query), "text/plain; charset=utf-8")


def _view_get(h):
    h.send(json.dumps(view()), "application/json")


def _games_get(h):
    h.send(json.dumps({"hash": games().get("hash", ""), "games": games()["games"]}), "application/json")


def _games_post(h):
    raw = h._body(MAX_BODY)
    parsed = parse_games(raw.decode("utf-8", "replace"))
    if parsed is None:
        h.send("bad game list\n", "text/plain; charset=utf-8", status=400)
        return True
    save_games(parsed[0], parsed[1])
    core.debug_log("openMenu link: %d games received" % len(parsed[1]))
    h.send("ok\n", "text/plain; charset=utf-8")
    return True


def _launch_post(h):
    try:
        product = str(json.loads(h._body(2000).decode("utf-8", "replace")).get("product", ""))
    except (ValueError, AttributeError):
        product = ""
    ok, message = request_launch(product)
    h.send(json.dumps({"ok": ok, "message": message}), "application/json", status=200 if ok else 409)
    return True


GET = {"/openmenu/poll": _poll, "/openmenu/view": _view_get, "/openmenu/games": _games_get}
POST = {"/openmenu/games": _games_post, "/openmenu/launch": _launch_post}
