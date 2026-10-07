# DreamPi Netswitch add-on - system module, web side: GET /about, the name / value rows under Settings > System.
import json

import netswitch_probes as probes
import base_security as security


def _about(h):
    rows = probes.about()
    rows.append(("PIN", "Asked before update, restart and Wi-Fi connect" if security.pin_required()
                 else "Off: anyone on your network can update or restart (install.sh --pin sets one)"))
    h.send(json.dumps(rows), "application/json")


GET = {"/about": _about}
