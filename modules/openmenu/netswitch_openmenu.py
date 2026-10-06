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
# a launch waits until openMenu asks. The answer to a poll also carries short lines of live info for the Dreamcast:
#   NET dcnet|dcnow                               the network calls go to now (dcnet only when it is selected and DreamPi can use it)
#   DCNET ok | DCNET off <why>                    whether DCNET works: why = config (netlink_config.ini not found), disabled ([DCNet] enabled =
#                                                 yes missing), noupdates (/boot/noautoupdates.txt) or inactive (DreamPi is not running the add-on)
#   PLY 2:3 1:1 27:2                              the card's games (slot:players) that someone plays online right now, the most played first
#                                                 (left out when none)
#   EVENT <unix start> <due 0|1> <title>          the DC99 event to show: the one whose reminder is due (due 1), else the soonest (left out when none)
# The module announces itself to the rest of the add-on in module.json ("launcher"): the card's games that are in the online game table
# (GET /openmenu/games, "online": true) and how to start one, so the Online players and DC99 events lists can show a Start button.
# The online players and the table of online games are read from the Online players module's file (core.PLAYERS_CACHE), never from its
# code. Works on Python 3 and 2.7.
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
PLAYERS_FRESH = 300       # the Online players module's list counts as current for this long
PLAYERS_ASK = 45          # a Dreamcast that is polling asks for a new list when the old one is older than this ...
PLAYERS_ASK_EVERY = 30    # ... at most this often
MAX_PLAYING = 16          # games in the PLY line

_lock = threading.Lock()
_state = {"seen": 0.0, "pending": None, "pending_time": 0.0, "launched": None, "launched_time": 0.0, "games": None, "asked": 0.0}


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


# ------------------------------------------------------------------ the online players and the table of online games
def _norm(text):
    return re.sub(r"[^a-z0-9]+", "", (text or u"").lower().replace(u"\u00d7", "x"))


def same_game(a, b):
    """Two spellings of a game: equal, or one inside the other (Sonic Adventure 2 / Sonic Adventure 2 (USA))."""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    return a == b or (min(len(a), len(b)) >= 6 and (a in b or b in a))


def match_game(title, glist):
    """The game on the card that a game title means, or None: the same normalised name first, else the shortest name that contains it
    or is inside it."""
    want = _norm(title)
    if len(want) < 3:
        return None
    exact = [g for g in glist if _norm(g["name"]) == want]
    if exact:
        return exact[0]
    loose = [g for g in glist if len(_norm(g["name"])) >= 3 and (want in _norm(g["name"]) or _norm(g["name"]) in want)]
    loose.sort(key=lambda g: len(_norm(g["name"])))
    return loose[0] if loose else None


def players_file():
    """(players, table, age): who is in a game now and the table of games that work online, as the Online players module last wrote them
    (core.PLAYERS_CACHE). players is [] while the list is older than PLAYERS_FRESH; table is a list of game names that are online or
    work in progress, [] when the table has none, None when there is no table (that module is off or has not read it yet); age is
    the list's age in seconds, None without a file."""
    if not core.module_enabled("players"):
        return [], None, None
    try:
        with open(core.PLAYERS_CACHE) as f:
            data = json.load(f)
        age = time.time() - float(data.get("time") or 0)
        players = [p for p in data.get("players") or [] if isinstance(p, dict) and p.get("player") and p.get("game")] if age <= PLAYERS_FRESH else []
        raw = data.get("games")
        table = [g["name"] for g in raw if isinstance(g, dict) and g.get("name") and g.get("status") in ("online", "wip")] if isinstance(raw, list) and raw else None
        return players, table, age
    except (IOError, OSError, ValueError, TypeError, AttributeError):
        return [], None, None


def is_online(name, table):
    """Does this card game work online? Without a table nothing is known, so every game counts."""
    return table is None or any(same_game(name, t) for t in table)


def playing_now(players):
    """[(slot, count)]: the card's games that the players (players_file()[0]) play online right now, each with how many play it, most first"""
    glist = games()["games"]
    counts = {}
    for p in players:
        g = match_game(p["game"], glist)
        if g and g["slot"] > 0:
            counts[g["slot"]] = counts.get(g["slot"], 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_PLAYING]


def event_line(now):
    """The EVENT line, or None: the event whose reminder is due now (due 1), else the soonest one. Both come from files the DC99 events
    module writes (core.event_reminder(), core.next_event()); nothing when that module is off."""
    if not core.module_enabled("events"):
        return None
    due = core.event_reminder(now)
    ev = due or core.next_event(now)
    if not ev:
        return None
    title = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f]", " ", ev["title"])).strip()[:60]
    return "EVENT %d %d %s" % (int(ev["start"]), 1 if due else 0, title)


def network():
    """'dcnet' when DCNET is the selected network and DreamPi can use it, else 'dcnow'."""
    return "dcnet" if core.tag() == "DCNET" else "dcnow"


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
    lines.append("NET " + network())
    code = core.dcnet_code()
    lines.append("DCNET ok" if code == "ok" else "DCNET off " + code)
    players, _table, age = players_file()
    playing = playing_now(players)
    if playing:
        lines.append("PLY " + " ".join("%d:%d" % kv for kv in playing))
    event = event_line(now)
    if event:
        lines.append(event)
    _ask_for_players(age, now)
    return "\n".join(lines) + "\n"


def _ask_for_players(age, now):
    """A Dreamcast is on the line: have the Online players module read its list again when it is old (core.poke), so the live info is
    current without a page being open. Only when that module is on."""
    if not core.module_enabled("players") or (age is not None and age <= PLAYERS_ASK):
        return
    with _lock:
        if now - _state["asked"] < PLAYERS_ASK_EVERY:
            return
        _state["asked"] = now
    core.poke("players")


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


def games_view():
    """GET /openmenu/games: the card's games, each with "online": whether it is in the table of games that work online (true for all
    when that table is not known, "filtered": false then). The Online players and events lists show Start only for the online ones."""
    table = players_file()[1]
    have = games()
    return {"hash": have.get("hash", ""), "filtered": table is not None,
            "games": [dict(g, online=is_online(g["name"], table)) for g in have["games"]]}


def _games_get(h):
    h.send(json.dumps(games_view()), "application/json")


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
