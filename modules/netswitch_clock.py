# DreamPi Netswitch add-on - a simple dashboard clock.
# Works on Python 3 and 2.7.
import datetime
import json
import os

import netswitch_core as core

FORMATS = ("24h", "12h", "beat")
DEFAULT_FORMAT = "24h"


def read_format():
    """Which time style the dashboard should use."""
    try:
        with open(core.CLOCK_MODE) as f:
            mode = f.read().strip().lower()
    except (IOError, OSError):
        return DEFAULT_FORMAT
    return mode if mode in FORMATS else DEFAULT_FORMAT


def save_format(value):
    """Save the selected clock mode and return it."""
    if value is None:
        value = DEFAULT_FORMAT
    value = str(value).strip().lower()
    if value not in FORMATS:
        value = DEFAULT_FORMAT
    tmp = core.CLOCK_MODE + ".tmp"
    with open(tmp, "w") as f:
        f.write(value)
    os.rename(tmp, core.CLOCK_MODE)
    return value


def _seconds(dt):
    return dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1000000.0


def format_time(mode, dt=None):
    """What the dashboard should show for a given mode."""
    dt = dt or datetime.datetime.now()
    mode = (mode or DEFAULT_FORMAT).lower()
    if mode == "12h":
        return dt.strftime("%I:%M:%S %p")
    if mode == "beat":
        return "@%03d" % int((( _seconds(dt) + 1.0) / 86.4))
    return dt.strftime("%H:%M:%S")


def _reply():
    mode = read_format()
    return {"values": {"format": mode},
            "texts": {"clock": "Dashboard clock format"},
            "options": {"formats": [{"value": f, "label": {"24h": "24-hour", "12h": "12-hour", "beat": ".beat"}[f]} for f in FORMATS]}}


def _get(h):
    h.send(json.dumps(_reply()), "application/json")


def _post(h):
    try:
        body = json.loads(h._body(4096).decode("utf-8"))
    except (ValueError, IOError, OSError, AttributeError) as e:
        return h.send(str(e), "text/plain; charset=utf-8", status=400)
    values = body.get("values") if isinstance(body, dict) else {}
    if not isinstance(values, dict):
        values = {}
    save_format(values.get("format"))
    h.send(json.dumps(_reply()), "application/json")
    return True


GET = {"/clock": _get}
POST = {"/clock": _post}


def api(d, warnings):
    mode = read_format()
    d["clock"] = {"text": format_time(mode), "mode": mode, "label": {"24h": "24-hour", "12h": "12-hour", "beat": ".beat"}[mode]}
