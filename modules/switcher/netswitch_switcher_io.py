# DreamPi Netswitch add-on - network switcher module: its jacks, see netswitch_bus.py. Python 2 and 3, only the base and files: the web page,
# the phone numbers (inside DreamPi) and anything else can switch the network through it, in any process.
import os

import netswitch_bus as bus
import netswitch_core as core

NAMES = {"dcnow": "DCNow!", "dcnet": "DCNET"}


def selected():
    """"dcnow" or "dcnet": the selected network (the dcnet_mode file exists = DCNET)."""
    return "dcnet" if os.path.exists(core.FLAG) else "dcnow"


def select(net, ctx=None):
    """Select a network (the web page's two buttons call this too); the jacks that say which is selected follow."""
    if net not in NAMES:
        raise ValueError("unknown network %r" % (net,))
    if net == "dcnet":
        open(core.FLAG, "w").close()
    elif os.path.exists(core.FLAG):
        os.remove(core.FLAG)
    core.debug_log("%s: %s selected" % ((ctx or {}).get("source", "add-on"), NAMES[net]))
    bus.refresh("switcher.dcnow_selected", ctx)
    bus.refresh("switcher.dcnet_selected", ctx)


# ---- inputs: each acts when it turns on
def select_dcnow(on, knobs, ctx):
    if on:
        select("dcnow", ctx)


def select_dcnet(on, knobs, ctx):
    if on:
        select("dcnet", ctx)


def toggle_network(on, knobs, ctx):
    if on:
        select("dcnow" if selected() == "dcnet" else "dcnet", ctx)


INPUTS = {"select_dcnow": select_dcnow, "select_dcnet": select_dcnet, "toggle_network": toggle_network}


# ---- outputs: facts about the module and what it knows
def _net(key):
    return lambda: bool((core.network_state() or {}).get(key))


OUTPUTS = {"dcnow_selected": lambda: selected() == "dcnow", "dcnet_selected": lambda: selected() == "dcnet",
           "dreampi_ready": lambda: core.dreampi_state()[0] == "ok",
           "in_call": lambda: core.dreampi_state()[0].startswith("call"),
           "network_up": _net("network"), "internet_ok": lambda: (core.network_state() or {}).get("internet") is True,
           "modem_plugged": lambda: (core.network_state() or {}).get("modem") is True}
