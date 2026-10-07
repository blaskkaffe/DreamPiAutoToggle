#!/usr/bin/env python3
# DreamPi Netswitch add-on - status on NeoPixels (WS2812), GPIO18 by default.
# The pixel output drivers (PWM FIFO, PWM/PCM + DMA, SPI) are in
# netswitch_led_drivers.py; this file decides what to show and when.
#
# What it shows comes from the page's settings (led.json, see netswitch_ledconfig):
# colour groups (each a colour, an effect, a speed, a brightness and an LED section, with the
# messages that light it, see the modules' module.json "led_messages"). Several groups can show at once on different
# LEDs; the top group wins where they overlap, "State unknown" is only a fallback,
# see netswitch_ledconfig.active_messages().
# The number of LEDs is in /opt/dreampi-netswitch/led_count (install.sh).
import colorsys
import math
import os
import signal
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                                            # this module's other files
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))          # the add-on's base files (base_core ...)
import base_core as core  # noqa: E402  (module on/off)
import netswitch_ledconfig as ledconfig  # noqa: E402  (led.json, messages: shared with the web service)
import netswitch_led_drivers as drivers  # noqa: E402  (open_output(), wire orders)
import netswitch_led_spi as spi  # noqa: E402  (SPI on/off in config.txt for GPIO10)

FPS = 25           # looks at the clock this often: a blink never needs more, and the CPU belongs to DreamPi
REFRESH = 0.25     # seconds between re-reading DreamPi's state and led.json
QUICK_REFRESH = 0.05    # ... and while a state file has just been written (below)
QUICK_WINDOW = 0.6      # for this long after a state file changed
QUICK_HOLD = 0.12       # a changed list must stay the same this long before it shows (Steady.HOLD otherwise)
KEEPALIVE = 0.5    # an unchanged frame is sent again this often, which repairs a garbled one
BURST = 6          # a changed frame is sent this many times in a row (one per loop, 40 ms apart): a frame that did not take (not latched,
                   # garbled by a pre-emption) is replaced within a frame instead of staying until the next keep-alive


# ---------------------------------------------------------------- effects
# An effect says, for a message, how lit its LEDs are t seconds after the message started (or last changed): a level 0..1
# (1 = on, 0 = off, in between = a fade). Brightness is applied afterwards, in one place (to_bytes), so no effect can change a
# colour's hue. Only the rainbow also decides the colour (effect_colour). To add an effect, give it a name in ledconfig.EFFECTS,
# a period in PERIOD and a function here; the page's CSS (page.css, "lk" rules) needs a matching animation for the preview.
# Every effect starts at its brightest, so a change shows straight away.
PERIOD = {                       # seconds for one round: (slow, fast)
    "blink": (1.0, 0.4),         # lit for the first half, dark for the second
    "fade": (3.0, 1.2),          # smoothly up and down, all the way to off
    "breathe": (4.0, 1.6),       # smoothly up and down, never fully off
    "blink1": (1.6, 0.8),        # o---    one short flash, then dark
    "blink2": (1.6, 0.8),        # oo---   two
    "blink3": (1.6, 0.8),        # ooo-    three
    "rainbow": (6.0, 2.0),       # round the colour wheel
}
BREATHE_LOW = 0.12               # the dimmest a breath gets (as a level, before gamma); the LED is never turned fully off
NEVER_OFF = ("breathe",)
PULSE = 0.09                     # a flash and the gap after it, as a share of the period


def _period(effect, speed):
    slow, fast = PERIOD[effect]
    return fast if speed == "fast" else slow


def _solid(t, speed):
    return 1.0


def _blink(t, speed):
    period = _period("blink", speed)
    return 1.0 if (t % period) < period / 2.0 else 0.0     # starts lit when the message appears


def _wave(t, period):
    return (1.0 + math.cos(2 * math.pi * t / period)) / 2.0     # 1 at the start, 0 half a period later


def _fade(t, speed):
    return _wave(t, _period("fade", speed))


def _breathe(t, speed):
    return BREATHE_LOW + (1.0 - BREATHE_LOW) * _wave(t, _period("breathe", speed))


def _flashes(effect, n):
    def level(t, speed):
        period = _period(effect, speed)
        t = t % period
        unit = period * PULSE
        return 1.0 if t < n * 2 * unit - unit and (t % (2 * unit)) < unit else 0.0
    return level


def _rainbow(t, speed):
    return 1.0


EFFECT_LEVEL = {"solid": _solid, "blink": _blink, "fade": _fade, "breathe": _breathe,
                "blink1": _flashes("blink1", 1), "blink2": _flashes("blink2", 2), "blink3": _flashes("blink3", 3),
                "rainbow": _rainbow}


def effect_level(effect, speed, t):
    """0..1: how lit a message with this effect is t seconds after it started."""
    return EFFECT_LEVEL.get(effect, _solid)(t, speed)


def effect_colour(effect, speed, t, colour):
    """The colour (r, g, b floats 0..1) a message shows: its own, except for the rainbow, which goes round the colour wheel."""
    if effect == "rainbow":
        return colorsys.hsv_to_rgb((t / _period("rainbow", speed)) % 1.0, 1.0, 1.0)
    return colour


def hex_rgb(colour):
    return tuple(int(colour[i:i + 2], 16) / 255.0 for i in (1, 3, 5))


# ------------------------------------------------------------- calibration
# requested colour -> gamma correction -> white-balance multipliers -> brightness -> 8-bit LED values.
# Gamma (ledconfig.GAMMA, ~2.2) compensates for duty-cycle brightness not matching perceived brightness; white balance
# is a plain per-channel multiplier (0..1, 1 = none) found once by eye with the LED at solid white (see
# ledconfig.wb_test_active()); brightness (the global one or a message's own) is applied last, as a duty.
#
# The last step, quantize(), is what keeps a colour the same colour when it is dimmed. The LED only takes whole numbers
# 0..255 per channel; at low brightness the wanted values are tiny (an orange of 20 / 5 / 0 at 8 %, 2 / 0.5 / 0 at 1 %)
# and rounding each channel on its own, or forcing every lit channel up to at least 1, changes the mix: orange turned
# yellow or green, because the green channel (also the brightest to the eye) was rounded up to match the red one.
# quantize() rounds only the strongest channel and gives the others the same share of it that they were wanted at.
_quantized = {}


def quantize(x):
    """Wanted channel values (floats, 0..255) -> the 8-bit values to send. The strongest channel is rounded; the others
    keep their ratio to it (so a dimmed colour keeps its hue, and a smaller wanted value never gives a larger one).
    No dithering, so no flicker: the same input always gives the same output."""
    key = tuple(int(round(max(0.0, min(255.0, v)) * 4096)) for v in x)     # 1/4096 of a step: far below anything visible
    got = _quantized.get(key)
    if got is None:
        top = max(key)
        peak = int(round(top / 4096.0))                # the strongest channel, as the LED will show it
        if top == 0 or peak == 0:
            got = (0, 0, 0)                          # too faint to light even the lowest step
        else:
            got = tuple(min(255, int(round(peak * c / float(top)))) for c in key)
        if len(_quantized) > 4096:
            _quantized.clear()
        _quantized[key] = got
    return got


def to_bytes(frame, brightness, white_balance=None, gamma=ledconfig.GAMMA):
    """Floats 0..1 per LED -> 0..255 per channel through gamma -> white balance -> brightness -> quantize()."""
    wr, wg, wb = white_balance or (1.0, 1.0, 1.0)
    return [quantize(((r ** gamma) * wr * brightness * 255,
                      (g ** gamma) * wg * brightness * 255,
                      (b ** gamma) * wb * brightness * 255)) for (r, g, b) in frame]


def _wb(cfg):
    """led.json's white_balance dict -> (r, g, b) multipliers for to_bytes()."""
    wb = (cfg or {}).get("white_balance") or {}
    return (wb.get("r", 1.0), wb.get("g", 1.0), wb.get("b", 1.0))


# ---------------------------------------------------------------- composing
def render(messages, now, count, clocks=None, white_balance=None, gamma=ledconfig.GAMMA):
    """Draw the active messages (lowest priority first) into one frame of 8-bit LED values.
    Each message covers all LEDs or its own section; later (more important) messages draw over earlier ones,
    and uncovered LEDs stay dark. A blinking message in its dark half draws darkness over what is below it.
    A message's effect restarts (a blink starts lit) when it appears or its look changes, so a change shows straight
    away instead of landing somewhere in the middle of a cycle. clocks keeps those start times between frames."""
    if clocks is None:
        clocks = {}
    frame = [(0, 0, 0)] * count
    seen = set()
    for m in messages:
        key = m.get("key", "")
        seen.add(key)
        sig = (m.get("effect"), m.get("speed"), m.get("color"), m.get("leds"), m.get("brightness"))
        if key not in clocks or clocks[key][0] != sig:
            clocks[key] = (sig, now)
        leds = m.get("leds")
        first, last = (1, count) if not leds else (max(1, leds[0]), min(count, leds[1]))
        if first > last:
            continue          # section lies beyond the end of this strip
        effect, speed, age = m.get("effect", "solid"), m.get("speed", "slow"), now - clocks[key][1]
        level = effect_level(effect, speed, age)
        colour = effect_colour(effect, speed, age, hex_rgb(m.get("color", "#3c3c3c")))
        brightness = m.get("brightness", 0.08)
        pixel = to_bytes([tuple(c * level for c in colour)], brightness, white_balance, gamma)[0]
        if pixel == (0, 0, 0) and effect in NEVER_OFF and brightness > 0 and max(colour) > 0:
            pixel = quantize([c / max(colour) for c in colour])      # one step on the strongest channel: dim, not off
        frame[first - 1:last] = [pixel] * (last - first + 1)
    for key in list(clocks):
        if key not in seen:
            del clocks[key]   # starts over next time the message appears
    return frame


class Steady(object):
    """Lets a change of the message list through only when it has stayed the same for a moment. The state files the list
    comes from are written by other processes and a reading can catch one in between (DreamPi starting a call, the web
    service re-measuring the network); showing that for a moment is what looked like a flicker. Real changes show up
    about HOLD seconds later; the first list is used at once."""
    HOLD = 0.4

    def __init__(self):
        self.current, self.pending, self.since = None, None, 0.0

    def feed(self, messages, now, immediate=False, hold=None):
        """immediate: use this list now, without the wait (the selected network was just switched: a change the user made and
        the service saw itself in a file that is written in one go, which is no half-written reading). hold: the wait for this
        change instead of HOLD."""
        sig = repr(sorted((m["key"], m.get("effect"), m.get("speed"), m.get("color"), m.get("leds"), m.get("brightness"))
                          for m in messages))
        if immediate:
            self.current, self.pending = (sig, messages), sig
            return messages
        if self.current is None:
            self.current, self.pending = (sig, messages), sig
            return messages
        if sig == self.current[0]:
            self.pending = sig
            return self.current[1]
        if sig != self.pending:
            self.pending, self.since = sig, now
        elif now - self.since >= (self.HOLD if hold is None else hold):
            self.current = (sig, messages)
        return self.current[1]


# ---------------------------------------------------------------- main loop
_warned = set()
_spi_tried = {}      # on -> when it was last attempted: a pin the hardware can't use yet is retried every 0.25 s, the SPI setup not


def _spi(on, now=None):
    """GPIO10 needs SPI: switch it on in config.txt when that pin is chosen, off again when it is left (best effort)."""
    now = time.time() if now is None else now
    if now - _spi_tried.get(on, -1e9) < 30:
        return
    _spi_tried[on] = now
    try:
        text = spi.ensure_spi(on)
    except (IOError, OSError) as e:
        text = "SPI setting not changed (%s)" % e
    if text:
        sys.stderr.write(text + "\n")


def switch_output(out, count, gpio, new_count, new_gpio):
    """Reopen the hardware output when the LED count or pin was changed on the
    page. Returns (out, count, gpio, switched). out is None while the count is
    0 (LEDs off). The new output is opened before the old one is closed, and
    if it can't be opened the current output (and its count/pin) is kept."""
    if new_count == count and new_gpio == gpio:
        return out, count, gpio, False
    new_out = None
    if new_count > 0:
        try:
            if new_gpio == 10:
                _spi(True)
            new_out = drivers.open_output(new_count, new_gpio)
        except (IOError, OSError) as e:
            key = (new_gpio, new_count, str(e))
            if key not in _warned:        # the page is re-read four times a second: say it once
                _warned.add(key)
                sys.stderr.write("could not switch to GPIO%d, %d LED(s) (%s), keeping the "
                                 "current output\n" % (new_gpio, new_count, e))
            return out, count, gpio, False
    if out is not None:
        out.show([(0, 0, 0)] * count)
        time.sleep(0.02)
        out.close()
    if new_gpio != 10:
        _spi(False)       # SPI was only switched on for GPIO10
    return new_out, new_count, new_gpio, True


def _realtime():
    """Ask for a low real-time priority (best effort, the service runs as root): the LED data is sent by the CPU for a
    single LED, and being pre-empted in the middle of it is one way to get a wrong colour for a moment."""
    try:
        os.sched_setscheduler(0, os.SCHED_FIFO, os.sched_param(1))
    except (AttributeError, OSError, ValueError):
        pass


def wanted_count():
    """How many LEDs to drive: the configured count while the LED module is switched on in the Modules menu, else 0
    (the output is closed and dark, and the service just waits for it to be switched on)."""
    return ledconfig.led_count() if core.module_enabled("led") else 0


def _stamp(path):
    try:
        st = os.stat(path)
        return (st.st_mtime, st.st_size, st.st_ino)       # the inode: a file replaced by a rename is a new file
    except OSError:
        return None                                       # not there (the selected network's flag is only there for DCNET)


def watched_files():
    """What the files that settings and the network selection are kept in look like now (changes when one is written or removed)."""
    return tuple(_stamp(p) for p in (core.FLAG, core.LED_CONFIG, core.PALETTE_FILE, core.LED_COLOURS, core.PALETTE_CUSTOM, core.MODULE_COLOURS, core.LED_COUNT, core.LED_GPIO,
                                     core.MODULES_STATE, core.WB_TEST))


def watched_state_files():
    """What the files other programs write while they work (DreamPi's state, the network, Wi-Fi setup, updates, the reboot mark, the
    players, the reminders) look like now. They are written in one go (a rename), so a change shows in the stamp at once: the loop
    then reads quickly for a moment instead of waiting for the next REFRESH."""
    return tuple(_stamp(p) for p in (core.STATE, core.STATUS, core.NET_STATE, core.WIFI_STATE, core.UPDATE_STATUS, core.UPDATE_INFO,
                                     core.REBOOT_MARK, core.PLAYERS_WATCH, core.EVENT_REMINDERS))


def main(halt=None):
    """The service loop. halt: an object with is_set() (a threading.Event) that ends the loop, for the tests."""
    count, gpio = wanted_count(), ledconfig.led_gpio()
    cfg = ledconfig.led_config()
    order = drivers.ORDERS.get(cfg.get("order"), drivers.DEFAULT_ORDER)
    white_balance, gamma = _wb(cfg), cfg.get("gamma", ledconfig.GAMMA)
    out = None   # stays None while the LED count is 0 (the service just waits for it to change)
    if count > 0:
        try:
            if gpio == 10:
                _spi(True)
            out = drivers.open_output(count, gpio)
        except (IOError, OSError) as e:
            sys.exit("Cannot drive the LEDs on GPIO%d (%s). The LED service must run as root "
                     "(for GPIO10 the SPI setting may need a reboot to apply)." % (gpio, e))
        out.order = order

    def stop(*_):
        try:
            if out is not None:
                out.show([(0, 0, 0)] * count)
                time.sleep(0.02)
                out.close()
        finally:
            sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    _realtime()
    messages = []
    steady = Steady()
    wb_test, wb_colour = False, "#ffffff"
    clocks = {}
    last_frame, last_sent, burst = None, 0.0, 0
    changed_at, slow_said = None, -1e9      # when a file the LED follows changed and has not shown yet; when a slow loop was last reported
    next_read = 0.0
    stamp = watched_files()
    state_stamp, quick_until = watched_state_files(), 0.0
    while not (halt is not None and halt.is_set()):
        now = time.monotonic()           # not the wall clock: the Pi has no clock of its own and jumps when it finds the time on the network
        # A change the user makes shows at once: the files the page writes (the selected network, led.json, the palette, the colours of the
        # networks, the LED count and pin, the modules, the white-balance test) are looked at every frame, and when one has changed the state
        # is read now and the list is not held back. Those files are written in one go (a rename), so nothing is half-read; the wait in
        # Steady is for the state files other programs write while they work.
        now_stamp = watched_files()
        fresh = now_stamp != stamp
        if fresh:
            stamp, next_read = now_stamp, 0.0
            if changed_at is None:
                changed_at = now
        now_state = watched_state_files()
        if now_state != state_stamp:            # DreamPi, the network ... just wrote its state: look at once, and again soon
            state_stamp, next_read, quick_until = now_state, 0.0, now + QUICK_WINDOW
            if changed_at is None:
                changed_at = now
        quick = now < quick_until
        if now >= next_read:
            try:
                wb_test = ledconfig.wb_test_active()
                wb_colour = ledconfig.wb_test_colour()
                messages = steady.feed(ledconfig.active_messages(), now, immediate=fresh, hold=QUICK_HOLD if quick else None)
                cfg = ledconfig.led_config()
                order = drivers.ORDERS.get(cfg.get("order"), drivers.DEFAULT_ORDER)
                white_balance, gamma = _wb(cfg), cfg.get("gamma", ledconfig.GAMMA)
                out, count, gpio, switched = switch_output(out, count, gpio, wanted_count(), ledconfig.led_gpio())
                if switched:
                    clocks = {}
                    last_frame = None
                if out is not None:
                    out.order = order
            except Exception:   # never let a bad read stop the LED loop
                pass
            next_read = now + (QUICK_REFRESH if quick else REFRESH)
        if out is None:   # no LEDs configured
            time.sleep(REFRESH)
            continue
        # White-balance test open on the page: hold the strip at solid white,
        # run through the same gamma/white-balance/brightness pipeline as
        # everything else, so what's previewed is exactly what's being
        # calibrated - see ledconfig.wb_test_active().
        if wb_test:
            frame = to_bytes([hex_rgb(wb_colour)] * count, cfg.get("max_brightness", 0.08), white_balance, gamma)
        else:
            frame = render(messages, now, count, clocks, white_balance, gamma)
        # A frame is sent when it changed (and BURST times in a row, so one that did not take is replaced at once), and an unchanged one
        # every KEEPALIVE, which repairs a garbled frame. (Sending only on a change, with a keep-alive every 3 s, made a frame that did not
        # take stay on the LED for seconds.)
        if frame != last_frame:
            burst = BURST
            if changed_at is not None:      # for the debug log (Settings > Debug log > Recording): how long from the file to the LED
                core.debug_log("LED: a change was shown %d ms after a file changed" % int((time.monotonic() - changed_at) * 1000))
                changed_at = None
        elif changed_at is not None and now - changed_at > 1.0:
            changed_at = None               # a file changed that does not change what the LED shows
        if burst > 0 or now - last_sent >= KEEPALIVE:
            shown = time.monotonic()
            out.show(frame)
            last_frame, last_sent, burst = frame, now, max(0, burst - 1)
            if time.monotonic() - shown > 0.25 and shown - slow_said > 30:
                slow_said = shown
                sys.stderr.write("LED: sending a frame took %d ms (the output is slow)\n" % int((time.monotonic() - shown) * 1000))
        spent = time.monotonic() - now
        if spent > 0.3 and now - slow_said > 30:
            slow_said = now
            sys.stderr.write("LED: a round of the loop took %d ms (reading the state is slow)\n" % int(spent * 1000))
        time.sleep(max(0.0, 1.0 / FPS - (time.monotonic() - now)))


if __name__ == "__main__":
    main()
