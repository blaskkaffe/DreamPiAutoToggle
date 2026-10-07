# Check-in add-on - the check-in board (web service side), after CheckinChicken.
# The people come from the contacts module's roster (core.CONTACTS); this module keeps who is in, and each person's status, in
# core.CHECKIN. There is one copy of that state: the web service of the host (every other screen is a browser that opens the
# host's address, in kiosk mode if you like), and every /api answer carries the whole board with a revision number, so a change
# made on one screen shows on all of them within a second. A button is grey while the person is out, in the colour of their
# department (or building) while in, and in the colour of the status once one is set. Colours are palette ids only. Python 3.
import io
import json
import os
import re
import threading
import time

import base_core as core

# [code, label, palette colour, needs, checks out]; the list CheckinChicken starts with. "needs": "time", "date", "note" or "".
# IN / OUT are the two fixed ones; the others can be changed in checkin.json "statuses" (a list of objects with these keys).
IN, OUT = "IN", "OUT"
DEFAULT_STATUSES = [
    {"code": "FYS", "label": "FYS", "colour": "cyan"},
    {"code": "LATE", "label": "Kommer sent", "colour": "orange", "needs": "time", "default": "07:30"},
    {"code": "EARLY_LEAVE", "label": "Går tidigare", "colour": "orange", "needs": "time", "default": "16:30"},
    {"code": "TRAVEL", "label": "Tjänsteresa", "colour": "blue", "needs": "date", "prefix": "tillbaka", "out": True},
    {"code": "SICK", "label": "Sjuk", "colour": "red", "out": True},
    {"code": "WFH", "label": "Jobbar hemifrån", "colour": "bright-blue", "out": True},
    {"code": "VACATION", "label": "Semester", "colour": "bright-cyan", "needs": "date", "prefix": "tillbaka", "out": True},
    {"code": "VAB", "label": "VAB", "colour": "bright-red", "out": True},
    {"code": "DOCTOR", "label": "Läkarbesök", "colour": "yellow", "needs": "time"},
    {"code": "PARENTAL", "label": "Föräldraledig", "colour": "purple", "out": True},
    {"code": "PERSONAL", "label": "Personlig dag", "colour": "bright-purple", "out": True},
    {"code": "OTHER", "label": "Annat", "colour": "white", "needs": "note"},
]
GROUPS = ("department", "building")
FRAMES = ("none", "thin", "thick")      # the frame round a department box
BOXES = ("neutral", "board")            # its colour: neutral (grey) or the board colour (Appearance > Check-in board colour)
SCROLLS = ("off", "auto", "status", "on")      # the scrolling on a row: never; only when name and status do not fit; only the status, and only when it does not fit (the name stays); always
AUTO = ("blue", "green", "orange", "purple", "cyan", "yellow", "bright-pink", "red", "bright-blue", "bright-green", "bright-purple", "bright-cyan")
OUT_COLOUR = "global"       # the grey of a person who is out
DETAIL_MAX = 60
_lock = threading.Lock()
_cache = {"key": None, "data": None}


def _default_state():
    return {"rev": 0, "config": {}, "statuses": None, "people": {}}


def _load():
    try:
        with io.open(core.CHECKIN, encoding="utf-8") as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        data = _default_state()
    data.setdefault("rev", 0)
    data.setdefault("people", {})
    if not isinstance(data["people"], dict):
        data["people"] = {}
    if not isinstance(data.get("config"), dict):
        data["config"] = {}
    return data


def _save(data):
    data["rev"] = int(data.get("rev", 0)) + 1
    tmp = core.CHECKIN + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False))
    os.rename(tmp, core.CHECKIN)
    _cache["key"] = None


def _palette_id(v, default):
    v = core.LEGACY_COLOURS.get(v, v)
    return v if v in core.palette_ids() else default


def statuses(data=None):
    """The status menu: the saved one (checkin.json "statuses") or the defaults, each cleaned."""
    data = data or _load()
    raw = data.get("statuses")
    out, seen = [], set()
    for s in (raw if isinstance(raw, list) else DEFAULT_STATUSES):
        if not isinstance(s, dict) or not re.match(r"^[A-Z0-9_]{1,24}$", str(s.get("code", ""))) or s["code"] in seen or s["code"] in (IN, OUT):
            continue
        seen.add(s["code"])
        out.append({"code": s["code"], "label": str(s.get("label") or s["code"])[:30], "colour": _palette_id(s.get("colour"), "white"),
                    "needs": s.get("needs") if s.get("needs") in ("time", "date", "note") else "", "default": str(s.get("default") or "")[:5],
                    "prefix": str(s.get("prefix") or "")[:20], "out": bool(s.get("out")), "sticky": bool(s.get("sticky")),
                    "dots": s.get("dots") if s.get("dots") in (1, 2, 3) else 0})
    return out[:16]


def save_statuses(items):
    """Replace the status menu (Settings > Statuses): a list of {code?, label, colour, needs, default, prefix, out, sticky, dots}. A status without a
    code (a new one) gets a fresh one. Returns the cleaned list, None when it is not a list or a label is missing. People who have a status that is
    no longer in the list simply show none."""
    if not isinstance(items, list) or len(items) > 16 or not all(isinstance(x, dict) for x in items):
        return None
    with _lock:
        data = _load()
        used = set(str(x.get("code")) for x in items if x.get("code"))
        out = []
        for x in items:
            label = re.sub(r"\s+", " ", str(x.get("label") or "")).strip()[:30]
            if not label:
                return None
            code = str(x.get("code") or "")
            if not re.match(r"^[A-Z0-9_]{1,24}$", code) or code in (IN, OUT):
                code = ""
                while not code or code in used:
                    code = "S" + os.urandom(4).hex().upper()
                used.add(code)
            d = str(x.get("default") or "").strip()
            out.append({"code": code, "label": label, "colour": _palette_id(x.get("colour"), "white"),
                        "needs": x.get("needs") if x.get("needs") in ("time", "date", "note") else "",
                        "default": d if re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", d) else "", "prefix": str(x.get("prefix") or "").strip()[:20],
                        "out": bool(x.get("out")), "sticky": bool(x.get("sticky")), "dots": x.get("dots") if x.get("dots") in (1, 2, 3) else 0})
        seen = set()
        for x in out:
            if x["code"] in seen:
                return None
            seen.add(x["code"])
        data["statuses"] = out
        _save(data)
        return statuses(data)


def _names(v):
    """None (= all) or a list of names that are shown."""
    if not isinstance(v, list):
        return None
    return [str(x)[:80] for x in v if isinstance(x, str)][:200]


def config(data=None):
    """{"group_by", "colour_by": department|building, "colours": {department: {name: id}, building: {...}}}"""
    c = (data or _load()).get("config", {})
    colours = c.get("colours") if isinstance(c.get("colours"), dict) else {}
    out = {"show_title": c.get("show_title") is not False, "group_by": c.get("group_by") if c.get("group_by") in GROUPS else "department",
           "colour_by": c.get("colour_by") if c.get("colour_by") in GROUPS else "department", "colours": {},
           "scroll": c.get("scroll") if c.get("scroll") in SCROLLS else "on",
           "title": re.sub(r"\s+", " ", str(c.get("title") or "")).strip()[:40], "frame": c.get("frame") if c.get("frame") in FRAMES else "thin",
           "box": c.get("box") if c.get("box") in BOXES else "board", "show_roles": c.get("show_roles") is not False, "show_buildings": c.get("show_buildings") is True, "keyboard": c.get("keyboard") is True,
           "roles_shown": _names(c.get("roles_shown")), "buildings_shown": _names(c.get("buildings_shown")),
           "group_order": [str(x)[:80] for x in c.get("group_order", []) if isinstance(x, str)][:200] if isinstance(c.get("group_order"), list) else []}
    for kind in GROUPS:
        m = colours.get(kind) if isinstance(colours.get(kind), dict) else {}
        out["colours"][kind] = dict((str(k), _palette_id(v, "")) for k, v in m.items() if _palette_id(v, ""))
    return out


def _roster_stamp():
    """Changes when the contacts module writes the roster or a photo, so a screen draws the board again after an import."""
    try:
        stamp = os.stat(core.CONTACTS).st_mtime_ns
    except OSError:
        stamp = 0
    try:
        stamp += int(os.stat(core.PHOTOS_DIR).st_mtime_ns)
    except OSError:
        pass
    return stamp


def _photos():
    """{person id: url} of the photos the contacts module stored (the version in the url changes when a photo does)."""
    out = {}
    try:
        names = os.listdir(core.PHOTOS_DIR)
    except OSError:
        return out
    for n in names:
        pid, _dot, ext = n.rpartition(".")
        if ext in ("jpg", "png") and re.match(r"^p[0-9a-f]{10}$", pid):
            try:
                out[pid] = "/contacts/photo/%s?v=%d" % (pid, os.stat(os.path.join(core.PHOTOS_DIR, n)).st_mtime_ns // 1000000)
            except OSError:
                pass
    return out


def _roster():
    try:
        with io.open(core.CONTACTS, encoding="utf-8") as f:
            people = json.load(f).get("people", [])
    except (IOError, OSError, ValueError, AttributeError):
        people = []
    return [p for p in people if isinstance(p, dict) and p.get("id") and p.get("name") and p.get("active", True)]


def _key_of(p, kind):
    return (p.get("location") or "") if kind == "building" else (p.get("department") or "")


def group_colours(people, kind, cfg):
    """{name: palette id} for every department (or building): the user's pick, else one from AUTO by the name's place in the sorted list."""
    names = sorted(set(_key_of(p, kind) for p in people), key=lambda s: s.lower())
    mine = cfg["colours"].get(kind, {})
    auto = [c for c in AUTO if c in core.palette_ids()] or [core.DEFAULT_COLOUR]        # the Colour palette module may have deleted some
    return dict((n, mine.get(n) or auto[i % len(auto)]) for i, n in enumerate(names))


def _status_text(st, detail):
    t = st["label"]
    if detail:
        t += " \u00b7 " + ((st["prefix"] + " ") if st["prefix"] and st["needs"] == "date" else "") + detail
    return t


def snapshot(data=None):
    """What the board draws (data source / api "checkin")."""
    data = data or _load()
    cfg, menu = config(data), statuses(data)
    by_code = dict((s["code"], s) for s in menu)
    people = sorted(_roster(), key=lambda p: (p.get("order", 0), p["name"].lower()))
    colour_of = group_colours(people, cfg["colour_by"], cfg)
    photos = _photos()
    groups, index = [], {}
    for p in people:
        gname = _key_of(p, cfg["group_by"]) or ("No building" if cfg["group_by"] == "building" else "No department")
        st = data["people"].get(p["id"]) or {}
        status = by_code.get(st.get("status"))
        is_in = bool(st.get("in")) and True
        base = colour_of.get(_key_of(p, cfg["colour_by"]), "blue")
        detail = str(st.get("detail") or "")
        item = {"id": p["id"], "name": p["name"], "role": p.get("role", ""), "phone": p.get("phone", ""), "department": p.get("department", ""),
                "building": p.get("location", ""), "photo": photos.get(p["id"], ""), "restrict": bool(p.get("restrictToLocation")), "in": is_in,
                "colour": status["colour"] if status else (base if is_in else ""),
                "status": status["code"] if status else "", "text": _status_text(status, detail) if status else "", "detail": detail,
                "state": "Status" if status else ("In" if is_in else "Out"), "at": st.get("at", 0), "dots": status["dots"] if status else 0}
        g = index.get(gname)
        if g is None:
            g = index[gname] = {"id": gname, "title": gname, "colour": colour_of.get(gname, "blue") if cfg["colour_by"] == cfg["group_by"] else "", "people": []}
            groups.append(g)
        g["people"].append(item)
    place = dict((n, i) for i, n in reversed(list(enumerate(cfg["group_order"]))))      # the order the user dragged the boxes into; the rest follow alphabetically
    groups.sort(key=lambda g: (place.get(g["title"], len(place)), g["title"].lower()))
    total = sum(len(g["people"]) for g in groups)
    n_in = sum(1 for g in groups for p in g["people"] if p["in"])
    buildings = sorted(set(p.get("location") or "" for p in people) - set([""]), key=str.lower)
    return {"rev": "%d.%d" % (data.get("rev", 0), _roster_stamp()), "show_title": cfg["show_title"], "group_by": cfg["group_by"], "colour_by": cfg["colour_by"], "groups": groups,
            "scroll": cfg["scroll"], "title": cfg["title"], "frame": cfg["frame"], "box": cfg["box"], "show_roles": cfg["show_roles"], "show_buildings": cfg["show_buildings"], "keyboard": cfg["keyboard"],
            "roles_shown": cfg["roles_shown"], "buildings_shown": cfg["buildings_shown"],
            "statuses": menu, "buildings": buildings, "total": total, "in": n_in,
            "text": "No people yet: import a CSV in Settings > Contacts." if not total else "%d of %d in" % (n_in, total),
            "out_colour": OUT_COLOUR}


def _person_known(pid):
    return any(p["id"] == pid for p in _roster())


def toggle(pid):
    """A tap on the INNE / UTE button: in <-> out, and the status is cleared unless it is a sticky one. Returns the new snapshot, or None for an unknown person."""
    with _lock:
        data = _load()
        if not _person_known(pid):
            return None
        cur = data["people"].get(pid) or {}
        keep = next((x for x in statuses(data) if x["code"] == cur.get("status") and x["sticky"]), None)      # a sticky status stays when the person is switched
        data["people"][pid] = {"in": not cur.get("in"), "status": keep["code"] if keep else "", "detail": cur.get("detail", "") if keep else "", "at": int(time.time())}
        _save(data)
        return snapshot(data)


def _clean_detail(st, detail):
    detail = re.sub(r"\s+", " ", str(detail or "")).strip()[:DETAIL_MAX]
    if st["needs"] == "time" and not re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", detail):
        detail = st["default"] if re.match(r"^\d\d:\d\d$", st["default"]) else ""
    if st["needs"] == "date":
        m = re.match(r"^(\d{4})-(\d\d)-(\d\d)$", detail)
        detail = "%s/%s" % (int(m.group(3)), int(m.group(2))) if m else (detail if re.match(r"^V\d{1,3}$", detail) else "")
    return detail


def set_status(pid, code, detail=""):
    """Pick a status for a person ("IN" / "OUT" set the plain state and clear the status; "" clears the status and keeps in / out).
    None for an unknown person or status."""
    with _lock:
        data = _load()
        if not _person_known(pid):
            return None
        cur = data["people"].get(pid) or {}
        now = int(time.time())
        if code in (IN, OUT):
            new = {"in": code == IN, "status": "", "detail": "", "at": now}
        elif code in ("", None):
            new = {"in": bool(cur.get("in")), "status": "", "detail": "", "at": now}
        else:
            st = dict((s["code"], s) for s in statuses(data)).get(code)
            if st is None:
                return None
            new = {"in": (not st["out"]) if st["out"] else bool(cur.get("in")), "status": code, "detail": _clean_detail(st, detail), "at": now}
        data["people"][pid] = new
        _save(data)
        return snapshot(data)


def set_all(is_in, ids=None):
    """Everyone (or the given people) in or out, statuses cleared: the start / end of the day."""
    with _lock:
        data = _load()
        known = set(p["id"] for p in _roster())
        now = int(time.time())
        for pid in (known if ids is None else known & set(ids)):
            data["people"][pid] = {"in": bool(is_in), "status": "", "detail": "", "at": now}
        _save(data)
        return snapshot(data)


def save_config(values):
    with _lock:
        data = _load()
        cur = config(data)
        if isinstance(values, dict):
            for k, allowed in (("group_by", GROUPS), ("colour_by", GROUPS), ("scroll", SCROLLS), ("frame", FRAMES), ("box", BOXES)):
                if values.get(k) in allowed:
                    cur[k] = values[k]
            for k in ("show_title", "show_roles", "show_buildings", "keyboard"):
                if isinstance(values.get(k), bool):
                    cur[k] = values[k]
            if isinstance(values.get("title"), str):
                cur["title"] = re.sub(r"\s+", " ", values["title"]).strip()[:40]
            for k in ("roles_shown", "buildings_shown"):
                if k in values and (values[k] is None or isinstance(values[k], list)):
                    cur[k] = _names(values[k])
        data["config"] = cur
        _save(data)
        return cur


def set_group_order(order):
    """Remember the order the user moved the department / building boxes into (a list of their names). Returns the config, None if bad."""
    if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
        return None
    with _lock:
        data = _load()
        cur = config(data)
        seen = []
        for x in order:
            if x and x not in seen:
                seen.append(x[:80])
        cur["group_order"] = seen[:200]
        data["config"] = cur
        _save(data)
        return cur


def set_group_colour(kind, name, colour):
    """The user's pick for a department or building; colour "" goes back to the automatic one."""
    if kind not in GROUPS or not isinstance(name, str) or not name or len(name) > 80:
        return None
    with _lock:
        data = _load()
        cur = config(data)
        if colour and _palette_id(colour, "") == "":
            return None
        if colour:
            cur["colours"][kind][name] = colour
        else:
            cur["colours"][kind].pop(name, None)
        data["config"] = cur
        _save(data)
        return cur


def _body(h, limit=8192):
    try:
        b = json.loads(h._body(limit).decode("utf-8"))
        return b if isinstance(b, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}


def _answer(h, snap, err="Unknown person or status"):
    if snap is None:
        h.send(json.dumps({"ok": False, "message": err}), "application/json", status=400)
    else:
        h.send(json.dumps({"ok": True, "checkin": snap}), "application/json")
    return True


def _get_board(h):
    h.send(json.dumps(snapshot()), "application/json")


def _post_toggle(h):
    return _answer(h, toggle(str(_body(h).get("id", ""))))


def _post_status(h):
    b = _body(h)
    return _answer(h, set_status(str(b.get("id", "")), str(b.get("code", "")), b.get("detail", "")))


def _post_order(h):
    if set_group_order(_body(h, 32768).get("order")) is None:
        h.send(json.dumps({"ok": False, "message": "order must be a list of names"}), "application/json", status=400)
    else:
        h.send(json.dumps({"ok": True, "checkin": snapshot()}), "application/json")
    return True


def _post_statuses(h):
    got = save_statuses(_body(h, 65536).get("statuses"))
    if got is None:
        h.send(json.dumps({"ok": False, "message": "Every status needs a name (at most 16 statuses)"}), "application/json", status=400)
    else:
        h.send(json.dumps({"ok": True, "statuses": got, "checkin": snapshot()}), "application/json")
    return True


def _post_all(h):
    b = _body(h)
    return _answer(h, set_all(bool(b.get("in")), b.get("ids") if isinstance(b.get("ids"), list) else None))


def _config_reply():
    c = config()
    snap = snapshot()
    kinds = {}
    for kind in GROUPS:
        people = _roster()
        cols = group_colours(people, kind, c)
        kinds[kind] = [{"name": n or "(none)", "key": n, "colour": cols[n], "own": n in c["colours"][kind]} for n in sorted(cols, key=lambda s: s.lower()) if n]
    roster = _roster()
    roles = sorted(set(p.get("role", "") for p in roster) - set([""]), key=str.lower)
    buildings = sorted(set(p.get("location", "") for p in roster) - set([""]), key=str.lower)
    return {"values": dict((k, c[k]) for k in ("show_title", "title", "group_by", "colour_by", "scroll", "frame", "box", "show_roles", "show_buildings", "keyboard", "roles_shown", "buildings_shown")),
            "options": {"groups": [{"value": "department", "label": "Department"}, {"value": "building", "label": "Building"}],
                        "frames": [{"value": "none", "label": "None"}, {"value": "thin", "label": "Thin"}, {"value": "thick", "label": "Thick"}],
                        "boxes": [{"value": "neutral", "label": "Neutral (grey)"}, {"value": "board", "label": "The board colour"}],
                        "scrolls": [{"value": "off", "label": "Off"}, {"value": "auto", "label": "Auto (when it does not fit)"}, {"value": "status", "label": "Auto, only the status"}, {"value": "on", "label": "On (always)"}],
                        "roles": [{"value": r, "label": r} for r in roles], "buildings": [{"value": b, "label": b} for b in buildings]},
            "texts": {"show_title": "Shown" if c["show_title"] else "Hidden", "group_by": c["group_by"].capitalize(), "colour_by": c["colour_by"].capitalize()},
            "colours": kinds, "total": snap["total"]}


def _get_config(h):
    h.send(json.dumps(_config_reply()), "application/json")


def _post_config(h):
    save_config(_body(h).get("values"))
    h.send(json.dumps(_config_reply()), "application/json")
    return True


def _post_colour(h):
    b = _body(h)
    ok = set_group_colour(str(b.get("kind", "")), b.get("name"), str(b.get("colour") or ""))
    if ok is None:
        h.send(json.dumps({"ok": False}), "application/json", status=400)
    else:
        h.send(json.dumps(_config_reply()), "application/json")
    return True


def api(d, warnings):
    """Every /api answer carries the board, so each screen follows the others (it is a few kilobytes for a hundred people)."""
    d["checkin"] = snapshot()


OPEN = ("/checkin/toggle", "/checkin/status")       # tapping people in and out works while Settings is locked with the PIN
GET = {"/checkin": _get_board, "/checkin/config": _get_config}
POST = {"/checkin/toggle": _post_toggle, "/checkin/status": _post_status, "/checkin/all": _post_all,
        "/checkin/config": _post_config, "/checkin/colour": _post_colour, "/checkin/order": _post_order, "/checkin/statuses": _post_statuses}
