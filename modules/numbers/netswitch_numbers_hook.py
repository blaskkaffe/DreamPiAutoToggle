# DreamPi Netswitch add-on - phone numbers module, the part that runs inside DreamPi (module.json "hook").
# The DreamPi integration (modules/switcher/netswitch_dreampi.py) asks this file which rows a dialed string matches while the module is
# on; without the module numbers.json is ignored and the integration's own default row is used. The web side (netswitch_numbers.py)
# shares the parsing. Runs in DreamPi, so it must stay Python 2.7 and 3 compatible: no f-strings, no type hints.
import json
import os

NUMBERS = "numbers.json"     # in the add-on's folder: the rows, edited on the web page

# The rows of numbers.json: {"rows": [{"action": "switcher.dcnow", "items": ["11111"], "opts": {"hangup": false}}]}. A row says which
# action (a module's, announced in its module.json "actions" and done by its "hook" file) the numbers trigger; opts.hangup = do not
# answer the call (busy tone) after the action. These are the rows used until the user has saved their own.
DEFAULT_ROWS = [{"action": "switcher.dcnow", "items": ["11111"], "opts": {}}]
# the four lists of an older numbers.json -> (action, hang up)
LEGACY_LISTS = (("toggle_dcnow", "switcher.dcnow", True), ("toggle_dcnet", "switcher.dcnet", True),
                ("call_dcnow", "switcher.dcnow", False), ("call_dcnet", "switcher.dcnet", False))


def rows_from_data(data):
    """The rows of what numbers.json holds (the web page's numbers module uses this too). The older form with four lists becomes
    rows; a missing, broken or empty file gives the default rows."""
    rows = []
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        for r in data["rows"]:
            if isinstance(r, dict) and r.get("action"):
                opts = r.get("opts") if isinstance(r.get("opts"), dict) else {}
                items = r.get("items") if isinstance(r.get("items"), list) else []
                rows.append({"id": str(r.get("id") or ""), "action": str(r["action"]), "items": [str(n) for n in items if n], "opts": opts})
        return rows
    if isinstance(data, dict) and any(k[0] in data for k in LEGACY_LISTS):
        for key, action, hangup in LEGACY_LISTS:
            items = data.get(key)
            if not isinstance(items, list):
                items = ["11111"] if key == "call_dcnow" else []
            rows.append({"id": "", "action": action, "items": [str(n) for n in items if n], "opts": {"hangup": True} if hangup else {}})
        return rows
    return [dict(r, id="") for r in DEFAULT_ROWS]


def load_rows(base_dir):
    """The rows from numbers.json in the add-on's folder, or the default rows when it is missing or broken."""
    try:
        with open(os.path.join(base_dir, NUMBERS)) as f:
            return rows_from_data(json.load(f))
    except Exception:
        return rows_from_data(None)


def matching(raw_string, rows):
    """[(row, number)] for what was dialed. The dialed string only has to END with a configured number: DreamPi often hears an
    extra leading digit (e.g. 15550002) and ISP settings add prefixes or area codes, so exact matching is unreliable. The longest
    match decides, and every row that has that number runs (a number may be in several rows), in the order of the rows."""
    if not raw_string:
        return []
    found = []
    for row in rows:
        lens = [len(n) for n in row.get("items", []) if n and raw_string.endswith(n)]
        if lens:
            found.append((row, max(lens)))
    best = max([n for _r, n in found] or [0])
    return [(row, raw_string[-best:]) for row, n in found if n == best]


def matches(raw_string, base_dir):
    """What the integration asks: [(row, number)] for the dialed string, from the saved rows."""
    return matching(raw_string, load_rows(base_dir))
