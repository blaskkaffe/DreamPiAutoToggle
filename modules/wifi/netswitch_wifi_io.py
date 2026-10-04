# DreamPi Netswitch add-on - Wi-Fi setup module: its jacks, see netswitch_bus.py. Python 2 and 3, only the base and files (the Wi-Fi
# service watches these files), so any process can ask.
import netswitch_core as core


def start_setup(on, knobs, ctx):
    """Turning it on: the Pi hosts its own Wi-Fi network with the setup page."""
    if on:
        open(core.WIFI_START, "w").close()


def stop_setup(on, knobs, ctx):
    """Turning it on: stop hosting / cancel."""
    if on:
        open(core.WIFI_STOP, "w").close()


def toggle_setup(on, knobs, ctx):
    """Turning it on: start the setup, or stop it when it is running (a button that is held, say)."""
    if on:
        (stop_setup if core.wifi_state().get("state", "idle") != "idle" else start_setup)(True, knobs, ctx)


INPUTS = {"start_setup": start_setup, "stop_setup": stop_setup, "toggle_setup": toggle_setup}
OUTPUTS = {"setup_running": lambda: core.wifi_state().get("state", "idle") != "idle",
           "setup_connected": lambda: core.wifi_state().get("state") == "ok",
           "setup_failed": lambda: core.wifi_state().get("state") == "failed"}
