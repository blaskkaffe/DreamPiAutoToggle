# DreamPi Netswitch add-on - the dashboard clock (web service side).
# The middle line is the time in 24-hour or 12-hour (AM/PM) form, the top line is empty or the .beat time, the bottom line is empty
# or a scrolling list of world times; with world time on, the box opens a time zone map. Runs in the web service (Python 3).
import json
import os
import time
from datetime import datetime

try:
    from zoneinfo import ZoneInfo           # Python 3.9+ (needs the system's tz database)
except ImportError:                         # older Python: the cities keep their winter time, without summer time
    ZoneInfo = None

import netswitch_core as core

FORMATS = ("24h", "12h")
LABELS = {"24h": "24-hour", "12h": "12-hour (AM/PM)"}
DEFAULT_FORMAT = "24h"

# (name, time zone, longitude, latitude, standard offset in hours: used when the tz database is not there)
CITIES = (
    ("Los Angeles", "America/Los_Angeles", -118.2, 34.1, -8),
    ("New York", "America/New_York", -74.0, 40.7, -5),
    ("São Paulo", "America/Sao_Paulo", -46.6, -23.5, -3),
    ("London", "Europe/London", -0.1, 51.5, 0),
    ("Berlin", "Europe/Berlin", 13.4, 52.5, 1),
    ("Moscow", "Europe/Moscow", 37.6, 55.8, 3),
    ("Mumbai", "Asia/Kolkata", 72.9, 19.1, 5.5),
    ("Tokyo", "Asia/Tokyo", 139.7, 35.7, 9),
    ("Sydney", "Australia/Sydney", 151.2, -33.9, 10),
    ("Auckland", "Pacific/Auckland", 174.8, -36.8, 12),
)


def _flag(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _format(value):
    value = str(value or "").strip().lower()
    return value if value in FORMATS else DEFAULT_FORMAT


def _legacy():
    """The choice of an older version (clock_mode: 24h, 12h or beat) as a config, or None."""
    try:
        with open(core.CLOCK_MODE) as f:
            old = f.read().strip().lower()
    except (IOError, OSError):
        return None
    return {"format": _format(old), "beat": old == "beat", "world": False}


def read_config():
    """{"format": "24h"|"12h", "beat": bool, "world": bool}; defaults for anything missing."""
    try:
        with open(core.CLOCK_CONFIG) as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        data = _legacy() or {}
    return {"format": _format(data.get("format")), "beat": _flag(data.get("beat")), "world": _flag(data.get("world"))}


def save_config(values):
    """Merge the given keys (format, beat, world) into the saved settings and return them."""
    cfg = read_config()
    if isinstance(values, dict):
        if "format" in values:
            cfg["format"] = _format(values["format"])
        if "beat" in values:
            cfg["beat"] = _flag(values["beat"])
        if "world" in values:
            cfg["world"] = _flag(values["world"])
    tmp = core.CLOCK_CONFIG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f)
    os.rename(tmp, core.CLOCK_CONFIG)
    return cfg


def beats(now=None):
    """Swatch Internet Time: the day in BMT (Biel Mean Time = UTC+1, no summer time) cut into 1000 beats of 86.4 s.
    It is the same everywhere, so it ignores the Pi's own time zone."""
    now = time.time() if now is None else now
    return int(((now + 3600) % 86400) / 86.4) % 1000


def format_time(mode, now=None):
    """The time of day for the Pi's own time zone: "13:05:09" (24h) or "1:05:09 PM" (12h). A mode "beat" is the .beat time ("@041")."""
    now = time.time() if now is None else now
    if mode == "beat":
        return "@%03d" % beats(now)
    local = time.localtime(now)
    if _format(mode) == "12h":
        return "%d:%s" % (int(time.strftime("%I", local)), time.strftime("%M:%S %p", local))
    return time.strftime("%H:%M:%S", local)


def zone_offset(zone, standard, now=None):
    """The UTC offset of a time zone in hours right now (with summer time when the tz database knows it)."""
    now = time.time() if now is None else now
    if ZoneInfo is not None:
        try:
            return datetime.fromtimestamp(now, ZoneInfo(zone)).utcoffset().total_seconds() / 3600.0
        except Exception:
            pass
    return float(standard)


def clock_hm(now, offset, mode):
    """Hours and minutes at an offset, in the chosen form ("21:05" or "9:05 PM")."""
    t = time.gmtime(now + offset * 3600)
    if _format(mode) == "12h":
        return "%d:%s" % (int(time.strftime("%I", t)), time.strftime("%M %p", t))
    return time.strftime("%H:%M", t)


def world(mode, now=None):
    """The cities with their time now: name, text (the time), offset (hours), lon, lat."""
    now = time.time() if now is None else now
    out = []
    for name, zone, lon, lat, std in CITIES:
        off = zone_offset(zone, std, now)
        out.append({"name": name, "text": clock_hm(now, off, mode), "offset": off, "lon": lon, "lat": lat})
    return out


def local_offset(now=None):
    """The Pi's own UTC offset in hours."""
    now = time.time() if now is None else now
    t = time.localtime(now)
    return (t.tm_gmtoff if hasattr(t, "tm_gmtoff") else -time.timezone) / 3600.0


def view(now=None):
    """What the page's widgets show (layout.json binds to these): time (middle), beat (top, empty when off), items (bottom: the
    scrolling list, empty when world time is off), map (the cities for the time zone map, or None)."""
    now = time.time() if now is None else now
    cfg = read_config()
    cities = world(cfg["format"], now) if cfg["world"] else []
    return {"time": format_time(cfg["format"], now), "beat": ".beat @%03d" % beats(now) if cfg["beat"] else "",
            "items": [{"text": c["name"], "n": c["text"]} for c in cities], "world": cfg["world"], "beat_on": cfg["beat"],
            "format": cfg["format"], "map": {"cities": cities, "utc": now, "local": local_offset(now)} if cfg["world"] else None}


def _reply():
    cfg = read_config()
    return {"values": {"format": cfg["format"]},
            "texts": {"clock": "Shown as %s" % LABELS[cfg["format"]]},
            "options": {"formats": [{"value": f, "label": LABELS[f]} for f in FORMATS]}}


def _body(h):
    try:
        body = json.loads(h._body(4096).decode("utf-8"))
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
    save_config({"format": values.get("format")})
    h.send(json.dumps(_reply()), "application/json")
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


GET = {"/clock": _get}
POST = {"/clock": _post, "/clock/beat": _toggle("beat"), "/clock/world": _toggle("world")}


def api(d, warnings):
    d["clock"] = view()
    d.setdefault("primary", {})["clock"] = core.module_colours("clock").get("clock") or "cyan"     # the box follows the colour picked in Settings
