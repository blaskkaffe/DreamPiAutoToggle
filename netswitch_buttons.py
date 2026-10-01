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
PULLUP_SETTLE = 0.05         # seconds for the internal pull-up to take effect before the first read
PULLUP_RETRY = 1.0           # re-apply the pull-up this often while a pin sits low (a stuck-low pin never reports a release)


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


def _wifi_active():
    return os.path.exists(core.WIFI_STATE) and core.wifi_state().get("state", "idle") != "idle"


def _start_wifi_toggle():
    if _wifi_active():
        open(core.WIFI_STOP, "w").close()
    else:
        open(core.WIFI_START, "w").close()
    core.debug_log("button: hold, Wi-Fi setup toggled")


def _wifi_request(start):
    """A toggle switch asks for Wi-Fi setup to run (start) or end. Only acts
    when that changes something, so repeating the same position is harmless."""
    if not wifi_enabled():
        return
    active = _wifi_active()
    if start and not active:
        open(core.WIFI_START, "w").close()
        core.debug_log("button: switch, Wi-Fi setup started")
    elif not start and active:
        open(core.WIFI_STOP, "w").close()
        core.debug_log("button: switch, Wi-Fi setup stopped")


def _switch_network(on_net, closed):
    select_network(on_net if closed else ("dcnow" if on_net == "dcnet" else "dcnet"))


# Toggle switches: called with closed=True when the switch connects the pin to GND.
_SWITCH_FUNCTIONS = {"sw_dcnet": lambda closed: _switch_network("dcnet", closed),
                     "sw_dcnow": lambda closed: _switch_network("dcnow", closed),
                     "sw_wifi": lambda closed: _wifi_request(closed),
                     "sw_wifi_off": lambda closed: _wifi_request(not closed)}


def effective_wifi_assignment(assignment, function1, function2):
    """The Wi-Fi hold ("1", "2", "12") only works on push buttons: a button set
    to a toggle switch function can't be 'held'. "" = nothing can start it."""
    push1, push2 = function1 not in _SWITCH_FUNCTIONS, function2 not in _SWITCH_FUNCTIONS
    if (assignment == "1" and push1) or (assignment == "2" and push2) or (assignment == "12" and push1 and push2):
        return assignment
    return ""


def new_button_state(level=True):
    """[stable, candidate, candidate_count, pressed_since, fired]. stable/
    candidate: True = released (idle high). fired: a long-press action (the
    Wi-Fi hold) already happened for the press in progress. level seeds the
    state from the pin's real level at start: a pin that already reads low
    then counts as a press that began before we looked (no pressed_since,
    marked fired), so letting go of it never triggers a function."""
    if level:
        return [True, True, 0, None, False]
    return [False, False, 0, None, True]


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
    pins = [gpio1] + ([gpio2] if two_buttons else [])

    def apply_pullups():
        for pin in pins:
            set_input_pullup(gpio_block, pin, base)

    run_buttons(lambda pin: read_level(gpio_block, pin), apply_pullups,
                gpio1, gpio2, function1, function2, wifi_assignment, stop_event)


def run_buttons(read, apply_pullups, gpio1, gpio2, function1, function2, wifi_assignment, stop_event):
    """The button loop proper, on top of read(pin) -> level and
    apply_pullups(), so it can be driven by scripted levels in the tests."""
    two_buttons = gpio2 != gpio1
    pins = [gpio1] + ([gpio2] if two_buttons else [])
    apply_pullups()
    time.sleep(PULLUP_SETTLE)   # let the pull-up take effect before the first read
    levels = [read(pin) for pin in pins]
    core.debug_log("button: watching GPIO%s, idle level %s" % (
        "+".join(str(p) for p in pins), "/".join("high" if lv else "LOW" for lv in levels)))

    fn1 = _BUTTON_FUNCTIONS.get(function1, _BUTTON_FUNCTIONS["off"])
    fn2 = _BUTTON_FUNCTIONS.get(function2, _BUTTON_FUNCTIONS["off"])
    sw1, sw2 = _SWITCH_FUNCTIONS.get(function1), _SWITCH_FUNCTIONS.get(function2)
    if not two_buttons:
        function2, sw2 = "off", None
    wifi_assignment = effective_wifi_assignment(wifi_assignment, function1, function2)
    st1 = new_button_state(levels[0])
    st2 = new_button_state(levels[1] if two_buttons else True)
    last_pullup = time.time()

    # A toggle switch's position decides the state, so apply it once at start.
    for n, pin, sw, st in ((1, gpio1, sw1, st1), (2, gpio2, sw2, st2)):
        if sw:
            core.debug_log("button %d (GPIO%d): switch %s at start" % (n, pin, "closed" if not st[0] else "open"))
            sw(not st[0])

    while not stop_event.is_set():
        was1, was2 = st1[0], st2[0]
        r1 = debounce_poll(read(gpio1), st1)
        r2 = debounce_poll(read(gpio2), st2) if two_buttons else None

        if check_wifi_hold(st1, st2, two_buttons, wifi_assignment):
            _start_wifi_toggle()

        if sw1:
            if st1[0] != was1:
                core.debug_log("button 1 (GPIO%d): switch %s" % (gpio1, "closed" if not st1[0] else "open"))
                sw1(not st1[0])
        elif r1 == "released":
            core.debug_log("button 1 (GPIO%d): short press" % gpio1)
            fn1()
        if two_buttons:
            if sw2:
                if st2[0] != was2:
                    core.debug_log("button 2 (GPIO%d): switch %s" % (gpio2, "closed" if not st2[0] else "open"))
                    sw2(not st2[0])
            elif r2 == "released":
                core.debug_log("button 2 (GPIO%d): short press" % gpio2)
                fn2()
        # A push button that sits low with nothing pressing it (pull-up not in
        # effect) never reports a release; re-apply the pull-up now and then
        # so it heals. A closed toggle switch is legitimately low: skip those.
        now = time.time()
        stuck = (not st1[0] and not sw1) or (two_buttons and not st2[0] and not sw2)
        if stuck and now - last_pullup >= PULLUP_RETRY:
            apply_pullups()
            last_pullup = now
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
