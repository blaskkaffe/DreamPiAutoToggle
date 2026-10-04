"""The LED engine: effects (on and blinking), hue-preserving output at every brightness, no randomness, and the
filter that stops a half-written state file from flashing on the LED."""
import unittest

from support import sandbox, cleanup
import netswitch_led as led

COLOURS = ["#ff8c00", "#0046ff", "#aa00ff", "#ff0000", "#00ff00", "#00c8ff", "#ffd000", "#ffffff"]


PULSE_SHARE = 0.09      # a flash is this share of the round (led.PULSE)


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

    def test_fast_is_faster_than_slow_for_every_effect(self):
        for name, (slow, fast) in led.PERIOD.items():
            self.assertLess(fast, slow, name)

    def test_an_unknown_effect_is_just_on(self):
        self.assertEqual(led.effect_level("disco", "slow", 0.7), 1.0)

    def pattern(self, effect, speed="slow", cells=20):
        period = led.PERIOD[effect][0 if speed == "slow" else 1]
        return "".join("o" if led.effect_level(effect, speed, (i + 0.5) * period / cells) > 0 else "-" for i in range(cells))

    def runs(self, effect, speed="slow", cells=400):
        """The lit stretches of one period as (start, end) shares of it."""
        period = led.PERIOD[effect][0 if speed == "slow" else 1]
        lit = [led.effect_level(effect, speed, (i + 0.5) * period / cells) > 0 for i in range(cells)]
        out, start = [], None
        for i, on in enumerate(lit + [False]):
            if on and start is None:
                start = i
            elif not on and start is not None:
                out.append((start / float(cells), i / float(cells)))
                start = None
        return out

    def test_one_two_and_three_short_flashes(self):
        for effect, n in (("blink1", 1), ("blink2", 2), ("blink3", 3)):
            for speed in ("slow", "fast"):
                runs = self.runs(effect, speed)
                self.assertEqual(len(runs), n, (effect, speed))                         # o---   oo---   ooo-  : n flashes ...
                self.assertEqual(runs[0][0], 0.0)                                       # ... the first one at once ...
                self.assertLess(runs[-1][1], 0.5)                                       # ... and then dark for the rest of the round
                self.assertTrue(all(abs((r[1] - r[0]) - PULSE_SHARE) < 0.01 for r in runs))

    def test_fade_goes_smoothly_from_on_to_off_and_back(self):
        period = led.PERIOD["fade"][0]
        levels = [led.effect_level("fade", "slow", period * i / 20.0) for i in range(21)]
        self.assertEqual((levels[0], round(levels[10], 6), round(levels[20], 6)), (1.0, 0.0, 1.0))      # starts lit, off at half time
        self.assertTrue(all(a >= b for a, b in zip(levels[:10], levels[1:11])))                       # and it is a ramp, not a jump

    def test_breathing_never_goes_fully_off(self):
        period = led.PERIOD["breathe"][0]
        levels = [led.effect_level("breathe", "slow", period * i / 40.0) for i in range(41)]
        self.assertEqual(max(levels), 1.0)
        self.assertAlmostEqual(min(levels), led.BREATHE_LOW)
        clocks = {}
        lit = [led.render([{"key": "b", "effect": "breathe", "speed": "slow", "color": "#ff8c00", "brightness": 0.01, "leds": None}],
                          10.0 + period * i / 40.0, 1, clocks)[0] for i in range(41)]
        self.assertNotIn((0, 0, 0), lit)                                           # even at 1 % the dimmest breath still glows

    def test_a_fade_may_reach_off(self):
        clocks = {}
        m = {"key": "f", "effect": "fade", "speed": "slow", "color": "#ff8c00", "brightness": 0.08, "leds": None}
        led.render([m], 10.0, 1, clocks)
        self.assertEqual(led.render([m], 10.0 + led.PERIOD["fade"][0] / 2.0, 1, clocks), [(0, 0, 0)])

    def test_rainbow_goes_round_the_colour_wheel_whatever_the_colour(self):
        period = led.PERIOD["rainbow"][0]
        got = [led.effect_colour("rainbow", "slow", period * i / 6.0, (0.0, 0.0, 1.0)) for i in range(6)]
        self.assertEqual([tuple(round(c) for c in g) for g in got], [(1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 1, 1), (0, 0, 1), (1, 0, 1)])
        self.assertEqual(led.effect_colour("solid", "slow", 3.0, (0.2, 0.4, 0.6)), (0.2, 0.4, 0.6))

    def test_every_effect_of_the_page_has_a_function_and_a_period(self):
        from netswitch_ledconfig import EFFECTS
        for name, _label, _speed in EFFECTS:
            self.assertIn(name, led.EFFECT_LEVEL)
            self.assertTrue(name == "solid" or name in led.PERIOD, name)

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

    def test_a_network_switch_shows_at_once(self):
        s = led.Steady()
        s.feed(self.msgs("a"), 0.0)
        self.assertEqual(s.feed(self.msgs("b"), 0.1), self.msgs("a"))                    # an ordinary change is held back for HOLD seconds ...
        self.assertEqual(s.feed(self.msgs("b"), 0.2, immediate=True), self.msgs("b"))    # ... a switch of the network the service saw itself is not
        self.assertEqual(s.feed(self.msgs("b"), 0.3), self.msgs("b"))

    def test_the_led_loop_looks_at_the_flag_every_frame_and_reads_at_once_when_it_changes(self):
        src = open(led.__file__.replace(".pyc", ".py")).read()
        self.assertIn("os.path.exists(core.FLAG)", src)
        self.assertIn("immediate=switched_net", src)

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
