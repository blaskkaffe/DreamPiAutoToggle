# Check-in add-on - the dashboard clock (web service side).
# The middle line is the time in 24-hour, 12-hour or 12-hour AM/PM form, in the common time zone (core.time_zone(), Settings > About;
# the Pi's own when none is set); the top line is empty or the .beat time; the bottom line is empty or a scrolling list of world
# times (cities the user picks, up to 12). With "large" on the time takes the rows that .beat and world time leave free (view()
# "size"). With world time on, a tap opens the cities as a list and a map of the world's time zones. Summer time comes from
# base_tz (zoneinfo, or the system's tz files on older Python). Runs in the web service (Python 3).
import json
import os
import time

import base_core as core
import base_tz as tz
CLOCK_CONFIG = os.path.join(core.BASE_DIR, "clock.json")  # {"format": "24h"|"12h"|"12h-ampm", "beat": bool, "world": bool, "large": bool, "cities": [...]}: the clock module's settings
CLOCK_MODE = os.path.join(core.BASE_DIR, "clock_mode")    # older versions: "24h", "12h" or "beat" (read once to carry the choice over to clock.json)

FORMATS = ("12h", "12h-ampm", "24h")
LABELS = {"12h": "12h", "12h-ampm": "12h am/pm", "24h": "24h"}
DEFAULT_FORMAT = "24h"
MAX_CITIES = 12

CATALOGUE = tz.CITIES              # (name, IANA zone, longitude, latitude, region): the cities to pick from, also the zone list
CITY = dict((c[0], c) for c in CATALOGUE)
DEFAULT_CITIES = ["Los Angeles", "New York", "São Paulo", "London", "Berlin", "Moscow", "Mumbai", "Tokyo", "Sydney", "Auckland"]


def _flag(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _format(value):
    value = str(value or "").strip().lower()
    return value if value in FORMATS else DEFAULT_FORMAT


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
        with open(CLOCK_MODE) as f:
            old = f.read().strip().lower()
    except (IOError, OSError):
        return None
    return {"format": _format(old), "beat": old == "beat", "world": False}


def read_config():
    """{"format": "24h"|"12h"|"12h-ampm", "beat": bool, "world": bool, "large": bool, "zone": the common time zone (read only here),
    "cities": [names]}."""
    try:
        with open(CLOCK_CONFIG) as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        data = _legacy() or {}
    if core.read_file(core.TIME_ZONE) is None and data.get("zone"):      # older installs kept the time zone here: carry it over once
        core.save_time_zone(data.get("zone"))
    return {"format": _format(data.get("format")), "beat": _flag(data.get("beat")), "world": _flag(data.get("world")),
            "large": _flag(data.get("large")), "zone": core.time_zone(), "cities": _cities(data.get("cities"))}


def save_config(values):
    """Merge the given keys (format, beat, world, large, cities) into the saved settings and return them."""
    cfg = read_config()
    if isinstance(values, dict):
        for key, clean in (("format", _format), ("beat", _flag), ("world", _flag), ("large", _flag), ("cities", _cities)):
            if key in values:
                cfg[key] = clean(values[key])
    tmp = CLOCK_CONFIG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(dict((k, v) for k, v in cfg.items() if k != "zone"), f)
    os.rename(tmp, CLOCK_CONFIG)
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
    mode = _format(mode)
    if mode == "24h":
        return time.strftime("%H:%M:%S" if seconds else "%H:%M", t)
    ampm = " %p" if mode == "12h-ampm" else ""
    return "%d:%s" % (int(time.strftime("%I", t)), time.strftime(("%M:%S" if seconds else "%M") + ampm, t))


def format_time(mode, now=None, off=None):
    """The time of day at an offset (default: the Pi's own): "13:05:09" (24h), "1:05:09" (12h) or "1:05:09 PM" (12h-ampm). Mode "beat": "@041"."""
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


def _system_zone():
    """The Pi's own time zone name ("Europe/Stockholm") from /etc/timezone or the /etc/localtime link, or ""."""
    try:
        with open("/etc/timezone") as f:
            name = f.read().strip()
        if name:
            return name
    except (IOError, OSError):
        pass
    try:
        link = os.readlink("/etc/localtime")
        return link.split("zoneinfo/", 1)[1] if "zoneinfo/" in link else ""
    except (IOError, OSError):
        return ""


def here(cfg, now, off):
    """Where the clock's own time zone is on the map: {"name", "lon", "lat", "text"}. The place is the first city in the catalogue that
    has the zone (the picked one, or the Pi's own); a zone that has no city is put in the middle of the band of its winter-time offset,
    so summer time does not move it into the next band."""
    zone = cfg.get("zone") or _system_zone()
    for c in CATALOGUE:
        if c[1] == zone:
            return {"name": c[0], "lon": c[2], "lat": c[3], "text": clock_hm(now, off, cfg["format"])}
    offs = [o for o in (tz.offset(zone, now - k * 91 * 86400) for k in range(5)) if o is not None] if zone else []      # a year of samples
    winter = min(offs) if offs else off
    return {"name": zone or "Here", "lon": max(-180.0, min(180.0, winter / 3600.0 * 15)), "lat": 40.0, "text": clock_hm(now, off, cfg["format"])}


def size(cfg, has_world):
    """How many of the box's three rows the time takes: "" = the middle one, "upper" (top and middle: world time is on, .beat is
    off), "lower" (middle and bottom: .beat is on, world time is off) or "full" (all three: neither is on). Only with "large" on."""
    if not cfg["large"]:
        return ""
    if cfg["beat"] and has_world:
        return ""
    return "lower" if cfg["beat"] else ("upper" if has_world else "full")


def view(now=None):
    """What the page's widgets show (layout.json binds to these): time (middle line), beat (top, empty when off), items (bottom:
    the scrolling list, empty when world time is off), cities (the open box's list), size (see size()), map (for the time zone
    map, or None)."""
    now = time.time() if now is None else now
    cfg = read_config()
    off = clock_offset(cfg, now)
    cities = world(cfg, now) if cfg["world"] else []
    return {"time": format_time(cfg["format"], now, off), "beat": "@%03d .beats" % beats(now) if cfg["beat"] else "",
            "items": [{"text": c["name"], "n": c["text"]} for c in cities],
            "cities": [{"title": c["name"], "tag": c["text"]} for c in cities],
            "world": cfg["world"] and bool(cities), "world_on": cfg["world"], "beat_on": cfg["beat"], "large_on": cfg["large"],
            "size": size(cfg, cfg["world"] and bool(cities)), "format": cfg["format"],
            "map": {"cities": cities, "utc": now, "here": off / 3600.0, "dot": here(cfg, now, off)}
            if cfg["world"] else None}


def _reply():
    cfg = read_config()
    return {"values": {"format": cfg["format"]}, "texts": {"clock": "Shown as %s" % LABELS[cfg["format"]]},
            "options": {"formats": [{"value": f, "label": LABELS[f]} for f in FORMATS]}}


def _cities_reply():
    cfg = read_config()
    full = len(cfg["cities"]) >= MAX_CITIES
    choices = [] if full else [{"value": c[0], "label": c[0], "sub": "%s, %s now" % (c[4], tz.utc_text(tz.offset(c[1]) or 0))}
                               for c in CATALOGUE if tz.offset(c[1]) is not None]
    return {"groups": [{"key": "cities", "label": "Cities", "sub": "Shown with world time on: %d of %d" % (len(cfg["cities"]), MAX_CITIES),
                        "items": cfg["cities"], "choices": choices, "free": False,
                        "empty": "The list is full: remove a city first" if full else "No city matches"}],
            "defaults": {"cities": list(DEFAULT_CITIES)},
            "rules": {"per_group": MAX_CITIES, "unique": True, "add_label": "Add", "add_title": "Add a city",
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
    save_config(dict((k, values[k]) for k in ("format",) if k in values))
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


def _toggle(key):
    def post(h):
        body = _body(h)
        if body is None:
            return True
        save_config({key: body.get("value")})
        h.send(json.dumps(view()), "application/json")
        return True
    return post


GET = {"/clock": _get, "/clock/cities": _get_cities}
POST = {"/clock": _post, "/clock/cities": _post_cities, "/clock/beat": _toggle("beat"), "/clock/world": _toggle("world"),
        "/clock/large": _toggle("large")}


def api(d, warnings):
    d["clock"] = view()
    d.setdefault("primary", {})["clock"] = core.module_colours("clock").get("clock") or "cyan"     # the box follows the colour picked in Settings
