# Check-in add-on - OPTIONAL "Snow background" module, web side: the settings of the snowstorm that the page draws behind everything.
#   GET  /snow     the form reply of Settings > Snow background (amount, wind, fog, time of day)
#   POST /snow     {"values": {"amount": "normal", "wind": "breeze", "fog": "light", "time": "follow"}}
# /api has "snow": {"amount", "wind", "fog", "time"}; the page (page.js) draws the storm with WebGL from it. The day and night come from /api "daylight"
# (the sun's height at the place of the common time zone, see base_core.daylight()) unless "time" is "day" or "night".
import json
import os

import base_core as core

SNOW_CONFIG = os.path.join(core.BASE_DIR, "snow.json")
AMOUNTS = [("light", "Light"), ("normal", "Normal"), ("heavy", "Heavy"), ("blizzard", "Blizzard")]
WINDS = [("calm", "Calm"), ("breeze", "Breeze"), ("storm", "Storm")]
FOGS = [("none", "No fog"), ("light", "Light fog"), ("thick", "Thick fog")]
TIMES = [("follow", "Follows the time zone"), ("day", "Always day"), ("night", "Always night")]
DEFAULT = {"amount": "normal", "wind": "breeze", "fog": "light", "time": "follow"}
CHOICES = {"amount": AMOUNTS, "wind": WINDS, "fog": FOGS, "time": TIMES}


def config():
    out = dict(DEFAULT)
    try:
        with open(SNOW_CONFIG) as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        data = {}
    if isinstance(data, dict):
        for k, choices in CHOICES.items():
            if data.get(k) in [c[0] for c in choices]:
                out[k] = data[k]
    return out


def save_config(cfg):
    tmp = SNOW_CONFIG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, sort_keys=True)
    os.rename(tmp, SNOW_CONFIG)


def api(d, warnings):
    d["snow"] = config()


def _form_reply():
    cfg = config()
    return {"values": dict(cfg),
            "options": {"amounts": [{"value": k, "label": v} for k, v in AMOUNTS], "winds": [{"value": k, "label": v} for k, v in WINDS],
                        "fogs": [{"value": k, "label": v} for k, v in FOGS], "times": [{"value": k, "label": v} for k, v in TIMES]},
            "texts": dict((k, dict(CHOICES[k])[cfg[k]]) for k in CHOICES)}


def _get_form(h):
    h.send(json.dumps(_form_reply()), "application/json")


def _post_form(h):
    try:
        values = json.loads(h._body(1024).decode("utf-8")).get("values") or {}
    except (ValueError, AttributeError):
        h.send("Bad request", "text/plain; charset=utf-8", status=400)
        return True
    cfg = config()
    for k, choices in CHOICES.items():
        if values.get(k) in [c[0] for c in choices]:
            cfg[k] = values[k]
    save_config(cfg)
    h.send(json.dumps(_form_reply()), "application/json")
    return True


GET = {"/snow": _get_form}
POST = {"/snow": _post_form}
