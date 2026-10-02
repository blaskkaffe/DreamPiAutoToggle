# DreamPi Netswitch add-on - LED module, web side: what the page's LED settings talk to. The settings themselves
# (led.json, the message list, priorities) are in netswitch_ledconfig.py, shared with the LED service.
#   GET  /ledconfig   the whole configuration plus the lists the page needs (messages, groups, effects, wire orders)
#   POST /ledconfig   save it (and the LED count / output pin, which are not part of led.json)
#   POST /ledhide     hide / show the LED settings on the page
#   POST /wbtest, /wbtestdone   hold the LED at solid white while the white balance is adjusted
# api() gives the DreamPi dot on the main page the look of the LED message that is showing.
import json
import os

import netswitch_core as core
import netswitch_ledconfig as ledconfig


def _get_config(h):
    h.send(json.dumps({"config": ledconfig.led_config(), "defaults": ledconfig.default_led_config(),
                       "states": ledconfig.LED_STATES, "groups": ledconfig.GROUPS,
                       "effects": ledconfig.EFFECTS, "orders": ledconfig.LED_ORDERS, "count": ledconfig.led_count(),
                       "gpio": ledconfig.led_gpio(), "gpios": ledconfig.GPIO_PINS,
                       "installed": ledconfig.led_count() > 0, "hidden": ledconfig.led_hidden()}),
           "application/json")


def _post_config(h):
    try:
        data = json.loads(h._body(65536).decode("utf-8"))
        cfg = ledconfig.save_led_config(data)
        if "count" in data:
            ledconfig.save_led_count(data["count"])
        if "gpio" in data:
            ledconfig.save_led_gpio(data["gpio"])
    except (ValueError, IOError, OSError) as e:
        h.send(str(e), "text/plain; charset=utf-8", status=400)
        return True
    h.send(json.dumps({"config": cfg, "count": ledconfig.led_count(), "gpio": ledconfig.led_gpio()}), "application/json")
    return True


def _post_hide(h):
    if os.path.exists(core.LED_HIDDEN):
        os.remove(core.LED_HIDDEN)
        core.debug_log("web page: LED settings shown again")
    else:
        open(core.LED_HIDDEN, "w").close()
        core.debug_log("web page: LED settings hidden")


def _post_wbtest(h):
    ledconfig.touch_wb_test()


def _post_wbtest_done(h):
    ledconfig.clear_wb_test()


GET = {"/ledconfig": _get_config}
POST = {"/ledconfig": _post_config, "/ledhide": _post_hide, "/wbtest": _post_wbtest, "/wbtestdone": _post_wbtest_done}


def api(d, warnings):
    d["dreampi"]["look"] = (ledconfig.active_messages(d["dreampi"]["state"], {"network": True}, wifi=False) or [None])[-1]
