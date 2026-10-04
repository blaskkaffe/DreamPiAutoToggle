# DreamPi Netswitch add-on - Status LED module: what other modules can ask of it (inputs), see netswitch_bus.py. Python 2 and 3, only
# the base and files (the LED service reads them), so any process can ask.
import json
import os
import time

import netswitch_core as core

SLOTS = ("a", "b", "c")


def alert(params, ctx):
    """Input "alert" {"slot": "a" | "b" | "c", "seconds"}: the LED message "Alert A / B / C" is true for that many seconds. What it looks
    like is up to the user: put the message in a colour row of Settings > Status LED."""
    slot = (params or {}).get("slot")
    if slot not in SLOTS:
        raise ValueError("unknown alert %r" % (slot,))
    try:
        seconds = min(3600.0, max(1.0, float(params.get("seconds", 10))))
    except (TypeError, ValueError):
        seconds = 10.0
    now = time.time()
    try:
        with open(core.LED_ALERTS) as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        data = {}
    data = dict((k, v) for k, v in data.items() if isinstance(v, (int, float)) and v > now) if isinstance(data, dict) else {}
    data[slot] = now + seconds
    tmp = core.LED_ALERTS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.rename(tmp, core.LED_ALERTS)
    return {"slot": slot, "seconds": seconds}


INPUTS = {"alert": alert}
