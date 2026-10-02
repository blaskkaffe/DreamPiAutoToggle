# DreamPi Netswitch add-on - the phone numbers that switch networks: five lists
# (one per action) edited on the web page and read by netswitch_hook.py from
# numbers.json. Works on Python 3 and 2.7.
import json
import os
import re

import netswitch_core as core

# key, label, what it does, default numbers. The hook matches a dialed string
# against the END of each number, longest match first, so an entry can be a
# short ending or a whole number, with digits, * and # (e.g. "*61#").
ACTIONS = (
    ("reset", "Reset", "Selects DCNow! and hangs up", ["1111111#"]),
    ("toggle_dcnow", "Toggle to DCNow!", "Selects DCNow! and hangs up", ["5550001#"]),
    ("toggle_dcnet", "Toggle to DCNET", "Selects DCNET and hangs up", ["5550002#"]),
    ("call_dcnow", "Call DCNow!", "Selects DCNow! and connects to it", ["5550001"]),
    ("call_dcnet", "Call DCNET", "Selects DCNET and connects to it", ["5550002"]),
)
MIN_LEN, MAX_LEN, MAX_PER_ACTION = 3, 24, 10
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
def _reply():
    return {"numbers": numbers(), "defaults": default_numbers(),
            "actions": [{"key": a[0], "label": a[1], "sub": a[2]} for a in ACTIONS],
            "min": MIN_LEN, "max": MAX_LEN, "per_action": MAX_PER_ACTION}


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
