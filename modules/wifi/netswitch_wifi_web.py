# DreamPi Netswitch add-on - Wi-Fi setup module, web side. The setup itself (scanning, the temporary access
# point, connecting) runs in the module's own service (netswitch_wifi_service.py + netswitch_wifi_setup.py in this folder);
# this file is how the page starts and stops it and tells it which network to join:
#   POST /wifitoggle   start Wi-Fi setup, or stop it while it runs (touches wifi_start / wifi_stop)
#   POST /wificonnect  join a network chosen on this page (an alternative to the access point's own page)
#   GET/POST /wifibutton   which button (1, 2 or both held) starts it: the standard form answer {values, options}
# api() adds the Wi-Fi state to /api (with the texts the page's widgets show) and the warning boxes shown while setup is in progress.
import json
import os

import base_core as core


def _toggle(h):
    if core.wifi_state().get("state", "idle") == "idle":
        open(core.WIFI_START, "w").close()
        core.debug_log("web page: Wi-Fi setup started")
    else:
        open(core.WIFI_STOP, "w").close()
        core.debug_log("web page: Wi-Fi setup stop requested")


def _connect(h):
    """Lets this page pick a network too: reachable while it's up over Ethernet (or anything else besides
    the Wi-Fi being reconfigured)."""
    ssid = ""
    try:
        data = json.loads(h._body(4096).decode("utf-8"))
        ssid = str(data.get("ssid") or "").strip()[:32]      # an SSID is at most 32 bytes
        password = str(data.get("password") or "")[:63]      # a WPA passphrase at most 63
    except (ValueError, IOError, OSError, AttributeError):
        pass
    if ssid:
        tmp = core.WIFI_CONNECT + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"ssid": ssid, "password": password}, f)
        os.rename(tmp, core.WIFI_CONNECT)
        core.debug_log("web page: Wi-Fi connect requested for %s" % ssid)


def _wifi_button_reply():
    choice = core.wifi_button()
    return {"values": {"wifi_button": choice},
            "texts": {"wifi_button": "Hold button %s for 3 s to start Wi-Fi setup" % ("1 + 2" if choice == "12" else choice)},
            "options": {"choices": [{"value": c[0], "label": c[1]} for c in core.WIFI_BUTTON_CHOICES]}}


def _get_button(h):
    h.send(json.dumps(_wifi_button_reply()), "application/json")


def _post_button(h):
    try:
        core.save_wifi_button((json.loads(h._body(1024).decode("utf-8")).get("values") or {}).get("wifi_button"))
    except (ValueError, IOError, OSError, AttributeError) as e:
        return h.send(str(e), "text/plain; charset=utf-8", status=400)
    h.send(json.dumps(_wifi_button_reply()), "application/json")
    return True


PROTECTED = ("/wificonnect",)      # joins a network as root: the PIN is asked for when one is set
GET = {"/wifibutton": _get_button}
POST = {"/wifitoggle": _toggle, "/wificonnect": _connect, "/wifibutton": _post_button}

# the button label and the line under "Wi-Fi setup" for each state of the setup service
LABELS = {
    "idle": ("Search", "Search for a Wi-Fi network to connect the Pi to"),
    "scanning": ("Stop", "Scanning for Wi-Fi networks..."),
    "hosting": ("Stop", "Pick a network below, or connect to \u201cDreamPi WiFi Config\u201d and open http://192.168.4.1"),
    "connecting": ("Stop", "Connecting to \u201c%s\u201d..."),
    "ok": ("Connected", "Connected to \u201c%s\u201d"),
    "failed": ("Stop", "Couldn't connect (%s)")}


def strength(sig):
    if sig is None:
        return ""
    return "Strong" if sig >= -55 else "Good" if sig >= -65 else "Fair" if sig >= -75 else "Weak"


def networks_list(nets):
    """The scan results as the page's list shows them: ssid, secured, info ("Secured \u00b7 Strong")."""
    out = []
    for n in nets or []:
        out.append({"ssid": n.get("ssid", ""), "secured": bool(n.get("secured")), "signal": n.get("signal"),
                    "info": " \u00b7 ".join(x for x in ("Secured" if n.get("secured") else "Open", strength(n.get("signal"))) if x)})
    return out


def api(d, warnings):
    wf = core.wifi_state()
    state = wf.get("state", "idle")
    if state in ("scanning", "hosting"):
        warnings.append("Wi-Fi setup: connect a phone or PC to the “%s” Wi-Fi network, then open "
                        "http://192.168.4.1 to pick a network." % core.WIFI_AP_SSID)
    elif state == "connecting":
        warnings.append("Wi-Fi setup: trying to connect to “%s”..." % (wf.get("ssid") or ""))
    elif state == "failed":
        warnings.append("Wi-Fi setup: could not connect (%s)." % (wf.get("ssid") or "unknown reason"))
    demo = os.path.exists(core.WIFI_DEMO)
    button, text = LABELS.get(state, LABELS["idle"])
    sub = "Pick a network below" if demo and state == "hosting" else text.replace("%s", wf.get("ssid") or "")
    d["wifi"] = {"state": state, "ssid": wf.get("ssid"), "networks": wf.get("networks"), "installed": True, "demo": demo,
                 "button": button, "disabled": state == "ok",
                 "sub": sub + (" - DEMO: dummy networks, password \u201cdemo\u201d connects" if demo else ""),
                 "show_list": state in ("hosting", "scanning"), "list": networks_list(wf.get("networks"))}
