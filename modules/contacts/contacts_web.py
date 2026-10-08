# Check-in add-on - the contacts module (web service side): the roster the check-in board is built from.
# People come from a CSV file (the columns of CheckinChicken's people.csv: name, department, role, phone, location,
# restrictToLocation; "location" is the building / area). Importing again updates people in place and never deletes anyone
# (unless "replace" is asked for, which deactivates the ones that are not in the file). A person's id comes from
# location + department + name, so their check-in state survives a re-import. The roster is CONTACTS; the check-in module
# reads that file, this module is the only one that writes it. Runs in the web service (Python 3).
import base64
import csv
import glob
import hashlib
import io
import json
import os
import re
import threading

import base_core as core

CONTACTS = os.path.join(core.BASE_DIR, "contacts.json")     # {"people": [{id, name, department, role, phone, location, restrictToLocation, active, order}]}: the contacts module's roster (imported from a CSV)
PHOTOS_DIR = os.path.join(core.BASE_DIR, "photos")           # <person id>.jpg / .png: the small profile photos (written by the contacts module, read by the check-in board)

MAX_BYTES = 1000000
MAX_PEOPLE = 2000
COLUMNS = ("name", "department", "role", "phone", "location", "restrictToLocation")
ALIASES = {"namn": "name", "avdelning": "department", "roll": "role", "telefon": "phone", "omrade": "location", "område": "location",
           "building": "location", "byggnad": "location", "restricttolocation": "restrictToLocation"}
NO_DEPARTMENT = "No department"
_lock = threading.Lock()


def _slug(s):
    s = str(s or "").strip().lower()
    for a, b in (("å", "a"), ("ä", "a"), ("ö", "o")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "x"


def person_id(name, department, location):
    key = "%s|%s|%s" % (_slug(location), _slug(department), _slug(name))
    return "p" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def _flag(s):
    return str(s or "").strip().lower() in ("1", "true", "yes", "ja", "x")


def read():
    """{"people": [person]} as saved (an empty roster when there is none)."""
    try:
        with io.open(CONTACTS, encoding="utf-8") as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        data = None
    people = data.get("people") if isinstance(data, dict) else None
    return {"people": [p for p in (people or []) if isinstance(p, dict) and p.get("id") and p.get("name")]}


def _write(data):
    tmp = CONTACTS + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=1))
    os.rename(tmp, CONTACTS)


def parse_csv(text):
    """The rows of a CSV text as dicts keyed by the canonical column names. Blank lines and lines that start with # are skipped;
    the delimiter (comma, semicolon or tab) is found from the header line. ValueError when there is no name column."""
    if text.startswith(u"﻿"):
        text = text[1:]
    lines = [l for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
    if not lines:
        return []
    head = lines[0]
    delim = max((",", ";", "\t"), key=lambda d: head.count(d))
    rows = list(csv.reader(lines, delimiter=delim))
    names = []
    for h in rows[0]:
        k = h.strip()
        k = ALIASES.get(k.lower(), k)
        names.append(next((c for c in COLUMNS if c.lower() == k.lower()), k))
    if "name" not in names:
        raise ValueError('The first line must name the columns, and one of them must be "name" (%s)' % ", ".join(COLUMNS))
    out = []
    for r in rows[1:]:
        out.append(dict((names[i], r[i].strip()) for i in range(min(len(names), len(r)))))
    return out


def import_csv(text, replace=False):
    """Merge a CSV into the roster. Returns {"added", "changed", "unchanged", "deactivated", "skipped"}. ValueError for a file
    that can't be read as a roster."""
    rows = parse_csv(text)
    with _lock:
        data = read()
        by_id = dict((p["id"], p) for p in data["people"])
        key_of = dict((person_id(p["name"], p["department"], p.get("location", "")), p["id"]) for p in data["people"])      # a person edited by hand keeps the id
        seen, added, changed, skipped = set(), 0, 0, 0
        for i, row in enumerate(rows):
            name = row.get("name", "").strip()
            if not name:
                skipped += 1
                continue
            department = row.get("department", "").strip() or NO_DEPARTMENT
            location = row.get("location", "").strip()
            pid = key_of.get(person_id(name, department, location)) or person_id(name, department, location)
            prev = by_id.get(pid)
            new = {"id": pid, "name": name, "department": department, "role": row.get("role", ""),
                   "phone": row.get("phone", "") or (prev or {}).get("phone", ""), "location": location,
                   "restrictToLocation": _flag(row["restrictToLocation"]) if "restrictToLocation" in row else bool((prev or {}).get("restrictToLocation")),
                   "active": True, "order": (prev or {}).get("order", i)}
            if prev is None:
                added += 1
            elif any(prev.get(k) != new[k] for k in new):
                changed += 1
            by_id[pid] = new
            seen.add(pid)
        if len(by_id) > MAX_PEOPLE:
            raise ValueError("Too many people (at most %d)" % MAX_PEOPLE)
        off = 0
        if replace:
            for pid, p in by_id.items():
                if pid not in seen and p.get("active", True):
                    p["active"] = False
                    off += 1
        data["people"] = sorted(by_id.values(), key=lambda p: (p.get("order", 0), p["name"].lower()))
        _write(data)
    return {"added": added, "changed": changed, "unchanged": len(seen) - added - changed, "deactivated": off, "skipped": skipped}


def set_active(pid, active):
    with _lock:
        data = read()
        for p in data["people"]:
            if p["id"] == pid:
                p["active"] = bool(active)
                _write(data)
                return True
    return False


def update_person(pid, fields):
    """Edit one person (name, department, role, phone, location, restrictToLocation; the id stays, so the status and the photo stay).
    Returns the person; ValueError with a message when there is no such person, no name, or somebody else has the same name, department and building."""
    if not isinstance(fields, dict):
        raise ValueError("Nothing to change")
    with _lock:
        data = read()
        p = next((x for x in data["people"] if x["id"] == pid), None)
        if p is None:
            raise ValueError("Unknown person")
        new = dict(p)
        for k, limit in (("name", 80), ("department", 80), ("role", 80), ("phone", 40), ("location", 80)):
            if k in fields:
                new[k] = str(fields[k] if fields[k] is not None else "").strip()[:limit]
        if "restrictToLocation" in fields:
            new["restrictToLocation"] = bool(fields["restrictToLocation"]) if isinstance(fields["restrictToLocation"], bool) else _flag(fields["restrictToLocation"])
        if not new["name"]:
            raise ValueError("A person needs a name")
        new["department"] = new["department"] or NO_DEPARTMENT
        key = person_id(new["name"], new["department"], new["location"])
        if any(x["id"] != pid and person_id(x["name"], x["department"], x.get("location", "")) == key for x in data["people"]):
            raise ValueError("Somebody else already has that name in that department and building")
        p.update(new)
        _write(data)
        return p


def delete_person(pid):
    """Remove one person for good (and their photo). True when there was such a person. (Switching a person off keeps them on file; a CSV
    import with the same name, department and building would bring a deleted person back as a new one.)"""
    with _lock:
        data = read()
        keep = [p for p in data["people"] if p["id"] != pid]
        if len(keep) == len(data["people"]):
            return False
        data["people"] = keep
        _write(data)
    path = photo_files().get(pid)
    if path:
        try:
            os.remove(path)
        except OSError:
            pass
    return True


def export_csv():
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(COLUMNS)
    for p in read()["people"]:
        if p.get("active", True):
            w.writerow([p["name"], p["department"], p.get("role", ""), p.get("phone", ""), p.get("location", ""),
                        "1" if p.get("restrictToLocation") else ""])
    return out.getvalue()


def view():
    """What the Settings box shows: counts and the people (inactive ones are greyed in the list and can be brought back)."""
    people = read()["people"]
    active = [p for p in people if p.get("active", True)]
    deps = sorted(set(p["department"] for p in active), key=str.lower)
    locs = sorted(set(p["location"] for p in active if p["location"]), key=str.lower)
    if people:
        text = "%d people in %d department%s%s" % (len(active), len(deps), "" if len(deps) == 1 else "s",
                                                   " and %d building%s" % (len(locs), "" if len(locs) == 1 else "s") if locs else "")
        if len(active) != len(people):
            text += " (%d switched off)" % (len(people) - len(active))
    else:
        text = "No people yet: import a CSV file."
    photos = dict((pid, "/contacts/photo/%s?v=%d" % (pid, os.stat(path).st_mtime_ns // 1000000)) for pid, path in photo_files().items())
    return {"text": text, "count": len(active), "columns": ", ".join(COLUMNS),
            "people": [{"id": p["id"], "photo": photos.get(p["id"], ""), "title": p["name"], "tag": p["department"] + (" / " + p["location"] if p["location"] else ""),
                        "active": p.get("active", True), "name": p["name"], "department": p["department"], "role": p.get("role", ""),
                        "phone": p.get("phone", ""), "location": p.get("location", ""), "restrict": bool(p.get("restrictToLocation"))} for p in people]}


def _get_view(h):
    h.send(json.dumps(view()), "application/json")


def _get_csv(h):
    h.send(export_csv(), "text/csv; charset=utf-8")


def _post_import(h):
    try:
        body = json.loads(h._body(MAX_BYTES).decode("utf-8"))
        result = import_csv(str(body.get("csv", "")), replace=bool(body.get("replace")))
    except (ValueError, UnicodeDecodeError, AttributeError) as e:
        h.send(json.dumps({"ok": False, "message": str(e) or "That is not a CSV file"}), "application/json", status=400)
        return True
    r = result
    msg = "Imported: %d new, %d changed, %d unchanged" % (r["added"], r["changed"], r["unchanged"])
    if r["deactivated"]:
        msg += ", %d switched off" % r["deactivated"]
    if r["skipped"]:
        msg += ", %d rows without a name skipped" % r["skipped"]
    h.send(json.dumps(dict(result, ok=True, message=msg)), "application/json")
    return True


def _post_person(h):
    try:
        body = json.loads(h._body(8192).decode("utf-8"))
        update_person(str(body.get("id", "")), body)
    except (ValueError, UnicodeDecodeError, AttributeError) as e:
        h.send(json.dumps({"ok": False, "message": str(e) or "That did not work"}), "application/json", status=400)
        return True
    h.send(json.dumps({"ok": True, "message": "Saved"}), "application/json")
    return True


def _post_delete(h):
    try:
        body = json.loads(h._body(4096).decode("utf-8"))
        ok = delete_person(str(body.get("id", "")))
    except (ValueError, UnicodeDecodeError, AttributeError):
        ok = False
    h.send(json.dumps({"ok": ok, "message": "Deleted" if ok else "Unknown person"}), "application/json", status=200 if ok else 400)
    return True


def _post_active(h):
    try:
        body = json.loads(h._body(4096).decode("utf-8"))
        ok = set_active(str(body.get("id", "")), bool(body.get("active", body.get("value"))))
    except (ValueError, UnicodeDecodeError, AttributeError):
        ok = False
    h.send(json.dumps({"ok": ok}), "application/json", status=200 if ok else 400)
    return True


PHOTO_MAX = 150000          # bytes of a stored photo (the page sends a 160 px square, a few kilobytes)
_ID_RE = re.compile(r"^p[0-9a-f]{10}$")
_TYPES = ((b"\xff\xd8\xff", "jpg", "image/jpeg"), (b"\x89PNG\r\n\x1a\n", "png", "image/png"))


def photo_files():
    """{person id: path} of the stored photos."""
    out = {}
    for path in glob.glob(os.path.join(PHOTOS_DIR, "p*.*")):
        pid = os.path.basename(path).rsplit(".", 1)[0]
        if _ID_RE.match(pid):
            out[pid] = path
    return out


def save_photo(pid, data_url):
    """Store (or, with an empty value, remove) a person's photo; data_url is a data:image/jpeg|png;base64 URL. False for an unknown
    person, True when it is stored; ValueError for something that is not a small JPEG or PNG."""
    if not _ID_RE.match(pid or "") or pid not in set(p["id"] for p in read()["people"]):
        return False
    with _lock:
        for path in glob.glob(os.path.join(PHOTOS_DIR, pid + ".*")):
            os.remove(path)
        if not data_url:
            return True
        m = re.match(r"^data:image/(?:jpeg|png);base64,([A-Za-z0-9+/=]+)$", data_url)
        if not m:
            raise ValueError("The photo must be a JPEG or PNG")
        raw = base64.b64decode(m.group(1))
        kind = next((t for t in _TYPES if raw.startswith(t[0])), None)
        if kind is None or len(raw) > PHOTO_MAX:
            raise ValueError("The photo must be a small JPEG or PNG")
        if not os.path.isdir(PHOTOS_DIR):
            os.makedirs(PHOTOS_DIR)
        path = os.path.join(PHOTOS_DIR, "%s.%s" % (pid, kind[1]))
        with open(path + ".tmp", "wb") as f:
            f.write(raw)
        os.rename(path + ".tmp", path)
    return True


def _post_photo(h):
    try:
        body = json.loads(h._body(PHOTO_MAX * 2).decode("utf-8"))
        ok = save_photo(str(body.get("id", "")), str(body.get("photo") or ""))
        err = "Unknown person"
    except (ValueError, UnicodeDecodeError, AttributeError) as e:
        ok, err = False, str(e) or "That is not a photo"
    h.send(json.dumps({"ok": bool(ok), "message": "" if ok else err}), "application/json", status=200 if ok else 400)
    return True


def _get_photo(h):
    pid = h.path.split("?")[0][len("/contacts/photo/"):]
    path = photo_files().get(pid) if _ID_RE.match(pid) else None
    if not path:
        return h._refuse(404, "No photo")
    with open(path, "rb") as f:
        body = f.read()
    h.send(body, "image/png" if path.endswith(".png") else "image/jpeg", cache=3600)


GET = {"/contacts": _get_view, "/contacts.csv": _get_csv}
GET_PREFIX = {"/contacts/photo/": _get_photo}
POST = {"/contacts/import": _post_import, "/contacts/active": _post_active, "/contacts/person": _post_person, "/contacts/delete": _post_delete, "/contacts/photo": _post_photo}
PROTECTED = ("/contacts/import", "/contacts/active", "/contacts/person", "/contacts/delete")
OPEN = ("/contacts/photo",)          # a photo is set from the status menu on the board


if __name__ == "__main__":      # python3 contacts_web.py people.csv [--replace]: the same import from a shell
    import sys
    if len(sys.argv) < 2:
        sys.exit("usage: contacts_web.py people.csv [--replace]")
    with io.open(sys.argv[1], encoding="utf-8") as f:
        print(import_csv(f.read(), replace="--replace" in sys.argv[2:]))
