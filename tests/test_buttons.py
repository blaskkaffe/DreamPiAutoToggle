"""Button debounce / Wi-Fi hold / short-press dispatch: plain functions over a
state list, driven with scripted levels and a fake clock (no GPIO)."""
import unittest

from support import core, sandbox, cleanup
import netswitch_buttons as b


class Clock(object):
    def __init__(self):
        self.t = 1000.0
    def __call__(self):
        return self.t


class ButtonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox(b)
        self.clock = Clock()
        self._time = b.time.time
        b.time.time = self.clock

    def tearDown(self):
        b.time.time = self._time
        cleanup(self.tmp)

    def feed(self, st, levels, step=0.01):
        out = []
        for lv in levels:
            self.clock.t += step
            out.append(b.debounce_poll(lv, st))
        return out

    def test_clean_press_release_is_one_short_press(self):
        st = b.new_button_state()
        res = self.feed(st, [True] * 5 + [False] * 10 + [True] * 5)
        self.assertEqual(res.count("released"), 1)

    def test_bounce_is_ignored(self):
        st = b.new_button_state()
        res = self.feed(st, [True, False, True, False, True, True, True, True])
        self.assertNotIn("released", res)
        self.assertTrue(st[0])           # never became "pressed"

    def test_too_short_press_is_ignored(self):
        st = b.new_button_state()
        res = self.feed(st, [False] * 3 + [True] * 5, step=0.001)   # < SHORT_PRESS_MIN
        self.assertNotIn("released", res)

    def test_hold_fires_once_and_suppresses_release(self):
        s1, s2 = b.new_button_state(), b.new_button_state()
        self.feed(s1, [False] * 5)
        self.clock.t += b.HOLD_SECONDS + 0.1
        self.assertTrue(b.check_wifi_hold(s1, s2, True, "1"))
        self.assertFalse(b.check_wifi_hold(s1, s2, True, "1"))     # only once
        res = self.feed(s1, [True] * 5)
        self.assertNotIn("released", res)

    def test_hold_assignment_two_and_both(self):
        s1, s2 = b.new_button_state(), b.new_button_state()
        self.feed(s1, [False] * 5)
        self.clock.t += b.HOLD_SECONDS + 0.1
        self.assertFalse(b.check_wifi_hold(s1, s2, True, "2"))     # button 2 not held
        self.assertFalse(b.check_wifi_hold(s1, s2, True, "12"))    # needs both
        self.feed(s2, [False] * 5)
        self.assertFalse(b.check_wifi_hold(s1, s2, True, "12"))    # 2 just pressed
        self.clock.t += b.HOLD_SECONDS + 0.1
        self.assertTrue(b.check_wifi_hold(s1, s2, True, "12"))
        self.assertTrue(s1[4] and s2[4])

    def test_empty_assignment_never_fires(self):
        s1, s2 = b.new_button_state(), b.new_button_state()
        self.feed(s1, [False] * 5)
        self.clock.t += 60
        self.assertFalse(b.check_wifi_hold(s1, s2, True, ""))

    def test_toggle_and_select(self):
        import os
        self.assertFalse(os.path.exists(core.FLAG))
        b.toggle_network()
        self.assertTrue(os.path.exists(core.FLAG))
        b.toggle_network()
        self.assertFalse(os.path.exists(core.FLAG))
        b.select_network("dcnet")
        b.select_network("dcnet")                     # idempotent
        self.assertTrue(os.path.exists(core.FLAG))
        b.select_network("dcnow")
        self.assertFalse(os.path.exists(core.FLAG))

    def test_pull_constants_differ_per_register(self):
        import netswitch_gpio as g
        # classic GPPUD and the Pi 4 register encode up/down opposite ways round
        self.assertEqual(g.PI4_PULL_UP, g.GPPUD_PULL_DOWN)
        self.assertEqual(g.PI4_PULL_DOWN, g.GPPUD_PULL_UP)
        self.assertNotEqual(g.PI4_PULL_UP, g.PI4_PULL_DOWN)


if __name__ == "__main__":
    unittest.main()
