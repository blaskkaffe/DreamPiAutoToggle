# DreamPi Netswitch add-on - network switcher module, web side: the selected network, DreamPi's / the modem's / the internet's
# / the Pi's status for the network box, the two network buttons' POSTs, hang up and the plain-text /status.
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


GET = {"/status": _status}
POST = {"/dcnow": _select("dcnow"), "/dcnet": _select("dcnet"), "/hangup": _hangup}
