# DreamPi Netswitch add-on - the special phone numbers: four lists edited on the web page and read by netswitch_hook.py from
# numbers.json. Dialing a number in a list is an OUTPUT of this module (numbers.<list>, see netswitch_bus.py); what it does is
# whatever the user linked it to (Settings > Connections: select a network, show a notice ...). A "hang up" list also leaves the
# call unanswered (busy tone), a "call" list lets it connect. Works on Python 3 and 2.7.
import json
import os
import re

import netswitch_bus as bus
import netswitch_core as core

# key, label, what it does, default numbers. The hook matches a dialed string
# against the END of each number, longest match first, so an entry can be a
# short ending or a whole number, with digits, * and # (e.g. "*61#").
# (the keys are the names numbers.json has always had; what a list does is set by the links, see _title())
ACTIONS = (
    ("toggle_dcnow", "Hang-up number A", "hang up", []),
    ("toggle_dcnet", "Hang-up number B", "hang up", []),
    ("call_dcnow", "Call number A", "connect", ["11111"]),
    ("call_dcnet", "Call number B", "connect", []),
)
HANGS_UP = ("toggle_dcnow", "toggle_dcnet")     # the lists whose call is not answered (the others connect)
MIN_LEN, MAX_LEN, MAX_PER_ACTION = 3, 12, 10
_JUNK = re.compile(r"[^0-9*#]")


def default_numbers():
    return dict((a[0], list(a[3])) for a in ACTIONS)


def clean_number(text):
    """'555-0001' -> '5550001'. Only digits, * and # are kept; None when what
    is left is too short or too long to be a sensible number."""
    try:
        n = _JUNK.sub("", str(text))
    except (TypeError, ValueError):
        return None
    return n if MIN_LEN <= len(n) <= MAX_LEN else None


def clean_numbers(data):
    """Validated lists. A missing action keeps its default; a present one is
    taken as given (an empty list switches the action off). A number can only
    belong to one action (the first one listed wins), without repeats."""
    out, seen = {}, set()
    defaults = default_numbers()
    data = data if isinstance(data, dict) else {}
    for key, _label, _sub, _default in ACTIONS:
        raw = data.get(key)
        if not isinstance(raw, list):
            raw = defaults[key]
        keep = []
        for item in raw:
            n = clean_number(item)
            if n and n not in seen and len(keep) < MAX_PER_ACTION:
                seen.add(n)
                keep.append(n)
        out[key] = keep
    return out


def numbers():
    try:
        with open(core.NUMBERS) as f:
            return clean_numbers(json.load(f))
    except (IOError, OSError, ValueError):
        return default_numbers()


def save_numbers(data):
    cleaned = clean_numbers(data)
    tmp = core.NUMBERS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cleaned, f)
    os.rename(tmp, core.NUMBERS)
    return cleaned


# ---------------------------------------------------------------- the page's side (loaded by the web service)
def _what_it_does(key, decl):
    """What a list does now, from its links: "Select a network (DCNow!)" and so on (empty: nothing but the call itself)."""
    ins = dict((i["id"], i) for i in decl["inputs"])
    out = []
    for link in bus.links(decl):
        if link["from"] != "numbers." + key or link["to"] not in ins:
            continue
        out.append(bus.summary(ins[link["to"]], link["params"]))
    return out


def _title(key, decl):
    todo = _what_it_does(key, decl)
    return (", ".join(todo) if todo else "Nothing") + (" and hang up" if key in HANGS_UP else " and connect")


def _reply():
    """The standard "picker" answer (page/widgets.js W.picker): groups of items plus the rules for adding one. A group's name says
    what its numbers do, from the links (Settings > Connections)."""
    nums = numbers()
    decl = bus.declarations()
    return {"groups": [{"key": a[0], "label": _title(a[0], decl),
                        "sub": "No answer, busy tone" if a[0] in HANGS_UP else "The call connects",
                        "items": nums.get(a[0], [])} for a in ACTIONS],
            "defaults": default_numbers(),
            "rules": {"min": MIN_LEN, "max": MAX_LEN, "per_group": MAX_PER_ACTION, "allowed": "0-9*#", "unique": True,
                      "add_label": "Add", "add_title": "Add a number to {group}",
                      "min_msg": "Needs at least %d digits, * or #" % MIN_LEN,
                      "help": "Functions are triggered by numbers ending in the listed numbers.\nUse 3 - %d digits, numbers 0-9, * and # are allowed.\nWhat a list does is set in Settings > System > Connections: the name of each list says what it does now." % MAX_LEN,
                      "restore": "Restore default numbers"}}


def _get(h):
    h.send(json.dumps(_reply()), "application/json")


def _post(h):
    try:
        save_numbers(json.loads(h._body(16384).decode("utf-8")))
    except (ValueError, IOError, OSError) as e:
        h.send(str(e), "text/plain; charset=utf-8", status=400)
        return True
    h.send(json.dumps(_reply()), "application/json")
    return True


GET = {"/numbers": _get}
POST = {"/numbers": _post}
