# DreamPi Netswitch add-on - OPTIONAL "online players" list for the main page.
# Fetches the JSON addresses listed in players_sources.json (for example
# DC99 or Dreamcast.online) and shows player, game and network. Self-contained
# on purpose: to drop the feature, delete this file and page/players.js (the
# web service and the installer cope with both being gone).
# Works on Python 3 and 2.7.
import json
import os
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
# Game lists (sources with "kind": "games" in players_sources.json): which online games exist and how far each one works.
# UNVERIFIED: the address and the field names are a guess, the host could not be reached from the development sandbox.
DEFAULT_GAME_SOURCES = [{"name": "Dreamcast Live", "url": "https://dreamcastlive.net/games.json", "kind": "games"}]
CACHE_SECONDS = 60
WATCH_EVERY = 60          # the background check for favourites (only while there are favourites)
MAX_FAVORITES = 30
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
_cache = {"time": 0, "refreshing": False, "players": [], "sources": [], "games": []}


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


def _all_sources():
    try:
        with open(core.PLAYERS_SOURCES) as f:
            data = json.load(f)
        return [s for s in data if isinstance(s, dict) and str(s.get("url", "")).startswith(("http://", "https://"))]
    except (IOError, OSError, ValueError, TypeError):
        return None


def sources():
    """The player feeds (everything that is not a game list)."""
    found = _all_sources()
    return list(DEFAULT_SOURCES) if found is None else [s for s in found if s.get("kind") != "games"]


def game_sources():
    """The game lists: the "kind": "games" entries of players_sources.json, else the default."""
    found = [s for s in (_all_sources() or []) if s.get("kind") == "games"]
    return found or list(DEFAULT_GAME_SOURCES)


# ---------------------------------------------------------------- the game list and the favourites
_STATUS_KEYS = ("status", "state", "colour", "color", "online", "working", "playable")
_GAME_LIST_KEYS = ("games", "data", "items", "list", "results")


def game_status(value):
    """'online' (green: fully online), 'wip' (work in progress), 'offline' (not online) or 'unknown'."""
    if value is True:
        return "online"
    if value is False:
        return "offline"
    t = str(value or "").strip().lower()
    if not t:
        return "unknown"
    if any(w in t for w in ("wip", "progress", "yellow", "orange", "partial", "beta", "limited")):
        return "wip"
    if any(w in t for w in ("not", "offline", "red", "down", "no", "false", "dead", "closed")):
        return "offline"
    if any(w in t for w in ("green", "online", "work", "full", "yes", "true", "up", "ok", "live")):
        return "online"
    return "unknown"


def parse_games(data):
    """[{"name", "status"}] from a game list: a list of objects (name/title + a status/colour field), an object holding
    such a list, or a {"Game": "status"} mapping. Unknown shapes give an empty list."""
    out = []
    if isinstance(data, dict):
        for key in _GAME_LIST_KEYS:
            if isinstance(data.get(key), list):
                return parse_games(data[key])
        for name, v in data.items():
            if isinstance(v, (_TEXT, bool)):
                out.append({"name": str(name)[:60], "status": game_status(v)})
            elif isinstance(v, dict) and not isinstance(v.get("name"), _TEXT):
                out.append({"name": str(name)[:60], "status": game_status(_first(v, _STATUS_KEYS) or v.get("online"))})
        return out
    if isinstance(data, list):
        for item in data:
            if isinstance(item, _TEXT) and item.strip():
                out.append({"name": item.strip()[:60], "status": "unknown"})
            elif isinstance(item, dict):
                name = _first(item, ("name", "title", "game", "game_name"))
                if name:
                    raw = next((item[k] for k in _STATUS_KEYS if k in item and item[k] not in (None, "")), "")
                    out.append({"name": name[:60], "status": game_status(raw)})
    return out


def _norm(text):
    return " ".join(str(text or "").lower().split())


def same_game(a, b):
    """Two spellings of a game: equal, or one inside the other (Phantasy Star Online / Phantasy Star Online Ver.2)."""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    return a == b or (min(len(a), len(b)) >= 6 and (a in b or b in a))


def clean_names(raw):
    out, seen = [], set()
    for item in raw if isinstance(raw, list) else []:
        n = " ".join(str(item).split())[:60]
        if n and n.lower() not in seen and len(out) < MAX_FAVORITES:
            seen.add(n.lower())
            out.append(n)
    return out


def favorites():
    try:
        with open(core.PLAYERS_FAVORITES) as f:
            data = json.load(f)
        return {"games": clean_names(data.get("games")), "players": clean_names(data.get("players"))}
    except (IOError, OSError, ValueError, AttributeError):
        return {"games": [], "players": []}


def save_favorites(data):
    data = data if isinstance(data, dict) else {}
    cleaned = {"games": clean_names(data.get("games")), "players": clean_names(data.get("players"))}
    tmp = core.PLAYERS_FAVORITES + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cleaned, f)
    os.rename(tmp, core.PLAYERS_FAVORITES)
    write_watch()
    return cleaned


def watch_result(players, favs):
    """Which favourites are online: games = the favourite games somebody plays, friends = the favourite players that are online."""
    games = [g for g in favs["games"] if any(same_game(g, p.get("game")) for p in players)]
    friends = [n for n in favs["players"] if any(_norm(n) == _norm(p["player"]) for p in players)]
    return {"games": games, "friends": friends}


def write_watch():
    """Tell the LED service (a file, no socket) which favourites are online, from the cached list."""
    with _lock:
        have, players = _cache["time"], list(_cache["players"])
    result = watch_result(players, favorites()) if have else {"games": [], "friends": []}
    result["time"] = int(time.time())
    tmp = core.PLAYERS_WATCH + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(result, f)
        os.rename(tmp, core.PLAYERS_WATCH)
    except (IOError, OSError):
        pass


def refresh():
    """Fetch every source now and replace the cache."""
    with _lock:
        if _cache["refreshing"]:
            return
        _cache["refreshing"] = True
    players, report, games = [], [], []
    try:
        for s in game_sources():
            name = str(s.get("name") or s["url"])[:30]
            try:
                try:
                    text = fetch(s["url"])
                except Exception:
                    if not s["url"].startswith("https://"):
                        raise
                    text = fetch("http://" + s["url"][len("https://"):])
                found = parse_games(json.loads(text))
                games += found
                report.append({"name": name, "ok": True, "count": len(found), "error": None, "kind": "games"})
            except Exception as e:
                report.append({"name": name, "ok": False, "count": 0, "error": str(getattr(e, "reason", None) or e)[:80], "kind": "games"})
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
            _cache.update({"time": int(time.time()), "players": players[:MAX_PLAYERS], "sources": report, "games": games, "refreshing": False})
        write_watch()


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


# ---------------------------------------------------------------- the page's side (loaded by the web service)
def games_line(players):
    """[{"text": "Game", "n": 3}, {"text": "Other game", "n": 1}], most played first (the carousel shows them joined with a bullet,
    each count in the subtitle colour)."""
    n, order = {}, []
    for p in players:
        if not p.get("game"):
            continue
        if p["game"] not in n:
            n[p["game"]] = 0
            order.append(p["game"])
        n[p["game"]] += 1
    order.sort(key=lambda g: -n[g])          # stable: ties keep their order of appearance
    return [{"text": g, "n": n[g]} for g in order]


def view():
    """The cache plus what the page's widgets show (layout.json binds to these): parts (the counts), games (the carousel),
    list (the players), status (what each source said) and links."""
    out = status()
    players = out.get("players") or []
    bad = [x for x in (out.get("sources") or []) if not x["ok"]]
    nets = (("DCNow!", "switcher.dcnow"), ("DCNET", "switcher.dcnet"))
    if not out["configured"]:
        out["parts"] = [{"text": "%s -" % n, "colour": c} for n, c in nets]
        out["games"] = ["No player list source is set up"]
        out["list"] = []
        out["status"] = "Add the JSON address of a status page to players_sources.json (see the README), or use the links."
    elif not out.get("time"):
        out["parts"] = [{"text": "%s -" % n, "colour": c} for n, c in nets]
        out["games"] = ["Loading..."]
        out["list"] = []
        out["status"] = ""
    else:
        out["parts"] = [{"text": "%s %d" % (n, len([p for p in players if p["network"] == n])), "colour": c} for n, c in nets]
        out["games"] = games_line(players) or ["Nobody is in a game" if players else "Nobody is online"]
        out["list"] = [{"title": p["player"], "sub": p.get("game") or "(Idle)", "tag": p.get("network") or "",
                        "colour": dict(nets).get(p.get("network"), "")} for p in players]
        detail = []
        for x in out.get("sources") or []:
            if x["ok"]:
                sec = x.get("sections")
                detail.append("%s: %s" % (x["name"], ", ".join("%s %d%s%s" % (v["section"], v["shown"], "/%d" % v["listed"] if v["listed"] != v["shown"] else "",
                                                                         " (offline)" if v.get("offline") else "") for v in sec) if sec else x["count"]))
        out["status"] = "; ".join("%s: %s" % (x["name"], x["error"]) for x in bad) + ("  \u00b7  " if bad and detail else "") + "  \u00b7  ".join(detail)
    out["retry"] = bool(out["configured"] and (not out.get("time") or out.get("refreshing")))      # ask again soon while it is loading
    return out


STATUS_NOTE = {"wip": "work in progress", "offline": "not online yet", "unknown": ""}


def game_choices(favs=None):
    """The games to pick from: the game list (green = fully online, work in progress; the others are shown greyed out so it is
    clear they are not online) plus games somebody is playing right now that the list doesn't have."""
    with _lock:
        listed, players = list(_cache["games"]), list(_cache["players"])
    seen, out = set(), []
    for g in listed:
        if g["name"].lower() in seen:
            continue
        seen.add(g["name"].lower())
        out.append({"value": g["name"], "label": g["name"], "status": g["status"]})
    for p in players:
        g = p.get("game")
        if g and g.lower() not in seen and not any(same_game(g, x["value"]) for x in out):
            seen.add(g.lower())
            out.append({"value": g, "label": g, "status": "playing"})
    rank = {"online": 0, "playing": 0, "unknown": 1, "wip": 2, "offline": 3}
    out.sort(key=lambda c: (rank.get(c["status"], 1), c["label"].lower()))
    for c in out:
        note = "playing now" if c["status"] == "playing" else STATUS_NOTE.get(c["status"], "")
        c["sub"] = note
        c["disabled"] = c.pop("status") == "offline"
    return out


def _favorites_reply():
    """The standard "picker" answer: two groups, the games with a choice list, the players with the names online now."""
    favs = favorites()
    choices = game_choices()
    notes = dict((c["value"], c["sub"]) for c in choices if c["sub"] and c["sub"] != "playing now")
    with _lock:
        players = list(_cache["players"])
    names = sorted(set(p["player"] for p in players), key=lambda n: n.lower())
    return {"groups": [{"key": "games", "label": "Favorite games", "sub": "The LEDs show when someone plays one of them",
                        "items": favs["games"], "choices": choices, "notes": notes, "free": False,
                        "empty": "The game list is not loaded yet"},
                       {"key": "players", "label": "Favorite players", "sub": "The LEDs show when one of them comes online",
                        "items": favs["players"], "free": True,
                        "choices": [{"value": n, "label": n} for n in names], "empty": "Nobody is online; type a name"}],
            "defaults": {"games": [], "players": []},
            "rules": {"min": 1, "max": 40, "per_group": MAX_FAVORITES, "unique": False, "add_label": "Add",
                      "add_title": "Add to {group}", "min_msg": "Type a name",
                      "help": "Pick games from the list (green = fully online, work in progress is marked; games that are not online yet "
                              "can't be picked) or players who are online now, or type a player's name. The LED messages "
                              "'Your game is played' and 'A friend came online' use this list.",
                      "restore": "Remove all"}}


def _get_favorites(h):
    with _lock:
        stale = time.time() - _cache["time"] > CACHE_SECONDS and not _cache["refreshing"]
    if stale:
        t = threading.Thread(target=refresh)
        t.daemon = True
        t.start()
    h.send(json.dumps(_favorites_reply()), "application/json")


def _post_favorites(h):
    try:
        save_favorites(json.loads(h._body(16384).decode("utf-8")))
    except (ValueError, IOError, OSError) as e:
        h.send(str(e), "text/plain; charset=utf-8", status=400)
        return True
    h.send(json.dumps(_favorites_reply()), "application/json")
    return True


_watcher = {"on": False}


def _watch_loop():
    while True:
        try:
            favs = favorites()
            if favs["games"] or favs["players"]:
                with _lock:
                    stale = time.time() - _cache["time"] > WATCH_EVERY
                if stale:
                    refresh()
        except Exception:
            pass
        time.sleep(WATCH_EVERY / 2)


def start():
    """Called once by the web service: keeps the list fresh while there are favourites, so the LEDs work with no page open."""
    if _watcher["on"]:
        return
    _watcher["on"] = True
    t = threading.Thread(target=_watch_loop)
    t.daemon = True
    t.start()


def _get(h):
    h.send(json.dumps(view()), "application/json")


GET = {"/players": _get, "/players/favorites": _get_favorites}
POST = {"/players/favorites": _post_favorites}
