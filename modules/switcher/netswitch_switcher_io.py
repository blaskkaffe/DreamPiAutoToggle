# DreamPi Netswitch add-on - network switcher module: what other modules can ask of it (inputs) and what it tells (outputs), see
# netswitch_bus.py. Python 2 and 3, only the base and files: the web page, the phone numbers (inside DreamPi) and anything else
# can run it, in any process.
import os

import netswitch_bus as bus
import netswitch_core as core

NETWORKS = (("dcnow", "DCNow!"), ("dcnet", "DCNET"))
NAMES = dict(NETWORKS)


def selected():
    """"dcnow" or "dcnet": the selected network (the dcnet_mode file exists = DCNET)."""
    return "dcnet" if os.path.exists(core.FLAG) else "dcnow"


def select_network(params, ctx):
    """Input "select_network" {"network": "dcnow" | "dcnet"}. Tells "switcher.network_selected" when it changed."""
    net = (params or {}).get("network")
    if net not in NAMES:
        raise ValueError("unknown network %r" % (net,))
    was = selected()
    if net == "dcnet":
        open(core.FLAG, "w").close()
    elif os.path.exists(core.FLAG):
        os.remove(core.FLAG)
    core.debug_log("%s: %s selected" % ((ctx or {}).get("source", "add-on"), NAMES[net]))
    if was != net:
        bus.emit("switcher.network_selected", {"network": net, "network_name": NAMES[net]}, ctx)
    return {"network": net, "changed": was != net}


def toggle_network(params, ctx):
    """Input "toggle_network": the other network."""
    return select_network({"network": "dcnow" if selected() == "dcnet" else "dcnet"}, ctx)


INPUTS = {"select_network": select_network, "toggle_network": toggle_network}
