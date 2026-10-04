# -*- coding: utf-8 -*-
# DreamPi Netswitch add-on - time zones with summer time on any Python, and a list of cities to pick a zone from (base; used by
# the clock and the events modules).
#
# Python 3.9+ has zoneinfo, which reads the system's tz database. Older Python has nothing for "the time in New York": only the
# Pi's own zone (time.localtime) and fixed offsets. The rules are on the Pi all the same, in /usr/share/zoneinfo (Debian's tzdata
# package), as TZif files - so without zoneinfo this module reads those files itself: the list of past and planned changes, and
# for the years after the list the POSIX TZ rule at its end ("CET-1CEST,M3.5.0,M10.5.0/3" = Central European time, summer time
# from the last Sunday in March 02:00 to the last Sunday in October 03:00). Works on Python 3 and 2.7.
import bisect
import calendar
import os
import re
import struct
import time

try:
    from zoneinfo import ZoneInfo           # Python 3.9+
    from datetime import datetime
except ImportError:                         # older Python: read the TZif files below
    ZoneInfo = None

ZONEINFO_DIRS = ("/usr/share/zoneinfo", "/usr/lib/zoneinfo", "/usr/share/lib/zoneinfo")
_NAME = re.compile(r"^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+)*$")
_cache = {}        # zone name -> parsed TZif (or None when there is no such file)
use_zoneinfo = ZoneInfo is not None   # tests switch this off to check the reader
# Zones that were renamed: the new name is tried first, the old one on a system whose tz database is older (or newer and
# without the old links)
ALIASES = {"Europe/Kyiv": "Europe/Kiev", "Europe/Kiev": "Europe/Kyiv", "Asia/Yangon": "Asia/Rangoon", "America/Nuuk": "America/Godthab"}

# Cities with their zones, to pick from on the page (the clock's world list and time zone, the events' time zone):
# (name, IANA time zone, longitude, latitude, region).
CITIES = (
    ("Honolulu", "Pacific/Honolulu", -157.9, 21.3, "Americas"),
    ("Anchorage", "America/Anchorage", -149.9, 61.2, "Americas"),
    ("Vancouver", "America/Vancouver", -123.1, 49.3, "Americas"),
    ("Los Angeles", "America/Los_Angeles", -118.2, 34.1, "Americas"),
    ("Phoenix", "America/Phoenix", -112.1, 33.4, "Americas"),
    ("Denver", "America/Denver", -105.0, 39.7, "Americas"),
    ("Mexico City", "America/Mexico_City", -99.1, 19.4, "Americas"),
    ("Chicago", "America/Chicago", -87.6, 41.9, "Americas"),
    ("Toronto", "America/Toronto", -79.4, 43.7, "Americas"),
    ("New York", "America/New_York", -74.0, 40.7, "Americas"),
    ("Bogotá", "America/Bogota", -74.1, 4.7, "Americas"),
    ("Lima", "America/Lima", -77.0, -12.0, "Americas"),
    ("Caracas", "America/Caracas", -66.9, 10.5, "Americas"),
    ("Halifax", "America/Halifax", -63.6, 44.6, "Americas"),
    ("Santiago", "America/Santiago", -70.7, -33.4, "Americas"),
    ("Buenos Aires", "America/Argentina/Buenos_Aires", -58.4, -34.6, "Americas"),
    ("St. John's", "America/St_Johns", -52.7, 47.6, "Americas"),
    ("São Paulo", "America/Sao_Paulo", -46.6, -23.5, "Americas"),
    ("Reykjavík", "Atlantic/Reykjavik", -21.9, 64.1, "Europe"),
    ("Lisbon", "Europe/Lisbon", -9.1, 38.7, "Europe"),
    ("Dublin", "Europe/Dublin", -6.3, 53.3, "Europe"),
    ("London", "Europe/London", -0.1, 51.5, "Europe"),
    ("Madrid", "Europe/Madrid", -3.7, 40.4, "Europe"),
    ("Paris", "Europe/Paris", 2.4, 48.9, "Europe"),
    ("Amsterdam", "Europe/Amsterdam", 4.9, 52.4, "Europe"),
    ("Oslo", "Europe/Oslo", 10.8, 59.9, "Europe"),
    ("Copenhagen", "Europe/Copenhagen", 12.6, 55.7, "Europe"),
    ("Berlin", "Europe/Berlin", 13.4, 52.5, "Europe"),
    ("Rome", "Europe/Rome", 12.5, 41.9, "Europe"),
    ("Stockholm", "Europe/Stockholm", 18.1, 59.3, "Europe"),
    ("Warsaw", "Europe/Warsaw", 21.0, 52.2, "Europe"),
    ("Helsinki", "Europe/Helsinki", 24.9, 60.2, "Europe"),
    ("Athens", "Europe/Athens", 23.7, 38.0, "Europe"),
    ("Kyiv", "Europe/Kyiv", 30.5, 50.5, "Europe"),
    ("Istanbul", "Europe/Istanbul", 29.0, 41.0, "Europe"),
    ("Moscow", "Europe/Moscow", 37.6, 55.8, "Europe"),
    ("Lagos", "Africa/Lagos", 3.4, 6.5, "Africa and Middle East"),
    ("Cairo", "Africa/Cairo", 31.2, 30.0, "Africa and Middle East"),
    ("Johannesburg", "Africa/Johannesburg", 28.0, -26.2, "Africa and Middle East"),
    ("Nairobi", "Africa/Nairobi", 36.8, -1.3, "Africa and Middle East"),
    ("Tehran", "Asia/Tehran", 51.4, 35.7, "Africa and Middle East"),
    ("Dubai", "Asia/Dubai", 55.3, 25.2, "Africa and Middle East"),
    ("Karachi", "Asia/Karachi", 67.0, 24.9, "Asia and Pacific"),
    ("Mumbai", "Asia/Kolkata", 72.9, 19.1, "Asia and Pacific"),
    ("Kathmandu", "Asia/Kathmandu", 85.3, 27.7, "Asia and Pacific"),
    ("Dhaka", "Asia/Dhaka", 90.4, 23.8, "Asia and Pacific"),
    ("Bangkok", "Asia/Bangkok", 100.5, 13.8, "Asia and Pacific"),
    ("Jakarta", "Asia/Jakarta", 106.8, -6.2, "Asia and Pacific"),
    ("Singapore", "Asia/Singapore", 103.8, 1.4, "Asia and Pacific"),
    ("Hong Kong", "Asia/Hong_Kong", 114.2, 22.3, "Asia and Pacific"),
    ("Shanghai", "Asia/Shanghai", 121.5, 31.2, "Asia and Pacific"),
    ("Manila", "Asia/Manila", 121.0, 14.6, "Asia and Pacific"),
    ("Seoul", "Asia/Seoul", 127.0, 37.6, "Asia and Pacific"),
    ("Tokyo", "Asia/Tokyo", 139.7, 35.7, "Asia and Pacific"),
    ("Perth", "Australia/Perth", 115.9, -32.0, "Asia and Pacific"),
    ("Adelaide", "Australia/Adelaide", 138.6, -34.9, "Asia and Pacific"),
    ("Brisbane", "Australia/Brisbane", 153.0, -27.5, "Asia and Pacific"),
    ("Sydney", "Australia/Sydney", 151.2, -33.9, "Asia and Pacific"),
    ("Auckland", "Pacific/Auckland", 174.8, -36.8, "Asia and Pacific"),
)


def zone_options(now=None, own="This Pi's own time zone"):
    """The form widget's options for a time zone: "" = the Pi's own, then the cities by region (with their offset now), then UTC.
    Zones this system does not know are left out."""
    now = time.time() if now is None else now
    t = time.localtime(now)
    pi = t.tm_gmtoff if hasattr(t, "tm_gmtoff") else -(time.altzone if t.tm_isdst > 0 else time.timezone)
    opts = [{"value": "", "label": "%s (%s now)" % (own, utc_text(pi))}]
    for name, zone, _lon, _lat, region in CITIES:
        off = offset(zone, now)
        if off is not None:
            opts.append({"value": zone, "label": "%s (%s now)" % (name, utc_text(off)), "group": region})
    opts.append({"value": "UTC", "label": "UTC", "group": "Other"})
    return opts


def zone_name(zone):
    """"Europe/Stockholm" -> "Stockholm" (the city of the list, else the last part of the name)."""
    for c in CITIES:
        if c[1] == zone:
            return c[0]
    return (zone or "").split("/")[-1].replace("_", " ")


def utc_text(off):
    """3600 -> "UTC+1", 19800 -> "UTC+5:30", 0 -> "UTC"."""
    if not off:
        return "UTC"
    a = abs(int(off))
    return "UTC%s%d%s" % ("-" if off < 0 else "+", a // 3600, (":%02d" % (a % 3600 // 60)) if a % 3600 else "")


def valid_name(zone):
    return bool(zone) and len(zone) < 64 and bool(_NAME.match(zone)) and ".." not in zone


def offset(zone, now=None):
    """The UTC offset of an IANA zone ("Europe/Stockholm") at unix time now, in seconds, with summer time. None when the zone is
    not known on this system."""
    now = time.time() if now is None else now
    if not valid_name(zone):
        return None
    off = _offset(zone, now)
    if off is None and zone in ALIASES:
        off = _offset(ALIASES[zone], now)
    return off


def _offset(zone, now):
    if use_zoneinfo:
        try:
            return int(datetime.fromtimestamp(now, ZoneInfo(zone)).utcoffset().total_seconds())
        except Exception:
            pass
    tzf = _load(zone)
    return _tzif_offset(tzf, now) if tzf else None


def local_to_utc(zone, y, mo, d, h=0, mi=0, s=0):
    """Unix time of a wall-clock time in a zone ("2026-10-08 21:00 in America/New_York"). In the hour that is skipped in spring
    it gives the time an hour later, in the hour that comes twice in autumn the first one. None when the zone is not known."""
    naive = calendar.timegm((y, mo, d, h, mi, s))
    offs = set()
    for probe in (naive - 86400, naive, naive + 86400):      # the offsets in force around that day (two near a change)
        o = offset(zone, probe)
        if o is None:
            return None
        offs.add(o)
    fits = [naive - o for o in offs if offset(zone, naive - o) == o]
    if fits:
        return min(fits)                  # twice in autumn: the first one
    return naive - min(offs)              # skipped in spring: as if the clock had not been put forward yet (an hour later)


# ----------------------------------------------------------------------------------------------------- the TZif reader
def _path(zone):
    for d in ZONEINFO_DIRS:
        p = os.path.join(d, zone)
        if os.path.isfile(p):
            return p
    return None


def _load(zone):
    if zone not in _cache:
        tzf = None
        p = _path(zone)
        if p:
            try:
                with open(p, "rb") as f:
                    tzf = parse_tzif(f.read())
            except (IOError, OSError, ValueError, struct.error):
                tzf = None
        _cache[zone] = tzf
    return _cache[zone]


def parse_tzif(data):
    """{"times": [transition unix times], "offs": [offset after each], "first": offset before the first, "rule": parsed POSIX TZ
    footer or None}. Reads the 64-bit block of version 2+ files, the 32-bit one of version 1 files."""
    if data[:4] != b"TZif":
        raise ValueError("not a TZif file")
    version = data[4:5]

    def header(pos):
        return struct.unpack(">6l", data[pos + 20:pos + 44])     # isutcnt isstdcnt leapcnt timecnt typecnt charcnt

    def block(pos, tsize):
        isut, isstd, leap, timecnt, typecnt, charcnt = header(pos)
        pos += 44
        fmt = ">%d%s" % (timecnt, "q" if tsize == 8 else "l")
        times = list(struct.unpack(fmt, data[pos:pos + timecnt * tsize]))
        pos += timecnt * tsize
        idx = list(struct.unpack(">%dB" % timecnt, data[pos:pos + timecnt]))
        pos += timecnt
        types = []
        for i in range(typecnt):
            utoff, isdst, _abbr = struct.unpack(">lBB", data[pos + i * 6:pos + i * 6 + 6])
            types.append((utoff, isdst))
        pos += typecnt * 6 + charcnt + leap * (tsize + 4) + isstd + isut
        return times, idx, types, pos

    times, idx, types, end = block(0, 4)
    footer = None
    if version >= b"2":
        times, idx, types, end = block(end, 8)
        nl = data.find(b"\n", end + 1)
        if data[end:end + 1] == b"\n" and nl > end:
            footer = data[end + 1:nl].decode("ascii", "replace")
    if not types:
        raise ValueError("no local time types")
    first = types[0][0]                   # RFC 8536: before the first change the zone is in its first time type
    return {"times": times, "offs": [types[i][0] for i in idx], "first": first, "rule": parse_posix(footer) if footer else None}


def _tzif_offset(tzf, now):
    times = tzf["times"]
    if not times or now < times[0]:
        if not times and tzf["rule"]:
            return posix_offset(tzf["rule"], now)
        return tzf["first"]
    if now >= times[-1] and tzf["rule"]:
        return posix_offset(tzf["rule"], now)
    return tzf["offs"][bisect.bisect_right(times, now) - 1]


# ----------------------------------------------------------------------------------------------------- POSIX TZ rules
_POSIX = re.compile(r"^(<[^>]+>|[A-Za-z]{3,})([+-]?\d{1,3}(?::\d{1,2}){0,2})"
                    r"(?:(<[^>]+>|[A-Za-z]{3,})([+-]?\d{1,3}(?::\d{1,2}){0,2})?(?:,([^,]+),([^,]+))?)?$")


def _hms(s):
    """'-3:30' -> seconds; POSIX allows a sign and hours up to 167."""
    sign = -1 if s.startswith("-") else 1
    parts = [int(x) for x in s.lstrip("+-").split(":")] + [0, 0]
    return sign * (parts[0] * 3600 + parts[1] * 60 + parts[2])


def _date_rule(s):
    when, _, at = s.partition("/")
    secs = _hms(at) if at else 7200
    if when.startswith("M"):
        m, w, d = [int(x) for x in when[1:].split(".")]
        return ("M", m, w, d, secs)
    if when.startswith("J"):
        return ("J", int(when[1:]), 0, 0, secs)
    return ("N", int(when), 0, 0, secs)


def parse_posix(s):
    """"CET-1CEST,M3.5.0,M10.5.0/3" -> {"std": 3600, "dst": 7200, "start": rule, "end": rule}; offsets east of UTC are positive
    here (POSIX writes them the other way round). No summer time: dst None. An empty or odd footer: None."""
    m = _POSIX.match((s or "").strip())
    if not m:
        return None
    std = -_hms(m.group(2))
    if not m.group(3):
        return {"std": std, "dst": None}
    dst = -_hms(m.group(4)) if m.group(4) else std + 3600
    if not m.group(5):                    # summer time without a rule: the old US default
        start, end = ("M", 3, 2, 0, 7200), ("M", 11, 1, 0, 7200)
    else:
        start, end = _date_rule(m.group(5)), _date_rule(m.group(6))
    return {"std": std, "dst": dst, "start": start, "end": end}


def _rule_day(rule, year):
    """The day (unix time of 00:00 UTC of that date) a rule falls on in a year."""
    kind, a, w, d, _secs = rule
    if kind == "M":
        first_wd = (calendar.weekday(year, a, 1) + 1) % 7          # 0 = Sunday, like POSIX
        day = 1 + (d - first_wd) % 7 + 7 * (w - 1)
        last = calendar.monthrange(year, a)[1]
        while day > last:
            day -= 7
        return calendar.timegm((year, a, day, 0, 0, 0))
    if kind == "J":                       # 1..365, February 29 never counted
        n = a - 1
        if calendar.isleap(year) and a >= 60:
            n += 1
        return calendar.timegm((year, 1, 1, 0, 0, 0)) + n * 86400
    return calendar.timegm((year, 1, 1, 0, 0, 0)) + a * 86400   # 0..365, February 29 counted


def posix_offset(rule, now):
    if rule.get("dst") is None:
        return rule["std"]
    std, dst = rule["std"], rule["dst"]
    year = time.gmtime(now + std).tm_year
    start = _rule_day(rule["start"], year) + rule["start"][4] - std     # the change to summer time, in local winter time
    end = _rule_day(rule["end"], year) + rule["end"][4] - dst          # back to winter time, in local summer time
    if start < end:                                                     # northern hemisphere
        return dst if start <= now < end else std
    return std if end <= now < start else dst                          # southern: summer over the new year
