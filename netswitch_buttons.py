#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# DreamPi Netswitch add-on - the GPIO buttons (always installed) and, when
# install.sh --wifi was used, the trigger for Wi-Fi setup (netswitch_wifi_setup.py).
#
# Runs as root (service dreampi-netswitch-buttons). Watches up to two GPIO
# button pins (see netswitch_gpio.py), each independently configured from the
# page's Settings > GPIO with its own pin and short-press function (off,
# toggle the selected network, or select DCNow!/DCNET outright). Holding the
# button(s) assigned to Wi-Fi setup for 3 s starts or stops it. Pins and
# functions are re-read every HEARTBEAT seconds, so page changes apply
# without a restart.
import os
import signal
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netswitch_core as core  # noqa: E402  (paths, settings, debug_log())
import netswitch_wifi_setup as wifi  # noqa: E402  (Wi-Fi setup; only used when wifi_enabled())
from netswitch_gpio import peripheral_base, Block, GPIO_OFFSET, set_input_pullup, read_level  # noqa: E402

HOLD_SECONDS = 3.0        # button hold before Wi-Fi setup starts/stops
SHORT_PRESS_MIN = 0.03    # ignore a debounced press shorter than this
BUTTON_POLL = 0.01        # 10 ms raw sample rate
DEBOUNCE_SAMPLES = 3      # a level must read the same for this many samples running (30 ms) to count
HEARTBEAT = 2             # seconds between state-file rewrites (so it can't go stale while idle)


def toggle_network():
    """Short press: switch the selected network, the same flag file the web
    page's DCNow!/DCNET buttons and the special phone numbers use."""
    if os.path.exists(core.FLAG):
        os.remove(core.FLAG)
        net = "DCNow!"
    else:
        open(core.FLAG, "w").close()
        net = "DCNET"
    core.debug_log("button: short press, %s selected" % net)


def select_network(net):
    """Short press: select DCNow! or DCNET outright, unlike toggle_network()
    not relative to the current selection. Idempotent (does nothing, and
    logs nothing, if that network is already selected)."""
    exists = os.path.exists(core.FLAG)
    if net == "dcnet" and not exists:
        open(core.FLAG, "w").close()
        core.debug_log("button: short press, DCNET selected")
    elif net == "dcnow" and exists:
        os.remove(core.FLAG)
        core.debug_log("button: short press, DCNow! selected")


_BUTTON_FUNCTIONS = {"off": lambda: None, "toggle": toggle_network,
                     "dcnow": lambda: select_network("dcnow"), "dcnet": lambda: select_network("dcnet")}


def _start_wifi_toggle():
    if os.path.exists(core.WIFI_STATE) and core.wifi_state().get("state", "idle") != "idle":
        open(core.WIFI_STOP, "w").close()
    else:
        open(core.WIFI_START, "w").close()
    core.debug_log("button: hold, Wi-Fi setup toggled")


def new_button_state():
    """[stable, candidate, candidate_count, pressed_since, fired]. stable/
    candidate: True = released (idle high). fired: a long-press action (the
    Wi-Fi hold) already happened for the press in progress."""
    return [True, True, 0, None, False]


def debounce_poll(level, st):
    """Advances one button's debounce state (see new_button_state()) from a
    fresh raw level; mutates st in place. Returns "released" if a debounced
    release just happened after a press long enough to not be contact
    bounce (and it didn't already fire a long-press action), else None.

    A mechanical button's contacts flicker for a few ms around each press
    and release, not just one clean transition, so a raw level is only
    trusted once it reads the same for DEBOUNCE_SAMPLES samples in a row.
    Without this, a single physical press could be seen as several quick
    press/release pairs - at best two toggles cancelling out (looks like
    nothing happened), at worst the short/long-press timing landing right on
    a threshold and firing unpredictably ("works, but not reliably")."""
    if level == st[1]:
        st[2] += 1
    else:
        st[1], st[2] = level, 1
    if st[2] >= DEBOUNCE_SAMPLES and st[1] != st[0]:
        st[0] = st[1]
        if not st[0]:   # debounced press just started
            st[3], st[4] = time.time(), False
        else:            # debounced release just happened
            since, st[3] = st[3], None
            if since is not None and not st[4] and time.time() - since >= SHORT_PRESS_MIN:
                return "released"
    return None


def check_wifi_hold(st1, st2, two_buttons, wifi_assignment):
    """True once, the moment the button(s) assigned to Wi-Fi setup
    ("1", "2" or "12" = both together) have been held HOLD_SECONDS; marks
    the relevant state(s) "fired" so debounce_poll() won't also report a
    short-press release for this same hold, and so this doesn't fire again
    for the same press."""
    if wifi_assignment == "12" and two_buttons:
        if not st1[0] and not st2[0] and not st1[4] and not st2[4] \
                and st1[3] is not None and st2[3] is not None \
                and time.time() - max(st1[3], st2[3]) >= HOLD_SECONDS:
            st1[4] = st2[4] = True
            return True
        return False
    watched = st1 if wifi_assignment == "1" else (st2 if two_buttons and wifi_assignment == "2" else None)
    if watched is not None and not watched[0] and not watched[4] and watched[3] is not None \
            and time.time() - watched[3] >= HOLD_SECONDS:
        watched[4] = True
        return True
    return False


def button_watcher(gpio1, gpio2, function1, function2, wifi_assignment, stop_event):
    """Watches one or two GPIO pins (internal pull-up; pressed = pulled to
    GND) in a single thread/register mapping. Each pin has its own
    short-press function (off / toggle the network / select DCNow! / select
    DCNET, from Settings > GPIO); wifi_assignment ("1", "2" or "12") says
    which pin, or whether both held together, must be held HOLD_SECONDS to
    touch wifi_start/wifi_stop, exactly like the web page's Wi-Fi setup
    button. A press that triggers the Wi-Fi hold never also fires its
    button's own short-press function once released. The debounce and
    hold/release decisions themselves are in debounce_poll()/
    check_wifi_hold(), which are plain functions so they can be tested
    without real GPIO hardware.

    Runs until stop_event is set, so main() can restart it with new pins or
    functions (picked up from the page within one HEARTBEAT) without
    restarting the whole service."""
    fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
    try:
        base = peripheral_base()
        gpio_block = Block(fd, base + GPIO_OFFSET)
    finally:
        os.close(fd)   # the mapping stays valid
    two_buttons = gpio2 != gpio1
    set_input_pullup(gpio_block, gpio1, base)
    if two_buttons:
        set_input_pullup(gpio_block, gpio2, base)

    fn1 = _BUTTON_FUNCTIONS.get(function1, _BUTTON_FUNCTIONS["off"])
    fn2 = _BUTTON_FUNCTIONS.get(function2, _BUTTON_FUNCTIONS["off"])
    st1, st2 = new_button_state(), new_button_state()

    while not stop_event.is_set():
        r1 = debounce_poll(read_level(gpio_block, gpio1), st1)
        r2 = debounce_poll(read_level(gpio_block, gpio2), st2) if two_buttons else None

        if check_wifi_hold(st1, st2, two_buttons, wifi_assignment):
            _start_wifi_toggle()

        if r1 == "released":
            fn1()
        if two_buttons and r2 == "released":
            fn2()
        time.sleep(BUTTON_POLL)


def wifi_enabled():
    """Wi-Fi setup was installed (install.sh --wifi); without it the buttons
    only run their own short-press functions."""
    return os.path.exists(core.WIFI_ENABLED)


def _button_config():
    # "" = no button starts Wi-Fi setup (check_wifi_hold() matches none)
    return (core.button_gpio(1), core.button_gpio(2), core.button_function(1), core.button_function(2),
            core.wifi_button() if wifi_enabled() else "")


def main():
    signal.signal(signal.SIGTERM, wifi.graceful_exit)   # a stop mid-setup must not strand the Wi-Fi interface
    signal.signal(signal.SIGINT, wifi.graceful_exit)
    cfg = _button_config()
    stop_event = threading.Event()
    thread = threading.Thread(target=button_watcher, args=cfg + (stop_event,))
    thread.daemon = True
    thread.start()

    while True:
        new_cfg = _button_config()
        if new_cfg != cfg:
            stop_event.set()
            thread.join(timeout=2)
            cfg = new_cfg
            stop_event = threading.Event()
            thread = threading.Thread(target=button_watcher, args=cfg + (stop_event,))
            thread.daemon = True
            thread.start()
            core.debug_log("button: config changed, button1=GPIO%d (%s), button2=GPIO%d (%s), wifi setup=%s"
                          % cfg)

        if not wifi_enabled():
            time.sleep(HEARTBEAT)
            continue
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
        time.sleep(HEARTBEAT)


if __name__ == "__main__":
    main()
