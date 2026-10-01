#!/usr/bin/env python3
# DreamPi Netswitch add-on - status on NeoPixels (WS2812), GPIO18 by default.
# The pixel output drivers (PWM FIFO, PWM/PCM + DMA, SPI) are in
# netswitch_led_drivers.py; this file decides what to show and when.
#
# What it shows comes from the page's settings (led.json, see netswitch_ledconfig):
# per message (DreamPi status, network/internet errors, Ethernet/Wi-Fi) and
# selected network: on/off, colour, effect, speed, brightness and LED section.
# Errors outrank information; see netswitch_ledconfig.active_messages().
# The number of LEDs is in /opt/dreampi-netswitch/led_count (install.sh).
import colorsys
import math
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netswitch_ledconfig as ledconfig  # noqa: E402  (led.json, messages: shared with the web service)
import netswitch_led_drivers as drivers  # noqa: E402  (open_output(), wire orders)

FPS = 50
REFRESH = 0.25     # seconds between re-reading DreamPi's state and led.json


# ---------------------------------------------------------------- effects
# Each effect gives a list of (r, g, b) floats 0..1 per LED at time t.
# Periods in seconds for (slow, fast).
PERIODS = {
    "blink": (1.0, 0.4),
    "breathe": (4.0, 1.6),
    "rainbow": (20.0, 10.0),
    "scanner": (3.0, 1.2),
    "comet": (3.0, 1.2),
    "chase": (0.6, 0.24),      # time for one full 3-LED step cycle
    "twinkle": (3.0, 1.2),
    "rgb": (20.0, 10.0),       # fast = a standard, calm RGB cycle; slow = half that speed
}


def hex_rgb(colour):
    return tuple(int(colour[i:i + 2], 16) / 255.0 for i in (1, 3, 5))


def hue(h):
    return colorsys.hsv_to_rgb(h % 1.0, 1.0, 1.0)


def _mul(c, f):
    return (c[0] * f, c[1] * f, c[2] * f)


def _rand(i, salt):
    """Stable pseudo-random 0..1 per LED."""
    x = math.sin(i * 12.9898 + salt * 78.233) * 43758.5453
    return x - math.floor(x)


def effect_frame(effect, speed, colour, t, n):
    c = hex_rgb(colour)
    fast = speed == "fast"
    if effect == "solid":
        return [c] * n
    period = PERIODS.get(effect, (1.0, 0.4))[1 if fast else 0]
    phase = (t / period) % 1.0
    if effect == "rgb":
        return [hue(phase)] * n
    if effect == "blink":
        return [c if phase < 0.5 else (0, 0, 0)] * n
    if effect == "breathe":
        f = 0.5 + 0.5 * math.cos(2 * math.pi * phase)    # starts bright
        return [_mul(c, f * f)] * n
    if n == 1:   # strip effects on a single LED
        if effect == "rainbow":
            return [hue(phase)]
        if effect in ("chase", "twinkle"):
            return [c if phase < 0.5 else (0, 0, 0)]
        f = 0.5 + 0.5 * math.cos(2 * math.pi * phase)
        return [_mul(c, f * f)]
    if effect == "rainbow":
        return [hue(phase + float(i) / n) for i in range(n)]
    if effect == "scanner":
        pos = (n - 1) * (1 - abs(2 * phase - 1))            # back and forth
        return [_mul(c, max(0.0, 1 - abs(i - pos) / 1.5) ** 2) for i in range(n)]
    if effect == "comet":
        head = phase * n
        tail = max(2.0, n / 4.0)
        out = []
        for i in range(n):
            d = (head - i) % n
            out.append(_mul(c, max(0.0, 1 - d / tail) ** 2))
        return out
    if effect == "chase":
        step = int(phase * 3 + 1e-6) % 3     # 1e-6: no float rounding at the step edges
        return [c if (i - step) % 3 == 0 else (0, 0, 0) for i in range(n)]   # moves forward
    if effect == "twinkle":
        out = []
        for i in range(n):
            p = period * (0.6 + 0.8 * _rand(i, 1))
            s = math.sin(2 * math.pi * (t / p + _rand(i, 2)))
            out.append(_mul(c, max(0.0, s) ** 6))
        return out
    return [c] * n


_dither_err = {}   # (led index, channel) -> carried-over rounding error


# ------------------------------------------------------------- calibration
# A simple NeoPixel-style pipeline (see ledconfig.default_led_config(), which
# stores it): requested colour -> gamma correction -> white-balance
# multipliers -> max_brightness -> NeoPixel. Gamma (ledconfig.GAMMA, ~2.2)
# compensates for duty-cycle brightness not matching perceived brightness
# (dim values get dimmer, full-on is unchanged); white balance is a plain
# per-channel multiplier (0..1, 1 = no correction) found once by eye with
# the LED held at solid white (see ledconfig.wb_test_active()) and nudging down
# whichever channel looks too strong; max_brightness is the familiar
# global/per-message brightness level, applied last so it scales the
# already-corrected colour rather than the raw request.
def to_bytes(frame, brightness, white_balance=None, gamma=ledconfig.GAMMA, dither=True, start=0):
    """Floats 0..1 -> 0..255 through gamma -> white balance -> brightness.
    A channel that is on never rounds down to 0, so colours stay
    recognisable at low brightness. With dither, the rounding error is
    carried over to the next frame instead of discarded, so a value the
    8-bit output can't represent exactly (typical at low brightness, where
    slow effects like breathe would otherwise visibly step) is approximated
    by alternating the neighbouring levels over time instead. start is the
    absolute LED index of frame[0], so a section keeps its own dither state
    even though render() quantizes one message's section at a time."""
    wr, wg, wb = white_balance or (1.0, 1.0, 1.0)
    out = []
    for i, (r, g, b) in enumerate(frame):
        idx = start + i
        raw = ((r ** gamma) * wr * brightness * 255,
              (g ** gamma) * wg * brightness * 255,
              (b ** gamma) * wb * brightness * 255)
        px = []
        for c, x in enumerate(raw):
            x = max(0.0, min(255.0, x))
            if x <= 0:
                px.append(0)
                if dither:
                    _dither_err.pop((idx, c), None)
                continue
            if dither:
                key = (idx, c)
                x += _dither_err.get(key, 0.0)
                q = max(1, min(255, int(round(x))))
                _dither_err[key] = x - q
            else:
                q = max(1, min(255, int(round(x))))
            px.append(q)
        out.append(tuple(px))
    return out


def reset_dither():
    """Forget carried-over error, e.g. when the LED count changes."""
    _dither_err.clear()


def scaled(colour, brightness, white_balance=None, gamma=ledconfig.GAMMA):
    """'#rrggbb' at a brightness, for a single solid pixel."""
    return to_bytes([hex_rgb(colour)], brightness, white_balance, gamma, dither=False)[0]


def _wb(cfg):
    """led.json's white_balance dict -> (r, g, b) multipliers for to_bytes()."""
    wb = (cfg or {}).get("white_balance") or {}
    return (wb.get("r", 1.0), wb.get("g", 1.0), wb.get("b", 1.0))


# ---------------------------------------------------------------- composing
def render(messages, now, count, clocks=None, white_balance=None, gamma=ledconfig.GAMMA):
    """Draw the active messages (lowest priority first) into one frame.
    Each message covers all LEDs or its own section; later (more important)
    messages draw over earlier ones, and uncovered LEDs stay dark.
    Every message's effect restarts from its beginning (blink on, breathe
    bright) when the message appears or its look changes, so a change shows
    straight away instead of landing somewhere in the middle of a cycle.
    clocks keeps those start times between frames."""
    if clocks is None:
        clocks = {}
    frame = [(0, 0, 0)] * count
    seen = set()
    for m in messages:
        key = m.get("key", "")
        seen.add(key)
        sig = (m.get("effect"), m.get("speed"), m.get("color"), m.get("leds"))
        if key not in clocks or clocks[key][0] != sig:
            clocks[key] = (sig, now)
        leds = m.get("leds")
        first, last = (1, count) if not leds else (max(1, leds[0]), min(count, leds[1]))
        if first > last:
            continue          # section lies beyond the end of this strip
        n = last - first + 1
        part = to_bytes(effect_frame(m.get("effect", "solid"), m.get("speed", "slow"),
                                     m.get("color", "#3c3c3c"), now - clocks[key][1], n),
                        m.get("brightness", 0.08), white_balance, gamma, start=first - 1)
        frame[first - 1:last] = part
    for key in list(clocks):
        if key not in seen:
            del clocks[key]   # starts over next time the message appears
    return frame


# ---------------------------------------------------------------- main loop
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
            new_out = drivers.open_output(new_count, new_gpio)
        except (IOError, OSError) as e:
            sys.stderr.write("could not switch to GPIO%d, %d LED(s) (%s), keeping the "
                             "current output\n" % (new_gpio, new_count, e))
            return out, count, gpio, False
    if out is not None:
        out.show([(0, 0, 0)] * count)
        time.sleep(0.02)
        out.close()
    return new_out, new_count, new_gpio, True


def main():
    count, gpio = ledconfig.led_count(), ledconfig.led_gpio()
    cfg = ledconfig.led_config()
    order = drivers.ORDERS.get(cfg.get("order"), drivers.DEFAULT_ORDER)
    white_balance, gamma = _wb(cfg), cfg.get("gamma", ledconfig.GAMMA)
    out = None   # stays None while the LED count is 0 (the service just waits for it to change)
    if count > 0:
        try:
            out = drivers.open_output(count, gpio)
        except (IOError, OSError) as e:
            sys.exit("Cannot drive the LEDs on GPIO%d (%s). The LED service must run as root "
                     "(and, for GPIO10, SPI must be enabled)." % (gpio, e))
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

    messages = []
    wb_test = False
    clocks = {}
    last_frame, last_sent = None, 0.0
    next_read = 0.0
    while True:
        now = time.time()
        if now >= next_read:
            try:
                wb_test = ledconfig.wb_test_active()
                messages = ledconfig.active_messages()
                cfg = ledconfig.led_config()
                order = drivers.ORDERS.get(cfg.get("order"), drivers.DEFAULT_ORDER)
                white_balance, gamma = _wb(cfg), cfg.get("gamma", ledconfig.GAMMA)
                out, count, gpio, switched = switch_output(out, count, gpio, ledconfig.led_count(), ledconfig.led_gpio())
                if switched:
                    clocks = {}
                    last_frame = None
                    reset_dither()
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
            frame = to_bytes([(1.0, 1.0, 1.0)] * count, cfg.get("max_brightness", 0.08),
                             white_balance, gamma, dither=False)
        else:
            frame = render(messages, now, count, clocks, white_balance, gamma)
        # Unchanged frames (solid colours) are only resent twice a second,
        # which fixes any garbled frame and keeps the CPU free for DreamPi.
        if frame != last_frame or now - last_sent >= 0.5:
            out.show(frame)
            last_frame, last_sent = frame, now
        time.sleep(max(0.0, 1.0 / FPS - (time.time() - now)))


if __name__ == "__main__":
    main()
