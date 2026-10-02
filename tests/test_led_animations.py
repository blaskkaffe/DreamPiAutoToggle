"""What each LED effect really does over time (compared with the usual NeoPixel behaviour: Adafruit
strandtest's theater chase / rainbow, FastLED's Cylon scanner, WLED's scan / comet / breath)."""
import colorsys
import unittest

import netswitch_led as led

WHITE = "#ffffff"


def levels(effect, speed, n, t, colour=WHITE):
    """Brightness (as the eye judges it, before gamma) of every LED."""
    return [max(px) for px in led.effect_frame(effect, speed, colour, t, n)]


def hue_of(px):
    return colorsys.rgb_to_hsv(*px)[0]


class Common(unittest.TestCase):
    def head(self, effect, speed, n, t):
        lv = levels(effect, speed, n, t)
        return max(range(n), key=lambda i: lv[i])


class ScannerTests(Common):
    N = 24

    def at(self, phase):
        return levels("scanner", "slow", self.N, phase * led.PERIODS["scanner"][0])

    def test_head_sweeps_to_the_end_and_back(self):
        heads = [self.head("scanner", "slow", self.N, p / 40.0 * led.PERIODS["scanner"][0]) for p in range(41)]
        self.assertEqual(heads[0], 0)
        self.assertEqual(heads[20], self.N - 1)           # the middle of the cycle: at the far end
        self.assertEqual(heads[40], 0)
        self.assertEqual(heads[:21], sorted(heads[:21]))                 # forward ...
        self.assertEqual(heads[20:], sorted(heads[20:], reverse=True))   # ... and back

    def test_trail_follows_behind_the_head_and_nothing_is_ahead(self):
        lv = self.at(0.25)                                  # a quarter cycle: heading forward, in the middle
        head = max(range(self.N), key=lambda i: lv[i])
        self.assertAlmostEqual(lv[head], 1.0, delta=0.35)
        behind = [lv[i] for i in range(head - 1, max(-1, head - 6), -1)]
        self.assertGreater(behind[0], 0.3)                  # a visible trail ...
        self.assertEqual(behind, sorted(behind, reverse=True))   # ... fading with distance
        self.assertLess(lv[min(self.N - 1, head + 4)], 0.05)     # dark in front of the head
        lv = self.at(0.75)                                  # heading back: the trail is on the higher side
        head = max(range(self.N), key=lambda i: lv[i])
        self.assertGreater(lv[head + 1], 0.3)
        self.assertLess(lv[head - 4], 0.05)

    def test_trail_turns_round_at_the_end(self):
        lv = self.at(0.5)                                   # at the far end, just turning
        self.assertGreater(lv[self.N - 1], 0.9)
        self.assertGreater(lv[self.N - 3], 0.2)             # the trail it brought along is still there
        self.assertLess(lv[3], 0.01)

    def test_bigger_strips_get_a_bigger_head_and_tail(self):
        small = sum(1 for v in levels("scanner", "slow", 12, 0.75) if v > 0.05)
        big = sum(1 for v in levels("scanner", "slow", 120, 0.75) if v > 0.05)
        self.assertGreater(big, 3 * small)

    def test_tiny_strips(self):
        for n in (2, 3):
            for t in (0.0, 0.4, 0.75, 1.5, 2.9):
                lv = levels("scanner", "slow", n, t)
                self.assertEqual(len(lv), n)
                self.assertTrue(all(0 <= v <= 1 for v in lv))
                self.assertGreater(max(lv), 0.4)

    def test_fast_is_faster(self):
        slow, fast = led.PERIODS["scanner"]
        self.assertGreater(slow, fast)
        self.assertEqual(levels("scanner", "fast", 8, 0.0), levels("scanner", "fast", 8, fast))


class CometTests(Common):
    N = 24

    def test_head_moves_forward_and_wraps(self):
        period = led.PERIODS["comet"][0]
        heads = [self.head("comet", "slow", self.N, p / 48.0 * period) for p in range(96)]    # two rounds
        self.assertEqual(heads[0], 0)
        self.assertGreaterEqual(sum(1 for a, b in zip(heads, heads[1:]) if b > a), 40)
        self.assertEqual(sum(1 for a, b in zip(heads, heads[1:]) if b < a), 1)   # never backwards, one wrap round the strip
        self.assertEqual(levels("comet", "slow", self.N, 0.0), levels("comet", "slow", self.N, period))

    def test_tail_is_behind_and_fades(self):
        lv = levels("comet", "slow", self.N, led.PERIODS["comet"][0] * 0.5)      # head at LED 12
        self.assertGreater(lv[12], 0.9)
        tail = [lv[i] for i in range(12, 5, -1)]
        self.assertEqual(tail, sorted(tail, reverse=True))
        self.assertGreater(tail[1], 0.3)
        self.assertLess(lv[14], 0.01)                        # nothing ahead

    def test_front_edge_is_soft(self):
        """A pixel just ahead of the head is already lit a little, so the head glides instead of jumping."""
        period = led.PERIODS["comet"][0]
        steps = [levels("comet", "slow", self.N, period * (10.0 + k / 10.0) / self.N)[10] for k in range(11)]
        self.assertLess(max(abs(b - a) for a, b in zip(steps, steps[1:])), 0.5)


class ChaseTests(Common):
    def lit(self, n, t):
        return [i for i, px in enumerate(led.effect_frame("chase", "slow", WHITE, t, n)) if px != (0, 0, 0)]

    def test_every_third_led_and_it_steps_forward(self):
        period = led.PERIODS["chase"][0]
        seen = []
        for step in range(7):
            lit = self.lit(12, period / 3.0 * (step + 0.5))
            self.assertEqual(lit, list(range(step % 3, 12, 3)), step)
            seen.append(lit[0])
        self.assertEqual(seen, [0, 1, 2, 0, 1, 2, 0])      # one LED forward each step, a full cycle every 3 steps

    def test_single_led_just_blinks(self):
        self.assertEqual(led.effect_frame("chase", "slow", WHITE, 0.0, 1), [(1, 1, 1)])
        self.assertEqual(led.effect_frame("chase", "slow", WHITE, 0.4, 1), [(0, 0, 0)])


class RainbowTests(Common):
    def test_flows_the_same_way_as_the_other_moving_effects(self):
        n = 24
        period = led.PERIODS["rainbow"][1]
        def red_at(t):
            fr = led.effect_frame("rainbow", "fast", WHITE, t, n)
            return min(range(n), key=lambda i: min(hue_of(fr[i]), 1 - hue_of(fr[i])))
        pos = [red_at(period * k / 48.0) for k in range(1, 12)]
        self.assertEqual(pos, sorted(pos))                  # towards the last LED

    def test_one_full_wheel_over_the_strip_and_one_cycle_per_period(self):
        n = 30
        fr = led.effect_frame("rainbow", "slow", WHITE, 0.0, n)
        hues = [hue_of(px) for px in fr]
        self.assertEqual(len(set(round(h, 3) for h in hues)), n)
        self.assertAlmostEqual(abs(hues[-1] - hues[0]), (n - 1.0) / n, places=2)
        slow = led.PERIODS["rainbow"][0]
        a, b = led.effect_frame("rainbow", "slow", WHITE, 3.0, n), led.effect_frame("rainbow", "slow", WHITE, 3.0 + slow, n)
        for x, y in zip(a, b):
            for u, v in zip(x, y):
                self.assertAlmostEqual(u, v, places=6)

    def test_single_led_cycles_through_the_colours(self):
        hues = set(round(hue_of(led.effect_frame("rainbow", "fast", WHITE, k * 1.0, 1)[0]), 1) for k in range(10))
        self.assertGreaterEqual(len(hues), 8)


class BreatheBlinkRgbTests(Common):
    def test_breathe_is_a_smooth_wave(self):
        slow, fast = led.PERIODS["breathe"]
        f = lambda t, sp="slow": led.effect_frame("breathe", sp, WHITE, t, 1)[0][0]
        self.assertAlmostEqual(f(0.0), 1.0)                   # starts bright when the message appears
        self.assertAlmostEqual(f(slow / 2), 0.0, places=6)
        self.assertAlmostEqual(f(slow / 4), 0.5, places=6)    # as the eye sees it (gamma comes later), not squared
        self.assertAlmostEqual(f(slow), 1.0)
        self.assertAlmostEqual(f(fast / 2, "fast"), 0.0, places=6)
        vals = [f(slow * k / 100.0) for k in range(101)]
        self.assertLess(max(abs(b - a) for a, b in zip(vals, vals[1:])), 0.07)    # no jumps
        self.assertTrue(0.3 < sum(1 for v in vals if v > 0.5) / 101.0 < 0.7)      # about half the time visibly lit

    def test_all_leds_breathe_together(self):
        fr = led.effect_frame("breathe", "slow", "#ff8800", 1.0, 5)
        self.assertEqual(len(set(fr)), 1)

    def test_blink_is_half_on_half_off(self):
        slow, fast = led.PERIODS["blink"]
        for period, sp in ((slow, "slow"), (fast, "fast")):
            on = [led.effect_frame("blink", sp, WHITE, period * k / 100.0, 1)[0] != (0, 0, 0) for k in range(100)]
            self.assertEqual(sum(on), 50)
            self.assertTrue(on[0] and not on[99])           # starts lit

    def test_rgb_goes_round_all_colours(self):
        period = led.PERIODS["rgb"][1]
        hues = [hue_of(led.effect_frame("rgb", "fast", "#000000", period * k / 60.0, 3)[0]) for k in range(60)]
        self.assertGreaterEqual(len(set(round(h, 1) for h in hues)), 10)
        self.assertEqual(led.effect_frame("rgb", "fast", "#000000", 0, 3), led.effect_frame("rgb", "fast", "#000000", period, 3))


class TwinkleTests(Common):
    def test_random_but_steady_sparkle(self):
        n = 24
        counts, ever = [], set()
        for k in range(120):
            lv = levels("twinkle", "slow", n, k * 0.05)
            lit = [i for i, v in enumerate(lv) if v > 0.2]
            counts.append(len(lit))
            ever |= set(lit)
        self.assertEqual(len(ever), n)                       # every LED takes part ...
        self.assertTrue(all(c < n * 0.7 for c in counts))    # ... but never all at once
        self.assertGreater(sum(counts) / 120.0, 2)           # and there is always some sparkle
        self.assertEqual(levels("twinkle", "slow", n, 1.234), levels("twinkle", "slow", n, 1.234))


class StripEffectsOnOneLed(Common):
    def test_every_animation_has_a_single_led_fallback(self):
        for effect in ("scanner", "comet", "chase", "twinkle", "rainbow"):
            seen = set()
            for k in range(40):
                (px,) = led.effect_frame(effect, "slow", "#ff8800", k * 0.1, 1)
                self.assertTrue(all(0 <= c <= 1 for c in px))
                seen.add(tuple(round(c, 1) for c in px))
            self.assertGreater(len(seen), 1, effect)         # it does change over time


if __name__ == "__main__":
    unittest.main()
