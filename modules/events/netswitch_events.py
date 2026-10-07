# DreamPi Netswitch add-on - DC99 events: the community calendar of dc99.net on the dashboard, with reminders (web service side).
#
# Where the data comes from (checked in a browser, October 2026): https://dc99.net/community/ has no events API. The calendar is
# drawn by a script in that page from a list written into it: `const EVENTS = [{...}, ...];`. Each event is
#   {"title", "date": "YYYY-MM-DD HH:MM:SS", "endDate" (or null), "allDay", "location", "summary", "source": "discord" |
#    "dreamcastlive" | "manual", "url" ("/events/<slug>" or an outside page), "external"}
# about a year ahead, no paging, no ids (a "/events/<slug>" url is used as one; DreamcastLive events all link to one schedule page,
# so theirs is made from the title and time). The times carry no time zone. DC99 says they are "normalized to one timezone", but
# DreamcastLive's own schedule gives "Game Night, Wednesdays 9:00 PM Eastern" and "Game Night UK, Sundays 8:00 PM UK", and DC99
# lists them at 21:00 and 20:00: so a time is US Eastern (America/New_York), and UK time for an event with "UK" in its title.
#
# The importer keeps the events in SQLite (core.EVENTS_DB): new ones are added, changed ones updated, future ones that are gone
# from DC99 marked removed. A failed or empty download changes nothing. It runs in the background every N minutes (Settings, or
# DC99_SYNC_INTERVAL=15m) and on POST /api/sync. DC99_MOCK=1 (or "mock" in events.json) reads sample_events.json instead of DC99.
#
# Reminders: the user picks events (the bell on the dashboard) or whole series (Settings: always remind me of "US Game Night").
# Their times go to core.EVENT_REMINDERS, so the LED service shows "Event starting soon" without the page open; the page shows a
# banner and highlights the clock box (and this module's box) from `lead` minutes before the start until 10 minutes after.
#
# A JSON API for other programs (an openMenu companion, say): GET /api/events, /api/events/upcoming, /api/events/<id>,
# /api/sources, /api/games, /api/status and POST /api/sync (see docs/events.md). Runs in the web service (Python 3).
import calendar
import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import time

try:
    from urllib.request import Request, urlopen
    from urllib.parse import parse_qs, urlsplit
except ImportError:                       # Python 2
    from urllib2 import Request, urlopen  # noqa: F401
    from urlparse import parse_qs, urlsplit  # noqa: F401

import base_core as core
import base_tz as tz

SITE = "https://dc99.net"
SOURCE_URL = SITE + "/community/"
SOURCE_LABELS = {"manual": "DC99", "discord": "Sega Online Discord", "dreamcastlive": "DreamcastLive"}
SAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_events.json")
TIMEOUT = 10
RETRIES = 2                 # tries after the first, a few seconds apart
RETRY_WAIT = 4
MAX_BYTES = 3000000
LEADS = (5, 10, 15, 30, 60)
DEFAULT_LEAD = 15
AFTER = 10                  # minutes after the start that a reminder still shows
INTERVALS = (15, 30, 60, 180, 360, 720)
DEFAULT_INTERVAL = 60
LIST_DAYS = 14              # the dashboard lists the events of the next two weeks
LIST_MAX = 10
MAX_SERIES = 12
REMIND_DAYS = 30            # reminders are written for the events of the next 30 days

_db_lock = threading.Lock()
_sync = {"running": False, "thread": None}


# ------------------------------------------------------------------------------------------------ settings
def _flag(v):
    return v is True or str(v).strip().lower() in ("1", "true", "yes", "on")


def read_config():
    """{"lead": minutes, "zone": the common time zone (core.time_zone(): "" = the Pi's own, read only here), "interval": minutes,
    "picked": [event ids], "series": [titles], "dismissed": [event ids], "mock": bool}."""
    try:
        with open(core.EVENTS_CONFIG) as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    lead = data.get("lead")
    interval = data.get("interval")

    def ids(v):
        return [str(x) for x in v if isinstance(x, (str, int))][:500] if isinstance(v, list) else []
    return {"lead": lead if lead in LEADS else DEFAULT_LEAD,
            "zone": core.time_zone(),
            "interval": interval if interval in INTERVALS else DEFAULT_INTERVAL,
            "picked": ids(data.get("picked")), "dismissed": ids(data.get("dismissed")),
            "series": [s for s in data.get("series") or [] if isinstance(s, str) and s.strip()][:MAX_SERIES]
            if isinstance(data.get("series"), list) else [],
            "mock": _flag(data.get("mock"))}


def save_config(values):
    cfg = read_config()
    cfg.update(values)
    cfg.pop("zone", None)                 # the time zone is the common setting (core.time_zone()), not kept here
    tmp = core.EVENTS_CONFIG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f)
    os.rename(tmp, core.EVENTS_CONFIG)
    return read_config()


def sync_interval(cfg=None):
    """Minutes between imports: DC99_SYNC_INTERVAL ("15m", "2h", "900s", "30") wins over the setting."""
    env = os.environ.get("DC99_SYNC_INTERVAL", "").strip().lower()
    m = re.match(r"^(\d+)\s*([smh]?)$", env)
    if m:
        n = int(m.group(1)) * {"s": 1.0 / 60, "m": 1, "h": 60, "": 1}[m.group(2)]
        return max(1.0, n)
    return (cfg or read_config())["interval"]


def mock_mode(cfg=None):
    return _flag(os.environ.get("DC99_MOCK", "")) or (cfg or read_config())["mock"]


def display_zone(cfg=None, override=None):
    """The zone times are shown in: an ?tz= of the API, the setting, or "" = the Pi's own."""
    z = override if override is not None else (cfg or read_config())["zone"]
    return z if (z == "" or (tz.valid_name(z) and tz.offset(z) is not None)) else ""


def zone_offset(zone, when):
    if zone:
        off = tz.offset(zone, when)
        if off is not None:
            return off
    t = time.localtime(when)
    return t.tm_gmtoff if hasattr(t, "tm_gmtoff") else -(time.altzone if t.tm_isdst > 0 else time.timezone)


def iso(when, zone=""):
    """Unix time -> "2026-10-09T03:00:00+02:00" in the display zone."""
    if when is None:
        return None
    off = zone_offset(zone, when)
    sign = "-" if off < 0 else "+"
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(when + off)) + "%s%02d:%02d" % (sign, abs(off) // 3600, abs(off) % 3600 // 60)


# ------------------------------------------------------------------------------------------------ reading DC99
def fetch(url):
    """The page's text. Replaced by the tests."""
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; dreampi-netswitch events)", "Accept": "text/html,*/*"})
    return urlopen(req, timeout=TIMEOUT).read(MAX_BYTES).decode("utf-8", "replace")


def extract_events(html):
    """The list behind `const EVENTS = [...]` in the community page. ValueError when it is not there or not JSON."""
    m = re.search(r"\bconst\s+EVENTS\s*=\s*\[", html or "")
    if not m:
        raise ValueError("no EVENTS list in the page (DC99 may have changed it)")
    data, _end = json.JSONDecoder().raw_decode(html, m.end() - 1)
    if not isinstance(data, list):
        raise ValueError("EVENTS is not a list")
    return [e for e in data if isinstance(e, dict)]


def source_zone(title):
    """The time zone a DC99 time is written in (see the top of this file)."""
    return "Europe/London" if re.search(r"\bUK\b", title or "") else "America/New_York"


def parse_time(text, zone):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$", (text or "").strip())
    if not m:
        return None
    y, mo, d, h, mi, s = [int(x or 0) for x in m.groups()]
    return tz.local_to_utc(zone, y, mo, d, h, mi, s)


def game_of(title):
    """The game when the title names it the way DreamcastLive does ("Game Night: Quake III Arena", "Game Night UK: F355
    Challenge"), else None: no guessing."""
    m = re.match(r"^.*\bGame Night(?: UK)?\s*:\s*(.+)$", title or "")
    return m.group(1).strip() if m else None


def normalize(ev):
    """One DC99 event as a row: None when it has no title or no readable time."""
    title = str(ev.get("title") or "").strip()
    if not title:
        return None
    zone = source_zone(title)
    start = parse_time(ev.get("date"), zone)
    if start is None:
        return None
    end = parse_time(ev.get("endDate"), zone) if ev.get("endDate") else None
    source = str(ev.get("source") or "unknown").strip().lower()[:30]
    url = str(ev.get("url") or "").strip()
    slug = re.match(r"^/events/([A-Za-z0-9._-]+)$", url)
    if slug and not ev.get("external"):
        sid = slug.group(1)
    else:
        sid = hashlib.sha1(("%s|%s|%s" % (source, title, ev.get("date"))).encode("utf-8")).hexdigest()[:16]
    if url.startswith("/"):
        url = SITE + url
    elif not re.match(r"^https?://", url):
        url = None
    raw = json.dumps(ev, sort_keys=True)
    return {"source": source, "source_event_id": sid, "title": title[:200], "game": game_of(title),
            "description": (str(ev.get("summary")).strip()[:1000] if ev.get("summary") else None),
            "start_utc": start, "end_utc": end, "all_day": 1 if ev.get("allDay") else 0, "source_timezone": zone,
            "location": (str(ev.get("location")).strip()[:200] if ev.get("location") else None), "network": None,
            "url": url, "raw_data": raw}


def sample_events(now=None):
    """The mock source: sample_events.json (real DC99 events from October 2026) moved on by whole weeks so they lie ahead (the
    weekday and the time stay as they were)."""
    now = time.time() if now is None else now
    with open(SAMPLE) as f:
        evs = json.load(f)
    first = min(calendar.timegm(time.strptime(e["date"], "%Y-%m-%d %H:%M:%S")) for e in evs)
    weeks = max(0, int((now - first) // (7 * 86400)) + 1)
    out = []
    for e in evs:
        e = dict(e)
        for k in ("date", "endDate"):
            if e.get(k):
                t = calendar.timegm(time.strptime(e[k], "%Y-%m-%d %H:%M:%S")) + weeks * 7 * 86400
                e[k] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t))
        if e.get("url", "").startswith("/events/") and weeks:
            e["url"] = e["url"] + "-w%d" % weeks
        out.append(e)
    return out


# ------------------------------------------------------------------------------------------------ the database
SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL, source_event_id TEXT NOT NULL,
  title TEXT NOT NULL, game TEXT, description TEXT,
  start_utc INTEGER NOT NULL, end_utc INTEGER, all_day INTEGER NOT NULL DEFAULT 0,
  source_timezone TEXT, location TEXT, network TEXT, url TEXT,
  first_seen INTEGER, last_seen INTEGER, last_updated INTEGER, removed INTEGER NOT NULL DEFAULT 0,
  raw_data TEXT,
  UNIQUE (source, source_event_id));
CREATE INDEX IF NOT EXISTS events_start ON events (start_utc);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""
FIELDS = ("source", "source_event_id", "title", "game", "description", "start_utc", "end_utc", "all_day", "source_timezone",
          "location", "network", "url", "raw_data")


def _connect():
    db = sqlite3.connect(core.EVENTS_DB, timeout=10)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def _meta(db, key, value=None):
    if value is None:
        r = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else None
    db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(value)))


def store(rows, now=None):
    """Upsert normalized rows; future events of the database that are not in rows are marked removed (and come back when they
    are seen again). {"added", "changed", "removed", "total"}."""
    now = int(time.time() if now is None else now)
    added = changed = 0
    seen = set()
    with _db_lock:
        db = _connect()
        try:
            for r in rows:
                key = (r["source"], r["source_event_id"])
                if key in seen:
                    continue
                seen.add(key)
                old = db.execute("SELECT id, raw_data, removed, start_utc FROM events WHERE source=? AND source_event_id=?", key).fetchone()
                if old is None:
                    db.execute("INSERT INTO events (%s, first_seen, last_seen, last_updated) VALUES (%s, ?, ?, ?)"
                               % (", ".join(FIELDS), ", ".join("?" * len(FIELDS))), [r[f] for f in FIELDS] + [now, now, now])
                    added += 1
                elif old["raw_data"] != r["raw_data"] or old["removed"] or old["start_utc"] != r["start_utc"]:
                    db.execute("UPDATE events SET %s, last_seen=?, last_updated=?, removed=0 WHERE id=?"
                               % ", ".join("%s=?" % f for f in FIELDS), [r[f] for f in FIELDS] + [now, now, old["id"]])
                    changed += 1
                else:
                    db.execute("UPDATE events SET last_seen=? WHERE id=?", (now, old["id"]))
            gone = 0
            for r in db.execute("SELECT id, source, source_event_id FROM events WHERE removed=0 AND start_utc>=?", (now,)).fetchall():
                if (r["source"], r["source_event_id"]) not in seen:
                    db.execute("UPDATE events SET removed=1, last_updated=? WHERE id=?", (now, r["id"]))
                    gone += 1
            total = db.execute("SELECT COUNT(*) FROM events WHERE removed=0").fetchone()[0]
            db.commit()
        finally:
            db.close()
    return {"added": added, "changed": changed, "removed": gone, "total": total}


def import_events(now=None, sleep=time.sleep):
    """One sync: fetch (or the sample in mock mode), parse, store. A failure (no internet, DC99 down, the page changed, no events
    found) is recorded and changes nothing else. Returns {"ok", "error", "added", "changed", "removed", "total"}."""
    now = time.time() if now is None else now
    cfg = read_config()
    mock = mock_mode(cfg)
    result = {"ok": False, "error": None}
    try:
        if mock:
            raw = sample_events(now)
        else:
            err = None
            for attempt in range(RETRIES + 1):
                try:
                    raw = extract_events(fetch(SOURCE_URL))
                    err = None
                    break
                except ValueError:
                    raise                                   # the page is there but has no list: trying again won't help
                except Exception as e:                       # network trouble: try again a little later
                    err = e
                    if attempt < RETRIES:
                        sleep(RETRY_WAIT)
            if err is not None:
                raise err
        rows = [r for r in (normalize(e) for e in raw) if r]
        if not rows:
            raise ValueError("DC99 listed no events")
        result.update(store(rows, now))
        result["ok"] = True
    except Exception as e:
        result["error"] = "%s: %s" % (e.__class__.__name__, e)
    with _db_lock:
        db = _connect()
        try:
            _meta(db, "last_attempt", int(now))
            if result["ok"]:
                _meta(db, "last_ok", int(now))
                _meta(db, "last_error", "")
            else:
                _meta(db, "last_error", result["error"])
            _meta(db, "mock", 1 if mock else 0)
            db.commit()
        finally:
            db.close()
    if result["ok"]:
        sys.stderr.write("events: synced %s%s: %d events (%d new, %d changed, %d removed)\n" % (
            "the sample" if mock else SOURCE_URL, "", result["total"], result["added"], result["changed"], result["removed"]))
    else:
        sys.stderr.write("events: sync failed, the stored events are kept: %s\n" % result["error"])
    try:
        write_reminders(now)
    except (IOError, OSError, sqlite3.Error) as e:
        sys.stderr.write("events: could not write the reminders: %s\n" % e)
    return result


def sync_async():
    """Start an import in the background (POST /api/sync, the Sync now button). False when one is running already."""
    if _sync["running"]:
        return False
    _sync["running"] = True

    def run():
        try:
            import_events()
        finally:
            _sync["running"] = False
    t = threading.Thread(target=run)
    t.daemon = True
    t.start()
    return True


def query(where="", args=(), order="start_utc", limit=None):
    sql = "SELECT * FROM events" + (" WHERE " + where if where else "") + " ORDER BY " + order + (" LIMIT %d" % limit if limit else "")
    with _db_lock:
        db = _connect()
        try:
            return [dict(r) for r in db.execute(sql, args).fetchall()]
        finally:
            db.close()


def status(now=None):
    now = time.time() if now is None else now
    cfg = read_config()
    try:
        with _db_lock:
            db = _connect()
            try:
                total = db.execute("SELECT COUNT(*) FROM events WHERE removed=0").fetchone()[0]
                upcoming = db.execute("SELECT COUNT(*) FROM events WHERE removed=0 AND start_utc>=?", (int(now),)).fetchone()[0]
                last_ok, last_attempt, last_error = _meta(db, "last_ok"), _meta(db, "last_attempt"), _meta(db, "last_error")
            finally:
                db.close()
        database = "ok"
    except sqlite3.Error as e:
        total = upcoming = 0
        last_ok = last_attempt = None
        last_error, database = str(e), "error"
    zone = display_zone(cfg)
    return {"database": database, "source": "dc99", "url": SOURCE_URL, "mock": mock_mode(cfg), "events": total, "upcoming": upcoming,
            "last_import": iso(int(last_ok), zone) if last_ok else None, "last_import_utc": int(last_ok) if last_ok else None,
            "last_attempt": iso(int(last_attempt), zone) if last_attempt else None,
            "last_error": last_error or None, "syncing": _sync["running"],
            "sync_interval_minutes": sync_interval(cfg), "timezone": zone or "system"}


# ------------------------------------------------------------------------------------------------ reminders
def reminded(row, cfg):
    return str(row["id"]) in cfg["picked"] or row["title"] in cfg["series"]


UPCOMING_KEPT = 5       # the soonest events (reminded or not) that EVENT_REMINDERS also holds, for core.next_event()


def write_reminders(now=None):
    """The reminded events of the next 30 days to core.EVENT_REMINDERS (the LEDs and the page read it); old picks are dropped. It also
    holds the soonest few events of all ("upcoming"), which the openMenu link tells the Dreamcast about."""
    now = time.time() if now is None else now
    cfg = read_config()
    rows = query("removed=0 AND start_utc>=? AND start_utc<?", (int(now - AFTER * 60), int(now + REMIND_DAYS * 86400)))
    items = [{"id": str(r["id"]), "title": r["title"], "start": r["start_utc"]} for r in rows if reminded(r, cfg)]
    alive = set(str(r["id"]) for r in rows)
    keep_picked = [i for i in cfg["picked"] if i in alive or not rows]
    keep_dismissed = [i for i in cfg["dismissed"] if i in alive]
    if keep_picked != cfg["picked"] or keep_dismissed != cfg["dismissed"]:
        cfg = save_config({"picked": keep_picked, "dismissed": keep_dismissed})
    coming = [{"id": str(r["id"]), "title": r["title"], "start": r["start_utc"]} for r in sorted(rows, key=lambda r: r["start_utc"])[:UPCOMING_KEPT]]
    data = {"lead": cfg["lead"], "after": AFTER, "items": items, "upcoming": coming, "dismissed": cfg["dismissed"], "written": int(now)}
    tmp = core.EVENT_REMINDERS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.rename(tmp, core.EVENT_REMINDERS)
    return data


def when_text(start, now, zone):
    """"Today 21:00", "Tomorrow 03:00", "Thu 8 Oct 03:00" in the display zone, plus "in 12 min" when it is close."""
    off = zone_offset(zone, start)
    t, today = time.gmtime(start + off), time.gmtime(now + zone_offset(zone, now))
    days = (calendar.timegm((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0)) - calendar.timegm((today.tm_year, today.tm_mon, today.tm_mday, 0, 0, 0))) // 86400
    hm = time.strftime("%H:%M", t)
    day = "Today" if days == 0 else "Tomorrow" if days == 1 else time.strftime("%a ", t) + str(t.tm_mday) + time.strftime(" %b", t)
    return "%s %s" % (day, hm)


def soon_text(start, now):
    mins = int(round((start - now) / 60.0))
    if mins > 90:
        return "in %d h %d min" % (mins // 60, mins % 60) if mins % 60 else "in %d h" % (mins // 60)
    if mins > 0:
        return "in %d min" % mins
    if mins == 0:
        return "now"
    return "started %d min ago" % -mins


# ------------------------------------------------------------------------------------------------ the page
def view(now=None):
    """GET /events/view (the box's data source): next (the first coming event), list (the next two weeks: id, title, when,
    source, url, reminded, series), status line."""
    now = time.time() if now is None else now
    cfg = read_config()
    zone = display_zone(cfg)
    rows = query("removed=0 AND start_utc>=?", (int(now - AFTER * 60),), limit=200)
    soon = [r for r in rows if r["start_utc"] < now + LIST_DAYS * 86400][:LIST_MAX]
    st = status(now)
    if st["last_error"] and not st["events"]:
        line = "Could not reach DC99 yet: " + st["last_error"]
    elif st["last_import_utc"]:
        ago = int(now - st["last_import_utc"]) // 60
        line = "Synced with %s %s; %s%s" % ("the sample events" if st["mock"] else "DC99",
                                           "just now" if ago < 1 else "%d min ago" % ago if ago < 120 else "%d h ago" % (ago // 60),
                                           _every(st["sync_interval_minutes"]).lower(), (". Last try failed: " + st["last_error"]) if st["last_error"] else "")
    else:
        line = "Not synced yet"
    if st["syncing"]:
        line = "Syncing with DC99..."
    nxt = rows[0] if rows else None
    return {"next": {"title": nxt["title"], "when": "%s, %s" % (when_text(nxt["start_utc"], now, zone), soon_text(nxt["start_utc"], now)),
                     "reminded": reminded(nxt, cfg)} if nxt else {"title": "No events listed", "when": line, "reminded": False},
            "list": [{"id": str(r["id"]), "title": r["title"], "when": when_text(r["start_utc"], now, zone),
                      "day": when_text(r["start_utc"], now, zone).rsplit(" ", 1)[0],
                      "hm": time.strftime("%H:%M", time.gmtime(r["start_utc"] + zone_offset(zone, r["start_utc"]))), "game": r["game"],
                      "source": SOURCE_LABELS.get(r["source"], r["source"]), "url": r["url"],
                      "reminded": reminded(r, cfg), "series": r["title"] in cfg["series"],
                      "sub": SOURCE_LABELS.get(r["source"], r["source"]) + (" \u00b7 every one" if r["title"] in cfg["series"] else "")} for r in soon],
            "status": line, "syncing": st["syncing"], "busy": st["syncing"], "zone": tz.utc_text(zone_offset(zone, now)) if not zone else tz.zone_name(zone)}


def reminder_view(now=None):
    """The due reminder for the banner and the highlight: (id, text) or None."""
    now = time.time() if now is None else now
    due = core.event_reminder(now)
    if not due:
        return None
    zone = display_zone()
    return due["id"], "DC99 event %s: %s (%s)" % (soon_text(due["start"], now), due["title"],
                                                  time.strftime("%H:%M", time.gmtime(due["start"] + zone_offset(zone, due["start"]))))


def api(d, warnings):
    r = reminder_view()
    if r:
        d.setdefault("notices", []).append({"id": r[0], "text": r[1], "post": "/events/dismiss"})
        hl = d.setdefault("highlight", {})
        hl["clock"] = r[1]                 # the clock box stands out (when the clock module is on: nothing happens without it)
        hl["events"] = r[1]


def _settings_reply():
    cfg = read_config()
    interval = sync_interval(cfg)
    env = bool(os.environ.get("DC99_SYNC_INTERVAL"))
    return {"values": {"lead": cfg["lead"], "interval": cfg["interval"]},
            "options": {"leads": [{"value": n, "label": "%d minutes before" % n} for n in LEADS],
                        "intervals": [{"value": n, "label": _every(n)} for n in INTERVALS]},
            "texts": {"lead": "%d minutes before the start" % cfg["lead"],
                      "interval": ("Every %g minutes (set by DC99_SYNC_INTERVAL)" % interval) if env else
                      "%s, and with Sync now" % _every(interval)}}


def _every(minutes):
    if minutes < 60:
        return "Every %d minutes" % minutes
    return "Every hour" if minutes == 60 else "Every %g hours" % (minutes / 60.0)


def _series_reply(now=None):
    now = time.time() if now is None else now
    cfg = read_config()
    titles = []
    for r in query("removed=0 AND start_utc>=?", (int(now),), limit=400):
        if r["title"] not in titles:
            titles.append(r["title"])
    for t in cfg["series"]:
        if t not in titles:
            titles.append(t)
    return {"groups": [{"key": "series", "label": "Always remind me of",
                        "sub": "Every event with these names" if cfg["series"] else "Every event of a series you pick",
                        "items": cfg["series"], "free": False,
                        "choices": [] if len(cfg["series"]) >= MAX_SERIES else [{"value": t, "label": t} for t in sorted(titles, key=lambda s: s.lower())],
                        "empty": "The list is full" if len(cfg["series"]) >= MAX_SERIES else "No event matches"}],
            "defaults": {"series": []},
            "rules": {"per_group": MAX_SERIES, "unique": True, "add_label": "Add", "add_title": "Remind me of every"}}


def _body(h, limit=8192):
    try:
        body = json.loads(h._body(limit).decode("utf-8") or "{}")
    except (ValueError, IOError, OSError, AttributeError) as e:
        h.send(str(e), "text/plain; charset=utf-8", status=400)
        return None
    return body if isinstance(body, dict) else {}


def _json(h, data, status=200):
    h.send(json.dumps(data), "application/json", status=status)


def _get_view(h):
    _json(h, view())


def _post_remind(h):
    """{"id": event id, "on": bool}: the bell of one event."""
    body = _body(h)
    if body is None:
        return True
    cfg = read_config()
    eid = str(body.get("id") or "")
    picked = [i for i in cfg["picked"] if i != eid]
    if _flag(body.get("on")) and query("id=?", (eid,)):
        picked.append(eid)
    save_config({"picked": picked, "dismissed": [i for i in cfg["dismissed"] if i != eid]})
    write_reminders()
    _json(h, view())
    return True


def _post_dismiss(h):
    body = _body(h)
    if body is None:
        return True
    cfg = read_config()
    eid = str(body.get("id") or "")
    if eid and eid not in cfg["dismissed"]:
        save_config({"dismissed": cfg["dismissed"] + [eid]})
        write_reminders()
    _json(h, {"ok": True})
    return True


def _get_settings(h):
    _json(h, _settings_reply())


def _post_settings(h):
    body = _body(h)
    if body is None:
        return True
    v = body.get("values") if isinstance(body.get("values"), dict) else {}
    changes = {}
    if v.get("lead") in LEADS:
        changes["lead"] = v["lead"]
    if v.get("interval") in INTERVALS:
        changes["interval"] = v["interval"]
    if changes:
        save_config(changes)
        write_reminders()
    _json(h, _settings_reply())
    return True


def _get_series(h):
    _json(h, _series_reply())


def _post_series(h):
    body = _body(h)
    if body is None:
        return True
    if isinstance(body.get("series"), list):
        save_config({"series": [s for s in body["series"] if isinstance(s, str) and s.strip()][:MAX_SERIES]})
        write_reminders()
    _json(h, _series_reply())
    return True


# ------------------------------------------------------------------------------------------------ the JSON API
def _q(h):
    q = parse_qs(urlsplit(h.path).query)
    return dict((k, v[-1]) for k, v in q.items())


def event_json(r, zone, cfg):
    return {"id": r["id"], "source": r["source"], "source_label": SOURCE_LABELS.get(r["source"], r["source"]),
            "source_event_id": r["source_event_id"], "title": r["title"], "game": r["game"], "description": r["description"],
            "start_time": iso(r["start_utc"], zone), "end_time": iso(r["end_utc"], zone), "all_day": bool(r["all_day"]),
            "timezone": zone or "system", "source_timezone": r["source_timezone"], "location": r["location"], "network": r["network"],
            "url": r["url"], "removed": bool(r["removed"]), "reminded": reminded(r, cfg),
            "last_seen": iso(r["last_seen"], zone), "last_updated": iso(r["last_updated"], zone)}


def _day_start(text, zone, plus_days=0):
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text or "")
    if not m:
        return None
    y, mo, d = [int(x) for x in m.groups()]
    t = calendar.timegm((y, mo, d, 0, 0, 0)) + plus_days * 86400
    g = time.gmtime(t)
    if zone:
        return tz.local_to_utc(zone, g.tm_year, g.tm_mon, g.tm_mday)
    return t - zone_offset("", t)


def _filtered(q, cfg, zone, upcoming=False, now=None):
    now = time.time() if now is None else now
    where, args = ["removed=0"] if q.get("removed") not in ("1", "true") else [], []
    for key in ("source", "game", "network"):
        if q.get(key):
            where.append("LOWER(%s)=LOWER(?)" % key)
            args.append(q[key])
    if upcoming:
        where.append("start_utc>=?")
        args.append(int(now))
    frm, to = _day_start(q.get("from"), zone), _day_start(q.get("to"), zone, 1)
    if q.get("from") and frm is None or q.get("to") and to is None:
        raise ValueError("from and to are dates: YYYY-MM-DD")
    if frm is not None:
        where.append("start_utc>=?")
        args.append(frm)
    if to is not None:
        where.append("start_utc<?")
        args.append(to)
    try:
        limit = max(1, min(1000, int(q.get("limit") or (20 if upcoming else 1000))))
    except ValueError:
        raise ValueError("limit is a number")
    return query(" AND ".join(where), args, limit=limit)


def _api_events(h, upcoming=False):
    q = _q(h)
    cfg = read_config()
    zone = display_zone(cfg, q.get("tz"))
    if q.get("tz") and zone != q["tz"]:
        return _json(h, {"error": "unknown time zone %s" % q["tz"]}, 400)
    try:
        rows = _filtered(q, cfg, zone, upcoming)
    except ValueError as e:
        return _json(h, {"error": str(e)}, 400)
    _json(h, {"timezone": zone or "system", "count": len(rows), "events": [event_json(r, zone, cfg) for r in rows]})


def _api_event(h):
    rest = urlsplit(h.path).path[len("/api/events/"):]
    if not rest.isdigit():
        return _json(h, {"error": "no such event"}, 404)
    rows = query("id=?", (int(rest),))
    if not rows:
        return _json(h, {"error": "no such event"}, 404)
    cfg = read_config()
    zone = display_zone(cfg, _q(h).get("tz"))
    out = event_json(rows[0], zone, cfg)
    try:
        out["raw_data"] = json.loads(rows[0]["raw_data"])
    except (TypeError, ValueError):
        out["raw_data"] = None
    _json(h, out)


def _api_sources(h):
    n = dict((r["source"], r["n"]) for r in query_count("source"))
    keys = sorted(set(SOURCE_LABELS) | set(n))
    _json(h, {"sources": [{"id": k, "label": SOURCE_LABELS.get(k, k), "events": n.get(k, 0)} for k in keys]})


def query_count(col):
    with _db_lock:
        db = _connect()
        try:
            return [dict(r) for r in db.execute("SELECT %s, COUNT(*) AS n FROM events WHERE removed=0 AND %s IS NOT NULL GROUP BY %s ORDER BY %s"
                                                % (col, col, col, col)).fetchall()]
        finally:
            db.close()


def _api_games(h):
    _json(h, {"games": [{"game": r["game"], "events": r["n"]} for r in query_count("game")]})


def _api_status(h):
    _json(h, status())


def _api_sync(h):
    started = sync_async()
    out = status()
    out["started"] = started
    _json(h, out)
    return True


GET = {"/events/view": _get_view, "/events/settings": _get_settings, "/events/series": _get_series,
       "/api/events": lambda h: _api_events(h), "/api/events/upcoming": lambda h: _api_events(h, upcoming=True),
       "/api/sources": _api_sources, "/api/games": _api_games, "/api/status": _api_status}
GET_PREFIX = {"/api/events/": _api_event}
OPEN = ("/events/remind", "/events/dismiss")   # the bell and the banner's dismiss work while Settings is locked with the PIN
POST = {"/events/remind": _post_remind, "/events/dismiss": _post_dismiss, "/events/settings": _post_settings,
        "/events/series": _post_series, "/api/sync": _api_sync}


# ------------------------------------------------------------------------------------------------ background sync
def _loop():
    time.sleep(5)                                  # let the web service settle first
    while True:
        try:
            if core.module_enabled("events"):
                with _db_lock:
                    db = _connect()
                    try:
                        last = float(_meta(db, "last_attempt") or 0)
                    finally:
                        db.close()
                if time.time() - last >= sync_interval() * 60 and not _sync["running"]:
                    _sync["running"] = True
                    try:
                        import_events()
                    finally:
                        _sync["running"] = False
                else:
                    write_reminders()              # keeps the LEDs' list fresh (series, events coming into the 30 days)
        except Exception as e:                      # never let the loop die
            sys.stderr.write("events: background sync: %s\n" % e)
        time.sleep(60)


def start():
    """Called once by the web service: the periodic sync runs while the module is on."""
    if _sync["thread"] is None:
        t = threading.Thread(target=_loop, name="events-sync")
        t.daemon = True
        t.start()
        _sync["thread"] = t
