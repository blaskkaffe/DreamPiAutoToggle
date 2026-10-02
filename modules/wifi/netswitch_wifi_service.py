#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# DreamPi Netswitch add-on - the Wi-Fi setup module's own service (dreampi-netswitch-wifi).
#
# Runs as root. Idle until something asks for Wi-Fi setup: the page's Settings > Network button (POST /wifitoggle)
# or a button hold (netswitch_buttons.py, in the base) just touch wifi_start / wifi_stop in /opt/dreampi-netswitch,
# and this service picks that up and runs netswitch_wifi_setup.setup_cycle(). So the buttons never load any Wi-Fi code;
# this module sits on top of them. While the module is switched off in Settings > Modules the service only idles
# (and stops a setup that is running), so it needs no restart when the module is toggled.
import os
import signal
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))     # the base folder, for netswitch_core
import netswitch_core as core  # noqa: E402
import netswitch_wifi_setup as wifi  # noqa: E402

HEARTBEAT = 2             # seconds between looks at the flag files (also keeps the state file from going stale)


def _module_off_watcher():
    """Switching the module off mid-setup counts as pressing stop (setup_cycle() watches for that)."""
    while True:
        time.sleep(1)
        if not core.wifi_enabled() and os.path.exists(core.WIFI_STATE) and core.wifi_state().get("state", "idle") != "idle":
            try:
                open(core.WIFI_STOP, "w").close()
            except OSError:
                pass


def run_once():
    """One look at the flag files; runs a whole setup session if one was asked for."""
    iface = wifi.wifi_iface()
    if wifi.start_requested():
        wifi.clear_flags()
        if not iface:
            core.debug_log("wifi setup: no Wi-Fi adapter found")
            wifi.set_state("failed", ssid="no Wi-Fi adapter found")
            wifi.wait_or_stop(wifi.RESULT_PAUSE)
            wifi.set_state("idle")
        else:
            try:
                wifi.setup_cycle(iface)
            except Exception:
                core.debug_log("wifi setup: unexpected error, stopping")
                sys.stderr.write("wifi setup failed:\n")
                import traceback
                traceback.print_exc()
                try:
                    wifi.restore_client(iface)
                except Exception:
                    pass
                wifi.set_state("idle")
                wifi.clear_flags()
    else:
        wifi.clear_flags()
        wifi.set_state("idle")


def main():
    signal.signal(signal.SIGTERM, wifi.graceful_exit)      # a stop mid-setup must not strand the Wi-Fi interface
    signal.signal(signal.SIGINT, wifi.graceful_exit)
    threading.Thread(target=_module_off_watcher, daemon=True).start()
    while True:
        if core.wifi_enabled():
            run_once()
        time.sleep(HEARTBEAT)


if __name__ == "__main__":
    main()
