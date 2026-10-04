# DreamPi Netswitch add-on - Wi-Fi setup module: what other modules can ask of it (inputs), see netswitch_bus.py. Python 2 and 3,
# only the base and files (the Wi-Fi service watches these files), so any process can ask.
import netswitch_core as core


def start_setup(params, ctx):
    """Input "start_setup": the Pi hosts its own Wi-Fi network with the setup page."""
    open(core.WIFI_START, "w").close()
    return {"requested": "start"}


def stop_setup(params, ctx):
    """Input "stop_setup": stop hosting / cancel."""
    open(core.WIFI_STOP, "w").close()
    return {"requested": "stop"}


INPUTS = {"start_setup": start_setup, "stop_setup": stop_setup}
