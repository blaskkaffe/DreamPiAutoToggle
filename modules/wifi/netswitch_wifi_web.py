# DreamPi Netswitch add-on - Wi-Fi setup module, web side. The setup itself (scanning, the temporary access
# point, connecting) runs in the module's own service (netswitch_wifi_service.py + netswitch_wifi_setup.py in this folder);
# this file is how the page starts and stops it and tells it which network to join:
#   POST /wifitoggle   start Wi-Fi setup, or stop it while it runs (touches wifi_start / wifi_stop)
#   POST /wificonnect  join a network chosen on this page (an alternative to the access point's own page)
# api() adds the Wi-Fi state to /api and the warning boxes shown while setup is in progress.
import json
import os

import netswitch_core as core


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


POST = {"/wifitoggle": _toggle, "/wificonnect": _connect}


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
    d["wifi"] = {"state": state, "ssid": wf.get("ssid"), "networks": wf.get("networks"),
                 "installed": True, "demo": os.path.exists(core.WIFI_DEMO)}
