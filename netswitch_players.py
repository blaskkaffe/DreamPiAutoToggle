# DreamPi Netswitch add-on - OPTIONAL "online players" list for the main page.
# Fetches the JSON addresses listed in players_sources.json (for example
# DC99 or Dreamcast.online) and shows player, game and network. Self-contained
# on purpose: to drop the feature, delete this file and page/players.js (the
# web service and the installer cope with both being gone).
# Works on Python 3 and 2.7.
import json
import threading
import time

try:
    from urllib.request import urlopen, Request
except ImportError:   # Python 2.7
    from urllib2 import urlopen, Request

import netswitch_core as core

# [{"name": "DC99", "url": "https://.../players.json", "network": "DCNET"}, ...]
# "network" is only the fallback label for entries that don't say which network they are on.
DEFAULT_SOURCES = []
CACHE_SECONDS = 60
TIMEOUT = 8
MAX_BYTES = 1000000
MAX_PLAYERS = 300

LINKS = [
    ("DC99", "https://dc99.net/"),
    ("Dreamcast.online", "https://dreamcast.online/"),
    ("DCNET status", "https://dcnet.flyca.st/status/games.html"),
    ("Dreamcast Live", "https://dreamcastlive.net/"),
    ("DreamPi on GitHub", "https://github.com/Kazade/dreampi"),
]

_NAME_KEYS = ("name", "player", "username", "user", "nick", "nickname", "gamertag", "handle")
_GAME_KEYS = ("game", "game_name", "gamename", "title", "game_title", "playing")
_NET_KEYS = ("network", "net", "service", "server", "platform")
_LIST_KEYS = ("players", "online", "users", "data", "results", "items", "list", "sessions")
_NESTED_PLAYERS = ("players", "users", "online", "members")

try:
    _TEXT = basestring  # noqa: F821  (Python 2: json gives unicode)
except NameError:
    _TEXT = str

_lock = threading.Lock()
_cache = {"time": 0, "refreshing": False, "players": [], "sources": []}


def fetch(url):
    """JSON text of a URL. Replaced by the tests."""
    req = Request(url, headers={"User-Agent": "dreampi-netswitch", "Accept": "application/json"})
    return urlopen(req, timeout=TIMEOUT).read(MAX_BYTES).decode("utf-8", "replace")


def network_label(text, default=""):
    t = str(text or "").strip()
    low = t.lower()
    if not t:
        return default
    if "dcnet" in low or "flycast" in low:
        return "DCNET"
    if "dcnow" in low or "dreampi" in low or "dreamcast now" in low:
        return "DCNow!"
    return t[:20]


def _first(item, keys):
    for k in keys:
        v = item.get(k)
        if isinstance(v, (_TEXT, int)) and str(v).strip():
            return str(v).strip()
        if isinstance(v, dict):                      # {"game": {"name": "..."}}
            inner = _first(v, ("name", "title"))
            if inner:
                return inner
    return ""


def _player(item, game="", network=""):
    if isinstance(item, _TEXT):
        return {"player": item.strip(), "game": game, "network": network} if item.strip() else None
    if not isinstance(item, dict):
        return None
    name = _first(item, _NAME_KEYS)
    if not name:
        return None
    return {"player": name[:40], "game": (_first(item, _GAME_KEYS) or game)[:60],
            "network": network_label(_first(item, _NET_KEYS), network)}


def parse_players(data, default_network=""):
    """Players from whatever shape a status endpoint uses. Understands a list of
    player objects, an object holding such a list under a common key, and games
    that each list their players. Unknown shapes give an empty list."""
    out = []
    if isinstance(data, dict):
        games = data.get("games")
        if isinstance(games, list) and games and all(isinstance(g, dict) for g in games):
            for g in games:                          # [{"name": "Game", "players": ["a", "b"]}, ...]
                gname = _first(g, _GAME_KEYS + ("name",))
                gnet = network_label(_first(g, _NET_KEYS), default_network)
                for key in _NESTED_PLAYERS:
                    if isinstance(g.get(key), list):
                        out += [p for p in (_player(i, gname, gnet) for i in g[key]) if p]
            if out:
                return out
        for key in _LIST_KEYS:
            if isinstance(data.get(key), list):
                return parse_players(data[key], default_network)
        # {"Game name": ["player", ...]}
        if data and all(isinstance(v, list) for v in data.values()):
            for gname, plist in data.items():
                out += [p for p in (_player(i, str(gname), default_network) for i in plist) if p]
        return out
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and any(isinstance(item.get(k), list) for k in _NESTED_PLAYERS) and not _first(item, _NAME_KEYS):
                gname = _first(item, _GAME_KEYS + ("name",))   # a game with a player list inside
                gnet = network_label(_first(item, _NET_KEYS), default_network)
                for key in _NESTED_PLAYERS:
                    if isinstance(item.get(key), list):
                        out += [p for p in (_player(i, gname, gnet) for i in item[key]) if p]
            else:
                p = _player(item, "", default_network)
                if p:
                    out.append(p)
    return out


def sources():
    try:
        with open(core.PLAYERS_SOURCES) as f:
            data = json.load(f)
        found = [s for s in data if isinstance(s, dict) and str(s.get("url", "")).startswith(("http://", "https://"))]
        return found
    except (IOError, OSError, ValueError, TypeError):
        return list(DEFAULT_SOURCES)


def refresh():
    """Fetch every source now and replace the cache."""
    with _lock:
        if _cache["refreshing"]:
            return
        _cache["refreshing"] = True
    players, report = [], []
    try:
        for s in sources():
            name = str(s.get("name") or s["url"])[:30]
            try:
                found = parse_players(json.loads(fetch(s["url"])), network_label(s.get("network")))
                for p in found:
                    p["source"] = name
                players += found
                report.append({"name": name, "ok": True, "count": len(found), "error": None})
            except Exception as e:
                report.append({"name": name, "ok": False, "count": 0, "error": str(getattr(e, "reason", None) or e)[:80]})
        order = {"DCNow!": 0, "DCNET": 1}
        players.sort(key=lambda p: (order.get(p["network"], 2), p["network"], p["game"].lower(), p["player"].lower()))
    finally:
        with _lock:
            _cache.update({"time": int(time.time()), "players": players[:MAX_PLAYERS], "sources": report, "refreshing": False})


def status():
    """The cached list for the page; a refresh runs in the background when it is old."""
    with _lock:
        stale = time.time() - _cache["time"] > CACHE_SECONDS and not _cache["refreshing"]
    if stale:
        t = threading.Thread(target=refresh)
        t.daemon = True
        t.start()
    with _lock:
        out = dict(_cache)
    out["configured"] = bool(sources())
    out["links"] = LINKS
    return out
