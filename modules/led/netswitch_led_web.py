# DreamPi Netswitch add-on - LED module, web side: what the page's LED settings talk to. The settings themselves
# (led.json, the message list, priorities) are in netswitch_ledconfig.py, shared with the LED service.
#   GET  /ledconfig   the whole configuration plus the lists the page needs (the messages and their categories, the colours, effects)
#   POST /ledconfig   save it (and the LED count / output pin, which are not part of led.json)
#   POST /wbtest, /wbtestdone   hold the LED at solid white while the white balance is adjusted
# api() gives the DreamPi dot on the main page the look of the LED message that is showing.
import json
import os

import netswitch_core as core
import netswitch_ledconfig as ledconfig


def _get_config(h):
    sel = "dcnet" if os.path.exists(core.FLAG) else "dcnow"
    h.send(json.dumps({"config": ledconfig.led_config(), "defaults": ledconfig.default_led_config(),
                       "messages": [{"key": m[0], "label": m[1], "category": m[2], "description": m[3], "detected": m[4]} for m in ledconfig.MESSAGES],
                       "categories": ledconfig.CATEGORIES, "priority": ledconfig.PRIORITY_ORDER, "effects": ledconfig.EFFECTS,
                       "colours": ledconfig.colour_choices(),
                       "token_ui": {t: {"ui": core.network_colour(n)["ui"], "ui_l": core.network_colour(n)["ui_l"]} for t, n in (("dcnow", "dcnow"), ("dcnet", "dcnet"), ("network", sel))},
                       "count": ledconfig.led_count(), "installed": ledconfig.led_count() > 0}),
           "application/json")


def _post_config(h):
    """Save the looks (led.json). The wire order is the hardware form's (POST /ledhardware), so it is kept as it is."""
    try:
        data = json.loads(h._body(65536).decode("utf-8"))
        data["order"] = ledconfig.led_config()["order"]
        cfg = ledconfig.save_led_config(data)
    except (ValueError, IOError, OSError) as e:
        h.send(str(e), "text/plain; charset=utf-8", status=400)
        return True
    h.send(json.dumps({"config": cfg, "count": ledconfig.led_count()}), "application/json")
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


GET = {"/ledconfig": _get_config, "/ledhardware": _get_hardware, "/ledcolours": _get_colours}
POST = {"/ledconfig": _post_config, "/ledhardware": _post_hardware, "/wbtest": _post_wbtest, "/wbtestdone": _post_wbtest_done,
        "/ledcolours": _post_colours}


def api(d, warnings):
    """The DreamPi dot previews the look of the LED message that is showing (the network switcher fills in the rest); the
    page hides the LED settings while the LED count is 0."""
    count = ledconfig.led_count()
    sel = "dcnet" if os.path.exists(core.FLAG) else "dcnow"
    tokens = dict((t, {"ui": core.network_colour(n)["ui"], "ui_l": core.network_colour(n)["ui_l"]}) for t, n in (("dcnow", "dcnow"), ("dcnet", "dcnet"), ("network", sel)))
    d["led"] = {"installed": count > 0, "count": count, "title": "Status LED" + (" (%d LEDs)" % count if count > 1 else ""), "tokens": tokens}
    d.setdefault("dreampi", {})["look"] = ledconfig.dreampi_look()
