# DreamPi Netswitch add-on - LED module, web side: what the page's LED settings talk to. The settings themselves
# (led.json, the message list, priorities) are in netswitch_ledconfig.py, shared with the LED service.
#   GET/POST /ledconfig   the calibration (white balance, global level) and what its pop-up needs
#   GET/POST /ledrows     the looks as the standard "triggers" rows (one per colour group, the order is the priority; the messages a row
#                         has are its triggers, offered by the enabled modules: module.json "led_messages")
#   POST /wbtest, /wbtestdone   hold the LED at solid white while the white balance is adjusted
# api() gives the DreamPi dot on the main page the look of the LED message that is showing.
import json
import os

import netswitch_core as core
import netswitch_ledconfig as ledconfig


def _config_reply():
    sel = "dcnet" if os.path.exists(core.FLAG) else "dcnow"
    cfg = ledconfig.led_config()
    return {"config": {"max_brightness": cfg["max_brightness"], "white_balance": cfg["white_balance"], "order": cfg["order"]},
            "token_ui": {t: {"ui": core.network_colour(n)["ui"], "ui_l": core.network_colour(n)["ui_l"]} for t, n in (("dcnow", "dcnow"), ("dcnet", "dcnet"), ("network", sel))},
            "count": ledconfig.led_count(), "installed": ledconfig.led_count() > 0}


def _get_config(h):
    """The calibration (white balance, global level) and what the page needs for it. The looks are /ledrows."""
    h.send(json.dumps(_config_reply()), "application/json")


def _post_config(h):
    """Save the calibration (led.json). The looks are POST /ledrows and the wire order the hardware form's (POST /ledhardware): they are kept."""
    try:
        data = json.loads(h._body(65536).decode("utf-8"))
        cfg = ledconfig.led_config()
        for key in ("max_brightness", "white_balance", "gamma"):
            if isinstance(data, dict) and key in data:
                cfg[key] = data[key]
        ledconfig.save_led_config(cfg)
    except (ValueError, IOError, OSError) as e:
        h.send(str(e), "text/plain; charset=utf-8", status=400)
        return True
    h.send(json.dumps(_config_reply()), "application/json")
    return True


# ---- the rows (the standard "triggers" widget): one row per colour group, the order is the priority
def _pct(level):
    v = level * 100
    return "%d%%" % int(round(v)) if v >= 10 or v == 0 else "%s%%" % ("%.1f" % v).rstrip("0").rstrip(".")


def _colour_names():
    names = dict((c["id"], c["name"]) for c in core.colours())
    names.update(dict(ledconfig.COLOUR_TOKENS))
    return names


def _effect_text(g):
    label = dict((e[0], e[1]) for e in ledconfig.EFFECTS).get(g["effect"], g["effect"]).lower()
    return label if g["effect"] == "solid" else "%s %s" % (g["speed"], label)


def _rows_reply():
    cfg, count = ledconfig.led_config(), ledconfig.led_count()
    names, msgs = _colour_names(), dict((m["key"], m) for m in ledconfig.messages())
    known = {}                                       # the label of every message, also of a module that is off (its rows keep it)
    for mod in core.module_names():
        for m in (core.module_manifest(mod) or {}).get("led_messages", []):
            known.setdefault(m.get("id"), m.get("label"))
    rows = []
    for g in cfg["groups"]:
        sub = ["Global level %s" % _pct(cfg["max_brightness"]) if g["brightness"] is None else "Level %s" % _pct(g["brightness"])]
        if count > 1 and g["leds"]:
            sub.append("LED %d" % g["leds"][0] if g["leds"][0] == g["leds"][1] else "LEDs %d-%d" % tuple(g["leds"]))
        rows.append({"id": g["id"], "title": "%s, %s" % (names.get(g["colour"], g["colour"]), _effect_text(g)), "sub": u" \u00b7 ".join(sub),
                     "look": {"colour": g["colour"], "effect": g["effect"], "speed": g["speed"]},
                     "items": [{"value": k, "label": known.get(k) or k} for k in g["messages"]],
                     "opts": {"colour": g["colour"], "effect": g["effect"], "speed": g["speed"], "brightness": g["brightness"], "leds": g["leds"]}})
    options = [{"key": "colour", "type": "colour", "label": "Colour", "options": "colours"},
               {"key": "effect", "type": "choice", "label": "Animation", "options": "effects"},
               {"key": "speed", "type": "choice", "label": "Speed", "options": "speeds", "disabled_if": {"key": "effect", "value": "solid"}},
               {"key": "brightness", "type": "slider", "label": "Level", "scale": "log100", "default": cfg["max_brightness"],
                "null_text": "Uses the global level from Calibration", "own_text": "Its own level", "null_button": "Use global"}]
    if count > 1:
        options.append({"key": "leds", "type": "range", "label": "LEDs", "max": count})
    used = set(g["colour"] for g in cfg["groups"])
    first = [c["id"] for c in core.colours() if c["id"] not in used and not c["id"].startswith("bright-")] or [core.colours()[0]["id"]]
    default = ledconfig.default_led_config()
    return {"rows": rows, "options": options,
            "lists": {"colours": [{"value": c["id"], "label": c["name"]} for c in core.colours()] + [{"value": t[0], "label": t[1]} for t in ledconfig.COLOUR_TOKENS],
                      "effects": [{"value": e[0], "label": e[1]} for e in ledconfig.EFFECTS],
                      "speeds": [{"value": "slow", "label": "Slow"}, {"value": "fast", "label": "Fast"}]},
            "choices": [{"value": m["key"], "label": m["label"], "sub": m["description"], "group": m["group"]} for m in msgs.values()],
            "new": {"opts": {"colour": first[0], "effect": "solid", "speed": "slow", "brightness": None, "leds": None}},
            "defaults": {"rows": _default_rows(default["groups"], known)},
            "note": "",
            "rules": {"sort": True, "unique": True, "free": False, "max_rows": ledconfig.MAX_GROUPS, "add_row": "Add colour", "add_label": "Add",
                      "add_title": "Add messages", "edit_label": "Edit", "restore": "Restore defaults",
                      "restore_confirm": "Put the colour rows back as they were when the add-on was installed? Calibration is kept.",
                      "help": "Each row is a look: a colour, an animation (solid or blinking), a level and, on a strip, which LEDs. The messages in a row "
                              "give them that look; a message can be in one row only, and a message in no row never lights the LEDs.\n"
                              "The top row has priority: when messages of several rows are true at once on the same LEDs, the highest row shows. "
                              "Drag a row by its handle to move it."}}


def _default_rows(groups, known):
    return [{"id": g["id"], "title": "", "sub": "", "items": [{"value": k, "label": known.get(k) or k} for k in g["messages"]],
             "opts": {"colour": g["colour"], "effect": g["effect"], "speed": g["speed"], "brightness": g["brightness"], "leds": g["leds"]}} for g in groups]


def _get_rows(h):
    h.send(json.dumps(_rows_reply()), "application/json")


def _post_rows(h):
    """Save the looks: {"rows": [{"id", "items": [message keys], "opts": {colour, effect, speed, brightness, leds}}]}, top row first."""
    try:
        data = json.loads(h._body(65536).decode("utf-8"))
        groups = []
        for r in data.get("rows") if isinstance(data, dict) and isinstance(data.get("rows"), list) else []:
            o = r.get("opts") if isinstance(r, dict) and isinstance(r.get("opts"), dict) else {}
            items = r.get("items") if isinstance(r.get("items"), list) else []
            groups.append({"id": r.get("id"), "colour": o.get("colour"), "effect": o.get("effect"), "speed": o.get("speed"),
                           "brightness": o.get("brightness"), "leds": o.get("leds"),
                           "messages": [i["value"] if isinstance(i, dict) else i for i in items]})
        cfg = ledconfig.led_config()
        cfg["groups"] = groups
        ledconfig.save_led_config(cfg)
    except (ValueError, IOError, OSError, AttributeError, KeyError) as e:
        h.send(str(e), "text/plain; charset=utf-8", status=400)
        return True
    h.send(json.dumps(_rows_reply()), "application/json")
    return True


def _hardware_reply():
    count, order, gpio = ledconfig.led_count(), ledconfig.led_config()["order"], ledconfig.led_gpio()
    return {"values": {"led_count": count, "led_order": order, "led_gpio": gpio},
            "texts": {"led": "%d %s LED%s connected to GPIO%d" % (count, order, "" if count == 1 else "s", gpio)},
            "options": {"orders": [{"value": o, "label": o} for o in ledconfig.LED_ORDERS],
                        "gpios": [{"value": g, "label": "GPIO%d" % g} for g in ledconfig.GPIO_PINS]}}


def _get_hardware(h):
    h.send(json.dumps(_hardware_reply()), "application/json")


def _post_hardware(h):
    """The LED row of Settings > GPIO: how many LEDs, their wire order and the output pin (the standard form answer)."""
    try:
        v = json.loads(h._body(4096).decode("utf-8")).get("values") or {}
        if "led_count" in v:
            ledconfig.save_led_count(v["led_count"])
        if "led_gpio" in v:
            ledconfig.save_led_gpio(v["led_gpio"])
        if "led_order" in v:
            cfg = ledconfig.led_config()
            cfg["order"] = v["led_order"]
            ledconfig.save_led_config(cfg)
    except (ValueError, IOError, OSError, AttributeError) as e:
        h.send(str(e), "text/plain; charset=utf-8", status=400)
        return True
    h.send(json.dumps(_hardware_reply()), "application/json")
    return True


def _post_wbtest(h):
    """Hold the LED at one colour for a few seconds: white (the white balance) or {"colour": "#rrggbb"} (the colour being calibrated)."""
    colour = None
    try:
        body = json.loads(h._body(1024).decode("utf-8") or "{}")
        colour = body.get("colour") if isinstance(body, dict) else None
    except (ValueError, IOError, OSError, AttributeError):
        pass
    ledconfig.touch_wb_test(colour)


def _post_wbtest_done(h):
    ledconfig.clear_wb_test()


def _colours_reply():
    return {"colours": [{"id": c["id"], "name": c["name"], "ui": c["ui"], "led": c["led"], "ui_default": c["ui_default"],
                         "led_default": c["led_default"], "fixed": c["id"] == "network"} for c in core.colours()]}


def _get_colours(h):
    h.send(json.dumps(_colours_reply()), "application/json")


def _post_colours(h):
    """The palette editor: {"id", "ui", "led"} changes a colour on screen and / or on the LED; {"reset": id | "all"} puts it back."""
    try:
        body = json.loads(h._body(1024).decode("utf-8"))
        if not isinstance(body, dict):
            raise ValueError("not an object")
        if "reset" in body:
            core.reset_palette(None if body["reset"] == "all" else body["reset"])
        elif not core.set_palette_colour(body.get("id"), body.get("ui"), body.get("led")):
            raise ValueError("not a palette colour")
    except (ValueError, IOError, OSError) as e:
        h.send(str(e), "text/plain; charset=utf-8", status=400)
        return True
    h.send(json.dumps(_colours_reply()), "application/json")
    return True


GET = {"/ledconfig": _get_config, "/ledrows": _get_rows, "/ledhardware": _get_hardware, "/ledcolours": _get_colours}
POST = {"/ledconfig": _post_config, "/ledrows": _post_rows, "/ledhardware": _post_hardware, "/wbtest": _post_wbtest, "/wbtestdone": _post_wbtest_done,
        "/ledcolours": _post_colours}


def api(d, warnings):
    """The DreamPi dot previews the look of the LED message that is showing (the network switcher fills in the rest); the
    page hides the LED settings while the LED count is 0."""
    count = ledconfig.led_count()
    sel = "dcnet" if os.path.exists(core.FLAG) else "dcnow"
    tokens = dict((t, {"ui": core.network_colour(n)["ui"], "ui_l": core.network_colour(n)["ui_l"]}) for t, n in (("dcnow", "dcnow"), ("dcnet", "dcnet"), ("network", sel)))
    d["led"] = {"installed": count > 0, "count": count, "title": "Status LED" + (" (%d LEDs)" % count if count > 1 else ""), "tokens": tokens}
    d.setdefault("dreampi", {})["look"] = ledconfig.dreampi_dot()
