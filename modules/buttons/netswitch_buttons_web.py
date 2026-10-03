# DreamPi Netswitch add-on - buttons module, web side: Settings > GPIO, the function and pin of the two buttons.
#   GET  /buttonconfig   {"values": {button1_function, button1_gpio, button2_function, button2_gpio},
#                         "options": {"functions": [{value, label, group, sub}], "gpios": [{value, label}]}}
#   POST /buttonconfig   {"values": {...}} saves what is valid and answers like the GET
# The buttons themselves are read by the always-running dreampi-netswitch-buttons service (netswitch_buttons.py), which
# only follows the files written here (netswitch_core.py).
import json

import netswitch_core as core


def _values():
    return {"button1_function": core.button_function(1), "button1_gpio": core.button_gpio(1),
            "button2_function": core.button_function(2), "button2_gpio": core.button_gpio(2)}


def _reply():
    values = _values()
    functions = []
    for name, label, group, needs_wifi, sub in core.BUTTON_FUNCTIONS:
        # the Wi-Fi switch functions only while the Wi-Fi module is on (or while one is already chosen)
        if needs_wifi and not core.wifi_enabled() and name not in (values["button1_function"], values["button2_function"]):
            continue
        functions.append({"value": name, "label": label, "group": group, "sub": sub})
    return {"values": values, "options": {"functions": functions,
                                          "gpios": [{"value": g, "label": "GPIO%d" % g} for g in core.BUTTON_GPIO_PINS]}}


def _get(h):
    h.send(json.dumps(_reply()), "application/json")


def _post(h):
    try:
        data = json.loads(h._body(4096).decode("utf-8")).get("values") or {}
    except (ValueError, IOError, OSError, AttributeError) as e:
        return h.send(str(e), "text/plain; charset=utf-8", status=400)
    try:
        g1, g2 = int(data["button1_gpio"]), int(data["button2_gpio"])
    except (KeyError, TypeError, ValueError):
        g1 = g2 = None
    if g1 is not None and g2 is not None and g1 != g2:   # reject if they'd collide on one pin
        core.save_button_gpio(1, g1)
        core.save_button_gpio(2, g2)
    if "button1_function" in data:
        core.save_button_function(1, data["button1_function"])
    if "button2_function" in data:
        core.save_button_function(2, data["button2_function"])
    h.send(json.dumps(_reply()), "application/json")
    return True


GET = {"/buttonconfig": _get}
POST = {"/buttonconfig": _post}
