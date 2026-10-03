# DreamPi Netswitch add-on - a simple dashboard clock.
# Works on Python 3 and 2.7.
import json
import os
import time

import netswitch_core as core

FORMATS = ("24h", "12h", "beat")
LABELS = {"24h": "24-hour", "12h": "12-hour", "beat": ".beat"}
DEFAULT_FORMAT = "24h"


def _clean(value):
    """A known format name, or the default."""
    value = str(value or "").strip().lower()
    return value if value in FORMATS else DEFAULT_FORMAT


def read_format():
    """Which time style the dashboard should use."""
    try:
        with open(core.CLOCK_MODE) as f:
            return _clean(f.read())
    except (IOError, OSError):
        return DEFAULT_FORMAT


def save_format(value):
    """Save the selected clock mode and return it."""
    value = _clean(value)
    tmp = core.CLOCK_MODE + ".tmp"
    with open(tmp, "w") as f:
        f.write(value)
    os.rename(tmp, core.CLOCK_MODE)
    return value


def beats(now=None):
    """Swatch Internet Time: the day in BMT (Biel Mean Time = UTC+1, no summer time) cut into 1000 beats of 86.4 s.
    It is the same everywhere, so it ignores the Pi's own time zone."""
    now = time.time() if now is None else now
    return int(((now + 3600) % 86400) / 86.4) % 1000


def format_time(mode, now=None):
    """What the dashboard should show for a given mode at unix time now (default: this moment)."""
    now = time.time() if now is None else now
    mode = _clean(mode)
    if mode == "beat":
        return "@%03d" % beats(now)
    local = time.localtime(now)
    if mode == "12h":
        return "%d:%s" % (int(time.strftime("%I", local)), time.strftime("%M:%S %p", local))
    return time.strftime("%H:%M:%S", local)


def _reply():
    mode = read_format()
    return {"values": {"format": mode},
            "texts": {"clock": "Shown as %s" % LABELS[mode]},
            "options": {"formats": [{"value": f, "label": LABELS[f]} for f in FORMATS]}}


def _get(h):
    h.send(json.dumps(_reply()), "application/json")


def _post(h):
    try:
        body = json.loads(h._body(4096).decode("utf-8"))
    except (ValueError, IOError, OSError, AttributeError) as e:
        return h.send(str(e), "text/plain; charset=utf-8", status=400)
    values = body.get("values") if isinstance(body, dict) else None
    if not isinstance(values, dict):
        values = {}
    save_format(values.get("format"))
    h.send(json.dumps(_reply()), "application/json")
    return True


GET = {"/clock": _get}
POST = {"/clock": _post}


def api(d, warnings):
    mode = read_format()
    d["clock"] = {"text": format_time(mode), "mode": mode, "label": LABELS[mode]}
