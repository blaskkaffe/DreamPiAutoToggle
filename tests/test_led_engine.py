"""The LED engine: effects (on and blinking), hue-preserving output at every brightness, no randomness, and the
filter that stops a half-written state file from flashing on the LED."""
import unittest

from support import sandbox, cleanup
import netswitch_led as led

COLOURS = ["#ff8c00", "#0046ff", "#aa00ff", "#ff0000", "#00ff00", "#00c8ff", "#ffd000", "#ffffff"]


class EffectTests(unittest.TestCase):
    def test_solid_is_always_on(self):
        for t in (0, 0.3, 7.9):
            self.assertEqual(led.effect_level("solid", "slow", t), 1.0)

    def test_blink_is_half_on_half_off_and_starts_lit(self):
        for speed, period in (("slow", 1.0), ("fast", 0.4)):
            self.assertEqual(led.effect_level("blink", speed, 0.0), 1.0)
            self.assertEqual(led.effect_level("blink", speed, period * 0.49), 1.0)
            self.assertEqual(led.effect_level("blink", speed, period * 0.51), 0.0)
            self.assertEqual(led.effect_level("blink", speed, period * 0.99), 0.0)
            self.assertEqual(led.effect_level("blink", speed, period * 1.01), 1.0)         # and round again

    def test_fast_blinks_faster_than_slow(self):
        self.assertLess(led.BLINK_PERIOD["fast"], led.BLINK_PERIOD["slow"])

    def test_an_unknown_effect_is_just_on(self):
        self.assertEqual(led.effect_level("breathe", "slow", 0.7), 1.0)

    def test_render_blink_goes_dark_and_comes_back(self):
        m = {"key": "a", "effect": "blink", "speed": "slow", "color": "#ff0000", "brightness": 1.0, "leds": None}
        clocks = {}
        self.assertEqual(led.render([m], 10.0, 2, clocks), [(255, 0, 0)] * 2)       # appears lit
        self.assertEqual(led.render([m], 10.7, 2, clocks), [(0, 0, 0)] * 2)         # dark half
        self.assertEqual(led.render([m], 11.1, 2, clocks), [(255, 0, 0)] * 2)       # lit again
        m2 = dict(m, color="#0000ff")                                               # a change restarts it lit, never mid-cycle
        self.assertEqual(led.render([m2], 11.7, 2, clocks), [(0, 0, 255)] * 2)

    def test_a_message_in_its_dark_half_still_owns_its_leds(self):
        low = {"key": "low", "effect": "solid", "speed": "slow", "color": "#00ff00", "brightness": 1.0, "leds": None}
        top = {"key": "top", "effect": "blink", "speed": "slow", "color": "#ff0000", "brightness": 1.0, "leds": [1, 1]}
        clocks = {}
        led.render([low, top], 0.0, 2, clocks)
        frame = led.render([low, top], 0.7, 2, clocks)
        self.assertEqual(frame, [(0, 0, 0), (0, 255, 0)])


class DimmingTests(unittest.TestCase):
    def sweep(self, colour, wb=None):
        c = led.hex_rgb(colour)
        return [led.to_bytes([c], i / 1000.0, wb)[0] for i in range(1000, 0, -2)]     # 100 % down to 0.2 %

    def test_dimming_never_brightens_any_channel(self):
        for colour in COLOURS:
            prev = None
            for q in self.sweep(colour):
                if prev is not None:
                    self.assertTrue(all(q[k] <= prev[k] for k in range(3)), (colour, q, prev))
                prev = q

    def test_orange_stays_orange_and_never_turns_green(self):
        for q in self.sweep("#ff8c00"):
            self.assertEqual(q[2], 0, q)
            self.assertLessEqual(q[1], q[0], q)           # red always at least as strong as green
            if q[0] >= 8:
                self.assertAlmostEqual(q[1] / float(q[0]), 0.267, delta=0.07)          # the same orange all the way down

    def test_the_mix_of_every_colour_survives_dimming(self):
        for colour in COLOURS:
            c = led.hex_rgb(colour)
            full = led.to_bytes([c], 1.0)[0]
            for q in self.sweep(colour):
                peak = max(q)
                if peak < 8:
                    continue
                for k in range(3):
                    self.assertAlmostEqual(q[k] / float(peak), full[k] / float(max(full)), delta=0.1, msg=(colour, q))

    def test_a_dimmed_colour_keeps_its_strongest_channel(self):
        for colour in COLOURS:
            c = led.hex_rgb(colour)
            strongest = max(range(3), key=lambda k: c[k])
            for q in self.sweep(colour):
                if max(q):
                    self.assertEqual(q[strongest], max(q), (colour, q))

    def test_the_same_input_always_gives_the_same_output(self):
        c = led.hex_rgb("#ff8c00")
        first = led.to_bytes([c] * 3, 0.0123)
        for _ in range(500):
            self.assertEqual(led.to_bytes([c] * 3, 0.0123), first)       # no dither: nothing changes from frame to frame

    def test_white_balance_is_still_a_per_channel_multiplier(self):
        self.assertEqual(led.to_bytes([(1, 1, 1)], 1.0, (1.0, 0.5, 1.0))[0], (255, 128, 255))

    def test_nothing_is_ever_out_of_range(self):
        for colour in COLOURS:
            for q in self.sweep(colour, (1.0, 0.7, 0.4)):
                self.assertTrue(all(0 <= v <= 255 for v in q))


class SteadyTests(unittest.TestCase):
    def msgs(self, *keys):
        return [{"key": k, "effect": "solid", "speed": "slow", "color": "#ff0000", "brightness": 0.08, "leds": None} for k in keys]

    def test_the_first_list_is_used_at_once(self):
        s = led.Steady()
        self.assertEqual(s.feed(self.msgs("a"), 0.0), self.msgs("a"))

    def test_a_single_odd_reading_is_ignored(self):
        s = led.Steady()
        s.feed(self.msgs("ready"), 0.0)
        self.assertEqual(s.feed(self.msgs("unknown"), 0.25), self.msgs("ready"))     # a half-written state file, say
        self.assertEqual(s.feed(self.msgs("ready"), 0.5), self.msgs("ready"))
        self.assertEqual(s.feed(self.msgs("ready"), 5.0), self.msgs("ready"))

    def test_a_real_change_comes_through_after_a_moment(self):
        s = led.Steady()
        s.feed(self.msgs("ready"), 0.0)
        self.assertEqual(s.feed(self.msgs("call"), 1.0), self.msgs("ready"))         # seen once: wait
        self.assertEqual(s.feed(self.msgs("call"), 1.25), self.msgs("ready"))
        self.assertEqual(s.feed(self.msgs("call"), 1.0 + led.Steady.HOLD + 0.01), self.msgs("call"))

    def test_flapping_never_gets_through(self):
        s = led.Steady()
        s.feed(self.msgs("ready"), 0.0)
        for i in range(1, 12):
            got = s.feed(self.msgs("call" if i % 2 else "other"), i * 0.25)
            self.assertEqual(got, self.msgs("ready"))


class WhiteTestAndSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()

    def tearDown(self):
        cleanup(self.tmp)

    def test_the_main_loop_pieces_exist(self):
        self.assertTrue(callable(led.main) and callable(led._realtime) and callable(led.render))


if __name__ == "__main__":
    unittest.main()
