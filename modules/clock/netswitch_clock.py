# DreamPi Netswitch add-on - the dashboard clock (web service side).
# The middle line is the time in 24-hour or 12-hour (AM/PM) form, in the Pi's own time zone or one picked in Settings; the top line
# is empty or the .beat time; the bottom line is empty or a scrolling list of world times (cities the user picks, up to 12). With
# world time on, a tap opens the cities as a list and a map of the world's time zones. Summer time comes from netswitch_tz (zoneinfo,
# or the system's tz files on older Python). Runs in the web service (Python 3).
import json
import os
import time

import netswitch_core as core
import netswitch_tz as tz

FORMATS = ("24h", "12h")
LABELS = {"24h": "24-hour", "12h": "12-hour (AM/PM)"}
DEFAULT_FORMAT = "24h"
MAX_CITIES = 12
ZONES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zones.json")   # the map's areas (tools/build_clock_zones.py)

CATALOGUE = tz.CITIES              # (name, IANA zone, longitude, latitude, region): the cities to pick from, also the zone list
CITY = dict((c[0], c) for c in CATALOGUE)
DEFAULT_CITIES = ["Los Angeles", "New York", "São Paulo", "London", "Berlin", "Moscow", "Mumbai", "Tokyo", "Sydney", "Auckland"]
ZONE_CHOICES = tuple(sorted(set(c[1] for c in CATALOGUE))) + ("UTC",)


def _flag(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _format(value):
    value = str(value or "").strip().lower()
    return value if value in FORMATS else DEFAULT_FORMAT


def _zone(value):
    """A zone from the list, or "" = the Pi's own."""
    value = str(value or "").strip()
    return value if value in ZONE_CHOICES else ""


def _cities(value):
    """Known city names, each once, at most MAX_CITIES; anything else (None, not a list): the defaults."""
    if not isinstance(value, list):
        return list(DEFAULT_CITIES)
    out = []
    for n in value:
        if isinstance(n, str) and n in CITY and n not in out:
            out.append(n)
    return out[:MAX_CITIES]


def _legacy():
    """The choice of an older version (clock_mode: 24h, 12h or beat) as a config, or None."""
    try:
        with open(core.CLOCK_MODE) as f:
            old = f.read().strip().lower()
    except (IOError, OSError):
        return None
    return {"format": _format(old), "beat": old == "beat", "world": False}


def read_config():
    """{"format": "24h"|"12h", "beat": bool, "world": bool, "zone": "" (the Pi's own) | IANA name, "cities": [names]}."""
    try:
        with open(core.CLOCK_CONFIG) as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        data = _legacy() or {}
    return {"format": _format(data.get("format")), "beat": _flag(data.get("beat")), "world": _flag(data.get("world")),
            "zone": _zone(data.get("zone")), "cities": _cities(data.get("cities"))}


def save_config(values):
    """Merge the given keys (format, beat, world, zone, cities) into the saved settings and return them."""
    cfg = read_config()
    if isinstance(values, dict):
        for key, clean in (("format", _format), ("beat", _flag), ("world", _flag), ("zone", _zone), ("cities", _cities)):
            if key in values:
                cfg[key] = clean(values[key])
    tmp = core.CLOCK_CONFIG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f)
    os.rename(tmp, core.CLOCK_CONFIG)
    return cfg


def beats(now=None):
    """Swatch Internet Time: the day in BMT (Biel Mean Time = UTC+1, no summer time) cut into 1000 beats of 86.4 s.
    It is the same everywhere, so it ignores every time zone."""
    now = time.time() if now is None else now
    return int(((now + 3600) % 86400) / 86.4) % 1000


def pi_offset(now=None):
    """The Pi's own UTC offset in seconds (its system time zone, with summer time)."""
    now = time.time() if now is None else now
    t = time.localtime(now)
    return t.tm_gmtoff if hasattr(t, "tm_gmtoff") else -(time.altzone if t.tm_isdst > 0 else time.timezone)


def clock_offset(cfg, now=None):
    """The offset (seconds) the clock shows: the picked zone's, or the Pi's own when none is picked or it is unknown here."""
    if cfg.get("zone"):
        off = tz.offset(cfg["zone"], now)
        if off is not None:
            return off
    return pi_offset(now)


def _text(now, off, mode, seconds):
    t = time.gmtime(now + off)
    if _format(mode) == "12h":
        return "%d:%s" % (int(time.strftime("%I", t)), time.strftime("%M:%S %p" if seconds else "%M %p", t))
    return time.strftime("%H:%M:%S" if seconds else "%H:%M", t)


def format_time(mode, now=None, off=None):
    """The time of day at an offset (default: the Pi's own): "13:05:09" (24h) or "1:05:09 PM" (12h). Mode "beat": "@041"."""
    now = time.time() if now is None else now
    if mode == "beat":
        return "@%03d" % beats(now)
    return _text(now, pi_offset(now) if off is None else off, mode, True)


def clock_hm(now, off, mode):
    """Hours and minutes at an offset in seconds, in the chosen form ("21:05" or "9:05 PM")."""
    return _text(now, off, mode, False)


utc_text = tz.utc_text


def world(cfg, now=None):
    """The picked cities with their time now: name, text (the time), offset (hours), lon, lat. A zone this system does not know
    is left out."""
    now = time.time() if now is None else now
    out = []
    for name in cfg["cities"]:
        _n, zone, lon, lat, _r = CITY[name]
        off = tz.offset(zone, now)
        if off is None:
            continue
        out.append({"name": name, "text": clock_hm(now, off, cfg["format"]), "offset": off / 3600.0, "lon": lon, "lat": lat})
    return out


_zones = {"list": None}
_offs = {"key": None, "offs": None}


def map_zones():
    """The map's areas (zones.json): {"top", "bottom", "zones": [{"tz", "p" (outlines), "l" (label points)}]}, or None."""
    if _zones["list"] is None:
        try:
            with open(ZONES_FILE) as f:
                _zones["list"] = json.load(f)
        except (IOError, OSError, ValueError):
            _zones["list"] = {}
    return _zones["list"] or None


def zone_offsets(now=None):
    """The offset (hours) of every map area right now, in the order of zones.json; None for a zone this system lacks.
    Worked out once a minute (offsets only change on the hour or half hour)."""
    now = time.time() if now is None else now
    data = map_zones()
    if not data:
        return []
    key = int(now // 60)
    if _offs["key"] != key:
        out = []
        for z in data["zones"]:
            off = tz.offset(z["tz"], now)
            out.append(None if off is None else off / 3600.0)
        _offs.update(key=key, offs=out)
    return _offs["offs"]


def view(now=None):
    """What the page's widgets show (layout.json binds to these): time (middle line), beat (top, empty when off), items (bottom:
    the scrolling list, empty when world time is off), cities (the open box's list), map (for the time zone map, or None)."""
    now = time.time() if now is None else now
    cfg = read_config()
    off = clock_offset(cfg, now)
    cities = world(cfg, now) if cfg["world"] else []
    return {"time": format_time(cfg["format"], now, off), "beat": ".beat @%03d" % beats(now) if cfg["beat"] else "",
            "items": [{"text": c["name"], "n": c["text"]} for c in cities],
            "cities": [[c["name"], c["text"]] for c in cities],
            "world": cfg["world"] and bool(cities), "world_on": cfg["world"], "beat_on": cfg["beat"], "format": cfg["format"],
            "map": {"cities": cities, "utc": now, "here": off / 3600.0, "offs": zone_offsets(now), "zone": utc_text(off)}
            if cfg["world"] else None}


def _zone_line(cfg, now=None):
    if not cfg["zone"]:
        return "This Pi's own time zone, %s now" % utc_text(pi_offset(now))
    names = [c[0] for c in CATALOGUE if c[1] == cfg["zone"]]
    off = tz.offset(cfg["zone"], now)
    if off is None:
        return "%s is not known on this Pi: its own time zone is used" % cfg["zone"]
    return "%s, %s now (summer and winter time follow the zone)" % (names[0] if names else cfg["zone"], utc_text(off))


def _reply():
    cfg = read_config()
    return {"values": {"format": cfg["format"], "zone": cfg["zone"]},
            "texts": {"clock": "Shown as %s" % LABELS[cfg["format"]], "zone": _zone_line(cfg)},
            "options": {"formats": [{"value": f, "label": LABELS[f]} for f in FORMATS], "zones": tz.zone_options()}}


def _cities_reply():
    cfg = read_config()
    choices = [{"value": c[0], "label": c[0], "group": c[4]} for c in CATALOGUE]
    return {"groups": [{"key": "cities", "label": "Cities", "sub": "Shown with world time on: %d of %d" % (len(cfg["cities"]), MAX_CITIES),
                        "items": cfg["cities"]}],
            "defaults": {"cities": list(DEFAULT_CITIES)},
            "rules": {"per_group": MAX_CITIES, "unique": True, "choices": choices, "add_label": "Add", "add_title": "Add a city",
                      "restore": "Restore", "help": "The cities of the world time list, in this order. Up to %d. Each one "
                      "follows its own summer and winter time." % MAX_CITIES}}


def _body(h):
    try:
        body = json.loads(h._body(8192).decode("utf-8"))
    except (ValueError, IOError, OSError, AttributeError) as e:
        h.send(str(e), "text/plain; charset=utf-8", status=400)
        return None
    return body if isinstance(body, dict) else {}


def _get(h):
    h.send(json.dumps(_reply()), "application/json")


def _post(h):
    body = _body(h)
    if body is None:
        return True
    values = body.get("values") if isinstance(body.get("values"), dict) else {}
    save_config(dict((k, values[k]) for k in ("format", "zone") if k in values))
    h.send(json.dumps(_reply()), "application/json")
    return True


def _get_cities(h):
    h.send(json.dumps(_cities_reply()), "application/json")


def _post_cities(h):
    body = _body(h)
    if body is None:
        return True
    if isinstance(body.get("cities"), list):
        save_config({"cities": body["cities"]})
    h.send(json.dumps(_cities_reply()), "application/json")
    return True


def _get_zones(h):
    data = map_zones()
    if not data:
        return h.send("no map", "text/plain; charset=utf-8", status=404)
    h.send(json.dumps(data, separators=(",", ":")), "application/json")


def _toggle(key):
    def post(h):
        body = _body(h)
        if body is None:
            return True
        save_config({key: body.get("value")})
        h.send(json.dumps(view()), "application/json")
        return True
    return post


GET = {"/clock": _get, "/clock/cities": _get_cities, "/clock/zones": _get_zones}
POST = {"/clock": _post, "/clock/cities": _post_cities, "/clock/beat": _toggle("beat"), "/clock/world": _toggle("world")}


def api(d, warnings):
    d["clock"] = view()
    d.setdefault("primary", {})["clock"] = core.module_colours("clock").get("clock") or "cyan"     # the box follows the colour picked in Settings
