# DreamPi Netswitch add-on - LED module, web side: what the page's LED settings talk to. The settings themselves
# (led.json, the message list, priorities) are in netswitch_ledconfig.py, shared with the LED service.
#   GET  /ledconfig   the whole configuration plus the lists the page needs (messages, groups, effects, wire orders)
#   POST /ledconfig   save it (and the LED count / output pin, which are not part of led.json)
#   POST /wbtest, /wbtestdone   hold the LED at solid white while the white balance is adjusted
# api() gives the DreamPi dot on the main page the look of the LED message that is showing.
import json

import netswitch_core as core
import netswitch_ledconfig as ledconfig


def _get_config(h):
    h.send(json.dumps({"config": ledconfig.led_config(), "defaults": ledconfig.default_led_config(),
                       "states": ledconfig.LED_STATES, "groups": ledconfig.GROUPS,
                       "effects": ledconfig.EFFECTS, "orders": ledconfig.LED_ORDERS, "count": ledconfig.led_count(),
                       "gpio": ledconfig.led_gpio(), "gpios": ledconfig.GPIO_PINS,
                       "net_bound": ledconfig.NET_BOUND,
                       "net_led": {"dcnow": core.network_colour("dcnow")["led"], "dcnet": core.network_colour("dcnet")["led"]},
                       "installed": ledconfig.led_count() > 0}),
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
    return {"values": {"led_count": ledconfig.led_count(), "led_order": ledconfig.led_config()["order"], "led_gpio": ledconfig.led_gpio()},
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
    ledconfig.touch_wb_test()


def _post_wbtest_done(h):
    ledconfig.clear_wb_test()


GET = {"/ledconfig": _get_config, "/ledhardware": _get_hardware}
POST = {"/ledconfig": _post_config, "/ledhardware": _post_hardware, "/wbtest": _post_wbtest, "/wbtestdone": _post_wbtest_done}


def api(d, warnings):
    """The DreamPi dot previews the look of the LED message that is showing (the network switcher fills in the rest); the
    page hides the LED settings while the LED count is 0."""
    count = ledconfig.led_count()
    d["led"] = {"installed": count > 0, "count": count, "title": "Status LED" + (" (%d LEDs)" % count if count > 1 else "")}
    d.setdefault("dreampi", {})["look"] = (ledconfig.active_messages(core.dreampi_state()[0], {"network": True}, wifi=False) or [None])[-1]
