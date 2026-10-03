#!/usr/bin/env python3
# DreamPi Netswitch add-on - status on NeoPixels (WS2812), GPIO18 by default.
# The pixel output drivers (PWM FIFO, PWM/PCM + DMA, SPI) are in
# netswitch_led_drivers.py; this file decides what to show and when.
#
# What it shows comes from the page's settings (led.json, see netswitch_ledconfig):
# per message (system, network and call messages, see LED_STATES): on/off, colour, effect,
# speed, brightness and LED section. Several messages can show at once on different LEDs;
# errors outrank information and "State unknown" is only a fallback, see
# netswitch_ledconfig.active_messages().
# The number of LEDs is in /opt/dreampi-netswitch/led_count (install.sh).
import math
import os
import signal
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                                            # this module's other files
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))          # the add-on's base files (netswitch_core ...)
import netswitch_core as core  # noqa: E402  (module on/off)
import netswitch_ledconfig as ledconfig  # noqa: E402  (led.json, messages: shared with the web service)
import netswitch_led_drivers as drivers  # noqa: E402  (open_output(), wire orders)
import netswitch_led_spi as spi  # noqa: E402  (SPI on/off in config.txt for GPIO10)

FPS = 25           # looks at the clock this often: a blink never needs more, and the CPU belongs to DreamPi
REFRESH = 0.25     # seconds between re-reading DreamPi's state and led.json
KEEPALIVE = 3.0    # an unchanged frame is sent again this often, which repairs a garbled one


# ---------------------------------------------------------------- effects
# An effect says, for a message, whether its LEDs are lit t seconds after the message started (or last changed).
# It does not touch colours: the colour is always the message's own, at full strength, and brightness is applied
# afterwards, in one place (to_bytes), so no effect can ever change a colour's hue. Only "solid" and "blink"
# exist for now. To add an effect, give it a name in ledconfig.EFFECTS and a function here that returns a
# brightness factor 0..1 (1 = on, 0 = off) for the time t; a factor between 0 and 1 is a fade.
BLINK_PERIOD = {"slow": 1.0, "fast": 0.4}     # seconds for one blink (lit for the first half, dark for the second)


def _solid(t, speed):
    return 1.0


def _blink(t, speed):
    period = BLINK_PERIOD.get(speed, BLINK_PERIOD["slow"])
    return 1.0 if (t % period) < period / 2.0 else 0.0     # starts lit when the message appears


EFFECT_LEVEL = {"solid": _solid, "blink": _blink}


def effect_level(effect, speed, t):
    """0..1: how lit a message with this effect is t seconds after it started."""
    return EFFECT_LEVEL.get(effect, _solid)(t, speed)


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
        level = effect_level(m.get("effect", "solid"), m.get("speed", "slow"), now - clocks[key][1])
        colour = hex_rgb(m.get("color", "#3c3c3c"))
        pixel = to_bytes([tuple(c * level for c in colour)], m.get("brightness", 0.08), white_balance, gamma)[0]
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

    def feed(self, messages, now):
        sig = repr(sorted((m["key"], m.get("effect"), m.get("speed"), m.get("color"), m.get("leds"), m.get("brightness"))
                          for m in messages))
        if self.current is None:
            self.current, self.pending = (sig, messages), sig
            return messages
        if sig == self.current[0]:
            self.pending = sig
            return self.current[1]
        if sig != self.pending:
            self.pending, self.since = sig, now
        elif now - self.since >= self.HOLD:
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


def main():
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
    wb_test = False
    clocks = {}
    last_frame, last_sent = None, 0.0
    next_read = 0.0
    while True:
        now = time.time()
        if now >= next_read:
            try:
                wb_test = ledconfig.wb_test_active()
                messages = steady.feed(ledconfig.active_messages(), now)
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
            next_read = now + REFRESH
        if out is None:   # no LEDs configured
            time.sleep(REFRESH)
            continue
        # White-balance test open on the page: hold the strip at solid white,
        # run through the same gamma/white-balance/brightness pipeline as
        # everything else, so what's previewed is exactly what's being
        # calibrated - see ledconfig.wb_test_active().
        if wb_test:
            frame = to_bytes([(1.0, 1.0, 1.0)] * count, cfg.get("max_brightness", 0.08), white_balance, gamma)
        else:
            frame = render(messages, now, count, clocks, white_balance, gamma)
        # A frame is sent when it changed, and an unchanged one now and then (KEEPALIVE), which repairs a garbled frame.
        if frame != last_frame or now - last_sent >= KEEPALIVE:
            out.show(frame)
            last_frame, last_sent = frame, now
        time.sleep(max(0.0, 1.0 / FPS - (time.time() - now)))


if __name__ == "__main__":
    main()
