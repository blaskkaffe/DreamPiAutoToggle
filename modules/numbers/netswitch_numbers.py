# DreamPi Netswitch add-on - the phone numbers module: rows of "an action + the numbers that trigger it", edited on the web page and
# read by netswitch_hook.py from numbers.json. The module has no actions of its own: every module announces what it can do in its
# module.json "actions" (the network switcher: toggle / DCNow! / DCNET), and a row picks one of them. A row can also say "hang up":
# the call is not answered (busy tone) after the action. A number may be in several rows (all of them run). Works on Python 3 and
# 2.7 (the hook shares the parsing: netswitch_hook.rows_from_data).
import json
import os
import re

import netswitch_core as core
import netswitch_hook as hook

MIN_LEN, MAX_LEN, MAX_PER_ROW, MAX_ROWS = 3, 12, 10, 30
_JUNK = re.compile(r"[^0-9*#]")
_ACTION = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
OPENMENU = "1111111"     # what openMenu dials; it ends with the default row's 11111
OPTIONS = [{"key": "hangup", "label": "Hang up after the action",
            "sub": "Don't answer the call: the Dreamcast gets a busy tone, like *70"}]


def default_rows():
    return [dict(r, id=str(i + 1), opts={"hangup": False}) for i, r in enumerate(hook.DEFAULT_ROWS)]


def clean_number(text):
    """'555-0001' -> '5550001'. Only digits, * and # are kept; None when what
    is left is too short or too long to be a sensible number."""
    try:
        n = _JUNK.sub("", str(text))
    except (TypeError, ValueError):
        return None
    return n if MIN_LEN <= len(n) <= MAX_LEN else None


def clean_rows(data):
    """Validated rows. A row keeps its action (even while that module is off), its numbers (cleaned, no repeats, at most
    MAX_PER_ROW) and its options; every row gets an id that is unique. A broken or missing list gives the default rows, a list
    with no rows means no numbers do anything."""
    rows = hook.rows_from_data(data)
    out, seen = [], set()
    for r in rows[:MAX_ROWS]:
        if not _ACTION.match(r["action"]):
            continue
        items = []
        for n in r["items"]:
            n = clean_number(n)
            if n and n not in items and len(items) < MAX_PER_ROW:
                items.append(n)
        rid = r["id"] if r["id"] and r["id"] not in seen else ""
        out.append({"id": rid, "action": r["action"], "items": items, "opts": {"hangup": bool(r["opts"].get("hangup"))}})
        seen.add(rid)
    n = 0
    for r in out:
        if not r["id"]:
            while str(n + 1) in seen:
                n += 1
            n += 1
            r["id"] = str(n)
            seen.add(r["id"])
    return out


def numbers():
    """The saved rows (the default row before anything was saved, or when the file can't be read)."""
    try:
        with open(core.NUMBERS) as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        return default_rows()
    return clean_rows(data)


def save_numbers(data):
    cleaned = clean_rows(data)
    tmp = core.NUMBERS + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"rows": cleaned}, f)
    os.rename(tmp, core.NUMBERS)
    return cleaned


# ---------------------------------------------------------------- the page's side (loaded by the web service)
def _reply():
    """The standard "rows" answer (page/widgets.js W.rows): the rows with their ready texts, the actions a row can pick, the options
    a row has and the rules for adding a number."""
    rows = numbers()
    actions = core.module_actions()
    known = dict((a["value"], a) for a in actions)
    out = []
    for r in rows:
        a = known.get(r["action"])
        sub = (a["sub"] if a else "This module is off or gone: the row does nothing until it is back")
        out.append({"id": r["id"], "action": r["action"], "title": a["label"] if a else r["action"], "sub": sub,
                    "items": r["items"], "opts": r["opts"], "off": a is None})
    caught = [row for row, _n in hook._matching(OPENMENU, rows) if row["action"] == "switcher.dcnow" and not row["opts"].get("hangup")]
    return {"rows": out, "actions": actions, "options": OPTIONS, "defaults": {"rows": default_rows()},
            "note": "" if caught else "No row selects DCNow! for %s, the number openMenu dials: openMenu will use the network that is "
                                       "selected, and on DCNET its login fails." % OPENMENU,
            "rules": {"min": MIN_LEN, "max": MAX_LEN, "per_row": MAX_PER_ROW, "max_rows": MAX_ROWS, "allowed": "0-9*#",
                      "add_row": "Add row", "add_row_title": "What should the numbers do?",
                      "add_label": "Add", "add_title": "Add a number", "min_msg": "Needs at least %d digits, * or #" % MIN_LEN,
                      "help": "A row runs its action when the dialed number ends with one of its numbers (3 - %d characters: 0-9, * and #); "
                              "the longest match decides, and a number can be in several rows.\n"
                              "openMenu always dials %s. It ends with 11111, so the DCNow! row with 11111 makes openMenu select DCNow! and "
                              "connect. Keep it: DCNET does not accept openMenu's login." % (MAX_LEN, OPENMENU),
                      "restore": "Restore default rows"}}


def _get(h):
    h.send(json.dumps(_reply()), "application/json")


def _post(h):
    try:
        save_numbers(json.loads(h._body(32768).decode("utf-8")))
    except (ValueError, IOError, OSError) as e:
        h.send(str(e), "text/plain; charset=utf-8", status=400)
        return True
    h.send(json.dumps(_reply()), "application/json")
    return True


GET = {"/numbers": _get}
POST = {"/numbers": _post}
