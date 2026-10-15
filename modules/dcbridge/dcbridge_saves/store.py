"""Save bookkeeping: an index of what is on the card, a history of every slot
version ever seen, and a queue of edits that wait for a safe moment.

On-disk layout (state_dir, default /var/lib/dcbridge/saves):
    index.json                          last scan of the card
    history/<SERIAL>/SLOT<n>/<UTC stamp>_<sha1-8>_<reason>.VMU
    pending/<id>.json  (+ <id>.bin)     edits not yet written to the card

Edits are only written into the image when the Dreamcast starts the card
after a cold boot (see daemon.py), because KallistiOS caches the FAT while
the card is mounted and would overwrite or corrupt changes made under it.
"""
import calendar
import hashlib
import json
import os
import re
import threading
import time

from . import SAVES_DIR, LASTDISC, VMU_SIZE, NUM_SLOTS

SERIAL_RE = re.compile(r"^[A-Za-z0-9._-]{1,31}$")
HISTORY_KEEP = 30


class StoreError(Exception):
    pass


def check_serial(serial):
    if not SERIAL_RE.match(serial or ""):
        raise StoreError("invalid game serial %r (letters, digits, . _ - only)" % (serial,))
    return serial


def check_slot(slot):
    try:
        slot = int(slot)
    except (TypeError, ValueError):
        raise StoreError("slot must be 1-%d" % NUM_SLOTS)
    if not 1 <= slot <= NUM_SLOTS:
        raise StoreError("slot must be 1-%d" % NUM_SLOTS)
    return slot


def slot_path(serial, slot, ext="VMU"):
    return "%s/%s/SLOT%d.%s" % (SAVES_DIR, serial, slot, ext)


def _utc_stamp(t=None):
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime(t if t is not None else time.time()))


def _atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp, path)


class SaveStore(object):
    def __init__(self, state_dir):
        self.dir = state_dir
        self.hist_dir = os.path.join(state_dir, "history")
        self.pend_dir = os.path.join(state_dir, "pending")
        for d in (self.hist_dir, self.pend_dir):
            if not os.path.isdir(d):
                os.makedirs(d)
        self.lock = threading.RLock()
        self.index = {"games": {}, "lastdisc": None, "scanned_at": None}
        p = os.path.join(state_dir, "index.json")
        if os.path.exists(p):
            try:
                with open(p) as f:
                    self.index = json.load(f)
            except ValueError:
                pass

    # ------------------------------------------------------------------ index
    def _save_index(self):
        _atomic_write(os.path.join(self.dir, "index.json"),
                      json.dumps(self.index, indent=1, sort_keys=True).encode())

    def rescan(self, fat, fat_lock=None):
        """Re-read the card. Every new or changed slot is copied into history.
        fat_lock (if given) is taken per file so the disk server never waits long."""
        lock = fat_lock or threading.RLock()
        with lock:
            paths = fat.walk(SAVES_DIR)
            lastdisc = fat.read(LASTDISC)
        games = {}
        changes = []
        for p in paths:
            m = re.match(r"^%s/([^/]+)/SLOT([1-%d])\.VMU$" % (re.escape(SAVES_DIR), NUM_SLOTS), p, re.I)
            if not m:
                continue
            serial, slot = m.group(1), int(m.group(2))
            if not SERIAL_RE.match(serial):
                continue                                  # not an openMenu game folder
            with lock:
                data = fat.read(p)
                label = fat.read(slot_path(serial, slot, "TXT"))
            g = games.setdefault(serial, {"title": None, "slots": {}})
            if data is None:
                continue
            sha = hashlib.sha1(data).hexdigest()
            old = self.index.get("games", {}).get(serial, {}).get("slots", {}).get(str(slot))
            entry = {
                "sha1": sha,
                "size": len(data),
                "valid": len(data) == VMU_SIZE,
                "label": _clean_label(label),
                "changed_at": old["changed_at"] if old and old.get("sha1") == sha else time.time(),
            }
            g["slots"][str(slot)] = entry
            if entry["valid"] and (not old or old.get("sha1") != sha):
                if self.history_add(serial, slot, data, "dreamcast"):
                    changes.append((serial, slot))
        for serial, g in games.items():
            with lock:
                t = fat.read("%s/%s/TITLE.TXT" % (SAVES_DIR, serial))
            if t:
                g["title"] = t.decode("latin-1").strip()
        with self.lock:
            self.index = {
                "games": games,
                "lastdisc": lastdisc.decode("latin-1").strip() if lastdisc else None,
                "scanned_at": time.time(),
            }
            self._save_index()
        return changes

    def lastdisc(self):
        """(serial, slot) openMenu will back the physical VMU up into on its next boot."""
        ld = self.index.get("lastdisc")
        if not ld:
            return None
        m = re.match(r"^(.*)-([1-%d])$" % NUM_SLOTS, ld)
        return (m.group(1), int(m.group(2))) if m else (ld, 1)

    # ---------------------------------------------------------------- history
    def _hdir(self, serial, slot):
        return os.path.join(self.hist_dir, check_serial(serial), "SLOT%d" % check_slot(slot))

    def history_add(self, serial, slot, data, reason):
        d = self._hdir(serial, slot)
        if not os.path.isdir(d):
            os.makedirs(d)
        sha = hashlib.sha1(data).hexdigest()
        existing = self.history_list(serial, slot)
        if existing and existing[0]["sha1"].startswith(sha[:8]):
            return False                                  # newest version already stored
        name = "%s_%s_%s.VMU" % (_utc_stamp(), sha[:8], re.sub(r"[^a-z]", "", reason)[:12] or "x")
        _atomic_write(os.path.join(d, name), data)
        for old in self.history_list(serial, slot)[HISTORY_KEEP:]:
            os.unlink(os.path.join(d, old["id"]))
        return True

    def history_list(self, serial, slot):
        d = self._hdir(serial, slot)
        if not os.path.isdir(d):
            return []
        out = []
        for name in sorted(os.listdir(d), reverse=True):
            m = re.match(r"^(\d{8}-\d{6})_([0-9a-f]{8})_([a-z]+)\.VMU$", name)
            if not m:
                continue
            t = calendar.timegm(time.strptime(m.group(1), "%Y%m%d-%H%M%S"))
            out.append({"id": name, "time": t, "sha1": m.group(2), "reason": m.group(3),
                        "size": os.path.getsize(os.path.join(d, name))})
        return out

    def history_get(self, serial, slot, hid):
        if not re.match(r"^[\w.-]+\.VMU$", hid or ""):
            raise StoreError("bad history id")
        p = os.path.join(self._hdir(serial, slot), hid)
        if not os.path.isfile(p):
            raise StoreError("no such version")
        with open(p, "rb") as f:
            return f.read()

    # ---------------------------------------------------------------- pending
    def _queue(self, entry, blob=None):
        with self.lock:
            pid = "%s-%06d" % (_utc_stamp(), int((time.time() % 1) * 1e6))
            while os.path.exists(os.path.join(self.pend_dir, pid + ".json")):
                pid += "x"
            entry["id"] = pid
            entry["created"] = time.time()
            if blob is not None:
                _atomic_write(os.path.join(self.pend_dir, pid + ".bin"), blob)
            _atomic_write(os.path.join(self.pend_dir, pid + ".json"), json.dumps(entry).encode())
            return entry

    def queue_put(self, serial, slot, data, title=None, source="upload"):
        check_serial(serial)
        slot = check_slot(slot)
        if len(data) != VMU_SIZE:
            raise StoreError("a VMU save must be exactly %d bytes (got %d)" % (VMU_SIZE, len(data)))
        if title is not None:
            title = title.strip()[:63]
        return self._queue({"action": "put", "serial": serial, "slot": slot,
                            "title": title, "source": source}, data)

    def queue_restore(self, serial, slot, hid):
        return self.queue_put(serial, slot, self.history_get(serial, slot, hid), source="restore")

    def queue_label(self, serial, slot, label):
        check_serial(serial)
        return self._queue({"action": "label", "serial": serial, "slot": check_slot(slot),
                            "label": _clean_label((label or "").encode("latin-1", "replace"))})

    def queue_delete(self, serial, slot):
        check_serial(serial)
        return self._queue({"action": "delete", "serial": serial, "slot": check_slot(slot)})

    def pending_list(self):
        out = []
        for name in sorted(os.listdir(self.pend_dir)):
            if name.endswith(".json"):
                try:
                    with open(os.path.join(self.pend_dir, name)) as f:
                        out.append(json.load(f))
                except (ValueError, IOError):
                    pass
        return out

    def pending_cancel(self, pid):
        if not re.match(r"^[\w-]+$", pid or ""):
            raise StoreError("bad id")
        found = False
        for ext in (".json", ".bin"):
            p = os.path.join(self.pend_dir, pid + ext)
            if os.path.exists(p):
                os.unlink(p)
                found = True
        if not found:
            raise StoreError("no such pending change")

    def apply_pending(self, fat):
        """Write queued edits into the image. Only call while the Dreamcast does
        not have the card mounted. Returns the number of edits applied."""
        applied = 0
        for e in self.pending_list():
            serial, slot = e["serial"], e["slot"]
            vmu = slot_path(serial, slot)
            if e["action"] == "put":
                with open(os.path.join(self.pend_dir, e["id"] + ".bin"), "rb") as f:
                    data = f.read()
                old = fat.read(vmu)
                if old and len(old) == VMU_SIZE:
                    self.history_add(serial, slot, old, "replaced")   # never lose the card copy
                fat.write(vmu, data)
                self.history_add(serial, slot, data, e.get("source", "upload"))
                title_path = "%s/%s/TITLE.TXT" % (SAVES_DIR, serial)
                if e.get("title") and not fat.exists(title_path):
                    fat.write(title_path, e["title"].encode("latin-1", "replace"))
            elif e["action"] == "label":
                if e["label"]:
                    fat.write(slot_path(serial, slot, "TXT"), e["label"].encode("latin-1", "replace"))
                else:
                    fat.delete(slot_path(serial, slot, "TXT"))
            elif e["action"] == "delete":
                old = fat.read(vmu)
                if old and len(old) == VMU_SIZE:
                    self.history_add(serial, slot, old, "deleted")
                fat.delete(vmu)
                fat.delete(slot_path(serial, slot, "TXT"))
            self.pending_cancel(e["id"])
            applied += 1
        return applied

    # --------------------------------------------------------------- summary
    def summary(self):
        """Everything the web page needs, in one structure."""
        pend = self.pending_list()
        ld = self.lastdisc()
        games = []
        idx_games = self.index.get("games", {})
        serials = set(idx_games) | set(p["serial"] for p in pend)
        for serial in sorted(serials):
            g = idx_games.get(serial, {"title": None, "slots": {}})
            slots = []
            for n in range(1, NUM_SLOTS + 1):
                s = g["slots"].get(str(n))
                hist = self.history_list(serial, n)
                p = [x for x in pend if x["serial"] == serial and x["slot"] == n]
                if not s and not hist and not p:
                    continue
                slots.append({
                    "slot": n,
                    "on_card": bool(s),
                    "valid": bool(s and s["valid"]),
                    "label": s["label"] if s else None,
                    "changed_at": s["changed_at"] if s else None,
                    "sha1": s["sha1"][:8] if s else None,
                    "history": len(hist),
                    "pending": [{"id": x["id"], "action": x["action"]} for x in p],
                    "lastdisc": ld == (serial, n),
                })
            title = g.get("title") or next((x.get("title") for x in pend if x["serial"] == serial and x.get("title")), None)
            games.append({"serial": serial, "title": title, "slots": slots})
        return {"games": games, "lastdisc": self.index.get("lastdisc"),
                "scanned_at": self.index.get("scanned_at"), "pending": len(pend)}


def _clean_label(raw):
    """openMenu shows the first line of SLOTn.TXT, trimmed, max 28 chars."""
    if not raw:
        return None
    s = raw.decode("latin-1", "replace") if isinstance(raw, bytes) else raw
    s = s.replace("\r", "\n").strip().split("\n")[0].strip()
    return s[:28] or None
