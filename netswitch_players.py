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

# [{"name": "DC99", "url": "http://.../players.json", "network": "DCNET"}, ...]
# "network" is only the fallback label for entries that don't say which network they are on.
# The defaults are the two feeds openMenu's player list uses: dc99.net's combined status page
# (DCNow!, DCNET and any other network section such as KOSnet) and dreamcast.online's own
# DCNow! feed. Players found in both are listed once.
DEFAULT_SOURCES = [{"name": "DC99", "url": "https://dc99.net/online/dcnet_status.php"},
                   {"name": "Dreamcast.online", "url": "https://dreamcast.online/now/api/users.json"}]
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
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; dreampi-netswitch)", "Accept": "application/json, */*"})
    return urlopen(req, timeout=TIMEOUT).read(MAX_BYTES).decode("utf-8", "replace")


def network_label(text, default=""):
    t = str(text or "").strip()
    low = t.lower()
    if not t:
        return default
    if "dcnet" in low or "flycast" in low:
        return "DCNET"
    if "kosnet" in low or low.startswith("kos"):
        return "KOSnet"
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


def _flag(value):
    return value is True or str(value).lower() in ("true", "1", "yes")


def _user(item, network):
    """One entry of dc99's dreampi.users / dreamcast.online's users, or None when offline."""
    if not isinstance(item, dict) or not _flag(item.get("online")):
        return None
    name = _first(item, ("username", "name"))
    if not name:
        return None
    return {"player": name[:40], "game": _first(item, ("current_game_display", "current_game"))[:60],
            "network": network, "country": _first(item, ("country",))[:3]}


def _section_entry(item, network):
    """One entry of a network section's players/users list. An entry that has an
    "online" field must have it true; players lists (dcnet.players) have none."""
    if not isinstance(item, dict):
        return None
    if "online" in item and not _flag(item.get("online")):
        return None
    name = _first(item, ("username", "name", "player"))
    if not name:
        return None
    geo = item.get("geoloc")
    country = _first(item, ("country",)) or (_first(geo, ("country",)) if isinstance(geo, dict) else "")
    return {"player": name[:40], "game": _first(item, ("current_game_display", "gameName", "current_game", "game", "title"))[:60],
            "network": network, "country": country[:3]}


def parse_sections(data):
    """dc99.net/online/dcnet_status.php lists one section per network at the top level:
    {"dreampi": {"users": [...]}, "dcnet": {"online": bool, "players": [...], "users": [...]}, ...}.
    Every section that holds a list of players is read (so a new network such as KOSnet
    shows up without a code change); the section name gives the network (dreampi/dcnow =
    DCNow!, dcnet = DCNET, kosnet = KOSnet, anything else its own name). A section's
    "players" list wins over its "users" list, as in openMenu's reader (dcnet.users is
    everybody who ever played). Returns (players, info) where info says per section how
    many entries it listed and how many are shown, for the page's diagnostics line."""
    out, info = [], []
    for key, section in data.items():
        if not isinstance(section, dict):
            continue
        lst = section.get("players") if isinstance(section.get("players"), list) else section.get("users")
        if not isinstance(lst, list):
            continue
        network = network_label(key, key)
        shown = []
        if section.get("online") is not False:
            shown = [p for p in (_section_entry(i, network) for i in lst) if p]
        out += shown
        info.append({"section": key, "network": network, "listed": len(lst), "shown": len(shown),
                     "offline": section.get("online") is False})
    return out, info


def parse_dcnow(data):
    """dreamcast.online/now/api/users.json: {"users": [{"username", "country",
    "current_game_display", "online", ...}]} (DCNow! players)."""
    return [p for p in (_user(i, "DCNow!") for i in data.get("users") or []) if p]


def parse_players_info(data, default_network=""):
    """(players, section info) - parse_players() plus what each section of a dc99-style feed contained."""
    if isinstance(data, dict) and any(isinstance(v, dict) and (isinstance(v.get("players"), list) or isinstance(v.get("users"), list))
                                      for v in data.values()):
        return parse_sections(data)
    return parse_players(data, default_network), []


def parse_players(data, default_network=""):
    """Players from whatever shape a status endpoint uses. Understands a list of
    player objects, an object holding such a list under a common key, and games
    that each list their players. Unknown shapes give an empty list."""
    out = []
    if isinstance(data, dict) and any(isinstance(v, dict) and (isinstance(v.get("players"), list) or isinstance(v.get("users"), list))
                                      for v in data.values()):
        return parse_sections(data)[0]
    if isinstance(data, dict) and isinstance(data.get("users"), list) and any(
            isinstance(u, dict) and "username" in u for u in data["users"]):
        return parse_dcnow(data)
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
                try:
                    text = fetch(s["url"])
                except Exception:
                    if not s["url"].startswith("https://"):
                        raise
                    text = fetch("http://" + s["url"][len("https://"):])   # a Pi whose TLS can't reach it
                found, info = parse_players_info(json.loads(text), network_label(s.get("network")))
                for p in found:
                    p["source"] = name
                players += found
                report.append({"name": name, "ok": True, "count": len(found), "error": None, "sections": info})
            except Exception as e:
                report.append({"name": name, "ok": False, "count": 0, "error": str(getattr(e, "reason", None) or e)[:80]})
        by_key, unique = {}, []
        for p in players:                       # the same person can be in two sources: keep one, fill gaps
            key = (p["player"].lower(), p["network"])
            if key not in by_key:
                by_key[key] = p
                unique.append(p)
            else:
                first = by_key[key]
                for field in ("game", "country"):
                    if not first.get(field) and p.get(field):
                        first[field] = p[field]
        players = unique
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
