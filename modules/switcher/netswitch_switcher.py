# DreamPi Netswitch add-on - network switcher module, web side: the selected network, DreamPi's / the modem's / the internet's
# / the Pi's status for the network box, the two network buttons' POSTs, hang up and the plain-text /status, and the module's
# GPIO settings: which function and pin the two physical network buttons have (GET/POST /buttonconfig, the standard form answer
# {values, options}; the always-running buttons service, netswitch_buttons.py, only follows the files written here).
# Everything it shows is in layout.json; the numbers and texts come from the /api answer built in api() below.
import json
import os
import time

import netswitch_core as core
import netswitch_probes as probes


def _dot_look(dstate):
    """What the DreamPi dot previews: a plain look for the state. The LED module replaces it with the look of the
    LED message that is showing (its api() hook), so the dot still says something without it."""
    dcnet = os.path.exists(core.FLAG)
    net = core.network_colour("dcnet" if dcnet else "dcnow")["led"]
    plain = {"ok": (net, "solid"), "busy": ("#ffd000", "blink"), "off": ("#ff0000", "blink"),
             "call-dcnow": (core.network_colour("dcnow")["led"], "solid"), "call-dcnet": (core.network_colour("dcnet")["led"], "solid"),
             "call": ("#aa00ff", "solid"), "unknown": ("#3c3c3c", "solid")}.get(dstate)
    return {"color": plain[0], "effect": plain[1], "speed": "slow"} if plain else None


def _ago(since, now):
    """"3 min ago" for a unix time (empty when there is none)."""
    if not since:
        return ""
    s = max(0, now - since)
    if s < 60:
        return "%ds ago" % s
    if s < 3600:
        return "%d min ago" % (s // 60)
    return "%d h ago" % (s // 3600)


def _selected():
    dcnet = os.path.exists(core.FLAG)
    return {"id": "dcnet" if dcnet else "dcnow", "title": "DCNET" if dcnet else "DCNow!"}


def api(d, warnings):
    dstate, dtext = core.dreampi_state()
    mtext, msince = core.modem_state()
    now = int(time.time())
    problem = core.hook_problem()
    if problem:
        warnings.append("Add-on not active: %s. Calls are not affected until it is." % problem)
    problem = core.dcnet_problem()
    if problem:
        warnings.append("DCNET unavailable: %s. All calls go to DCNow!" % problem)
    with probes._checks_lock:
        checks = json.loads(json.dumps(probes._checks))
    pi = checks.get("pi", {})
    if pi.get("undervoltage"):
        warnings.append("Power: the Pi is getting too little power (under-voltage). Use a stronger power "
                        "supply or a shorter, thicker cable; this can make the Pi unstable or drop off the network.")
    elif pi.get("problem"):
        warnings.append("Too hot: the Pi is at %.0f°C and slows itself down. Give it more air or a heatsink."
                        % (pi.get("temp") or 0))
    net = core.network_state()
    if net and not net.get("network"):
        warnings.append("No network: the Pi has no working network connection.")
    elif net and net.get("internet") is False:
        why = "name lookups (DNS) fail" if "DNS" in checks["internet"]["text"] \
            else "the network works, but the internet can't be reached"
        warnings.append("No internet: %s. Dreamcast games can't get online right now." % why)
    plugged = probes.modem_plugged()
    compat, label = probes.modem_compat(probes._usb_info(probes.modem_port()))
    if plugged is False:
        warnings.append("Modem not detected: its USB serial port is gone. Check the cable/connection.")
    elif compat is False:
        warnings.append("Modem: %s is known not to work reliably with DreamPi. "
                        "See the Modem row in Settings." % label)
    sel = _selected()
    dp = d.setdefault("dreampi", {})            # the LED module may have put the look of its message here already
    dp.update(state=dstate, text=dtext)
    if "look" not in dp:
        dp["look"] = _dot_look(dstate)
    busy = probes._hangup["busy"]
    pi_lines = [pi["line1"], pi.get("line2") or ""] + ([pi["warn"]] if pi.get("warn") else []) if pi.get("line1") else [pi.get("text") or "..."]
    d.update({"network": sel["id"], "selected": sel,
              "modem": {"text": mtext, "since": msince, "since_text": _ago(msince, now), "plugged": plugged, "label": label, "compat": compat},
              "internet": checks["internet"],
              "pi": {"state": pi.get("state"), "text": pi.get("text"), "line1": pi.get("line1"), "line2": pi.get("line2"),
                     "warn": pi.get("warn"), "lines": pi_lines},
              "hangup": {"busy": busy, "text": probes._hangup["text"] or "hanging up...",
                         "visible": dstate.startswith("call") or busy}})
    d.setdefault("primary", {})["switcher"] = core.network_colour(sel["id"])["id"]       # the box and its borders take the selected network's colour
    d.setdefault("primary_key", {})["switcher"] = sel["id"]                               # and the box follows that network's background setting


def _select(net):
    def handler(h):
        if net == "dcnet":
            open(core.FLAG, "w").close()
            core.debug_log("web page: DCNET selected")
        else:
            if os.path.exists(core.FLAG):
                os.remove(core.FLAG)
            core.debug_log("web page: DCNow! selected")
    return handler


def _hangup(h):
    probes.start_hangup()


def _status(h):
    import netswitch_web
    d = netswitch_web.api_state()
    h.send("network=%s\ntag=%s\ndreampi=%s\nmodem=%s\ninternet=%s\npi=%s\n" % (
        d["network"], core.tag(), d["dreampi"]["text"],
        d["modem"]["text"], d["internet"]["text"], d["pi"]["text"]), "text/plain; charset=utf-8")


def _values():
    return {"button1_function": core.button_function(1), "button1_gpio": core.button_gpio(1),
            "button2_function": core.button_function(2), "button2_gpio": core.button_gpio(2)}


def button_texts(values):
    """The line under each button's row: what its function does, with its pin ("GPIO17 toggles DCNow! and DCNET")."""
    texts = {}
    for n in (1, 2):
        template = [f[4] for f in core.BUTTON_FUNCTIONS if f[0] == values["button%d_function" % n]]
        texts["button%d" % n] = (template[0] if template else "{pin} is not used").replace("{pin}", "GPIO%d" % values["button%d_gpio" % n])
    return texts


def _reply():
    values = _values()
    functions = []
    for name, label, group, needs_wifi, sub in core.BUTTON_FUNCTIONS:
        # the Wi-Fi switch functions only while the Wi-Fi module is on (or while one is already chosen)
        if needs_wifi and not core.wifi_enabled() and name not in (values["button1_function"], values["button2_function"]):
            continue
        functions.append({"value": name, "label": label, "group": group})
    return {"values": values, "texts": button_texts(values),
            "options": {"functions": functions, "gpios": [{"value": g, "label": "GPIO%d" % g} for g in core.BUTTON_GPIO_PINS]}}


def _get_buttons(h):
    h.send(json.dumps(_reply()), "application/json")


def _post_buttons(h):
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


GET = {"/status": _status, "/buttonconfig": _get_buttons}
POST = {"/dcnow": _select("dcnow"), "/dcnet": _select("dcnet"), "/hangup": _hangup, "/buttonconfig": _post_buttons}
