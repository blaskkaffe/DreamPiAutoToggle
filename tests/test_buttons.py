"""Button debounce / Wi-Fi hold / short-press dispatch: plain functions over a
state list, driven with scripted levels and a fake clock (no GPIO)."""
import json
import threading
import unittest

from support import core, sandbox, cleanup
import netswitch_buttons as b


class Clock(object):
    def __init__(self):
        self.t = 1000.0
    def __call__(self):
        return self.t


class LoopTests(unittest.TestCase):
    """run_buttons() driven by scripted pin levels (True = open/idle, False = closed to GND)."""
    def setUp(self):
        self.tmp = sandbox(b)
        self.clock = Clock()
        self._time, self._sleep = b.time.time, b.time.sleep
        b.time.time = self.clock
        self.ticks = 0
        self.limit = 0
        self.stop = threading.Event()

        def sleep(secs):
            if secs == b.BUTTON_POLL:
                self.ticks += 1
                self.clock.t += secs
                if self.ticks >= self.limit:
                    self.stop.set()
        b.time.sleep = sleep

    def tearDown(self):
        b.time.time, b.time.sleep = self._time, self._sleep
        cleanup(self.tmp)

    def run_loop(self, script, function1, function2, wifi="1", ticks=400):
        """script: {pin: [(from_tick, level), ...]}"""
        self.limit = ticks
        def read(pin):
            level = True
            for t, lv in script.get(pin, []):
                if self.ticks >= t:
                    level = lv
            return level
        b.run_buttons(read, lambda: None, 17, 4, function1, function2, wifi, self.stop)

    def selected(self):
        import os
        return "dcnet" if os.path.exists(core.FLAG) else "dcnow"

    def test_switch_position_is_applied_at_start_and_follows_changes(self):
        self.run_loop({17: [(0, False), (100, True), (200, False)]}, "sw_dcnet", "off")
        # closed at start = on = DCNET; opened at tick 100 -> DCNow!; closed again at 200 -> DCNET
        self.assertEqual(self.selected(), "dcnet")

    def test_switch_open_at_start_selects_the_off_network(self):
        open(core.FLAG, "w").close()
        self.run_loop({17: [(0, True)]}, "sw_dcnet", "off", ticks=20)
        self.assertEqual(self.selected(), "dcnow")

    def test_switch_change_midway(self):
        self.run_loop({17: [(0, False), (100, True)]}, "sw_dcnet", "off", ticks=150)
        self.assertEqual(self.selected(), "dcnow")

    def test_switch_does_not_also_count_as_a_push_button(self):
        self.run_loop({17: [(0, True), (50, False), (100, True)]}, "sw_dcnow", "off", ticks=150)
        self.assertEqual(self.selected(), "dcnet")      # open at start = DCNET; closed = DCNow!; open again = DCNET

    def test_push_button_and_wifi_switch_together(self):
        import os
        core.save_module_enabled("wifi", True)
        # button 1 pushes (toggle), button 2 is an "on = Wi-Fi setup" switch that gets closed at tick 100
        self.run_loop({17: [(0, True), (30, False), (45, True)], 4: [(0, True), (100, False)]},
                      "toggle", "sw_wifi", ticks=200)
        self.assertEqual(self.selected(), "dcnet")      # the push toggled once
        self.assertTrue(os.path.exists(core.WIFI_START))

    def test_held_push_button_still_starts_wifi_next_to_a_switch(self):
        import os
        core.save_module_enabled("wifi", True)
        self.run_loop({17: [(0, True), (10, False)], 4: [(0, True)]}, "toggle", "sw_dcnet", wifi="1", ticks=500)
        self.assertTrue(os.path.exists(core.WIFI_START))

    def test_wifi_hold_on_a_switch_button_is_ignored(self):
        import os
        core.save_module_enabled("wifi", True)
        self.run_loop({17: [(0, True), (10, False)]}, "sw_dcnet", "off", wifi="1", ticks=500)
        self.assertFalse(os.path.exists(core.WIFI_START))

    def test_push_button_toggle_still_works(self):
        self.run_loop({17: [(0, True), (10, False), (40, True)]}, "toggle", "off", ticks=100)
        self.assertEqual(self.selected(), "dcnet")


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

    def test_pin_already_low_at_start_does_not_fire_on_release(self):
        st = b.new_button_state(False)               # read low before anything pressed it
        res = self.feed(st, [False] * 5 + [True] * 6)
        self.assertNotIn("released", res)
        self.assertTrue(st[0])                       # back to idle...
        res = self.feed(st, [False] * 5 + [True] * 5)
        self.assertEqual(res.count("released"), 1)   # ...and the next real press works

    def test_stuck_low_pin_never_fires_a_wifi_hold(self):
        s1, s2 = b.new_button_state(False), b.new_button_state()
        self.clock.t += 60
        self.assertFalse(b.check_wifi_hold(s1, s2, True, "1"))

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

    def test_network_switch_positions(self):
        import os
        b._SWITCH_FUNCTIONS["sw_dcnet"](True)             # on = DCNET
        self.assertTrue(os.path.exists(core.FLAG))
        b._SWITCH_FUNCTIONS["sw_dcnet"](False)            # off = DCNow!
        self.assertFalse(os.path.exists(core.FLAG))
        b._SWITCH_FUNCTIONS["sw_dcnow"](True)             # on = DCNow!
        self.assertFalse(os.path.exists(core.FLAG))
        b._SWITCH_FUNCTIONS["sw_dcnow"](False)            # off = DCNET
        self.assertTrue(os.path.exists(core.FLAG))
        b._SWITCH_FUNCTIONS["sw_dcnow"](False)            # same position again changes nothing
        self.assertTrue(os.path.exists(core.FLAG))

    def test_wifi_switch_needs_wifi_installed(self):
        import os
        b._SWITCH_FUNCTIONS["sw_wifi"](True)
        self.assertFalse(os.path.exists(core.WIFI_START))   # Wi-Fi setup not installed: nothing happens
        core.save_module_enabled("wifi", True)
        b._SWITCH_FUNCTIONS["sw_wifi"](True)
        self.assertTrue(os.path.exists(core.WIFI_START))

    def test_wifi_switch_start_stop_follow_the_position(self):
        import os
        core.save_module_enabled("wifi", True)
        def set_state(state):
            with open(core.WIFI_STATE, "w") as f:
                json.dump({"state": state, "time": self.clock.t}, f)
        core_time, core.time.time = core.time.time, self.clock
        try:
            set_state("hosting")                                  # already running: "on" again does nothing
            b._SWITCH_FUNCTIONS["sw_wifi"](True)
            self.assertFalse(os.path.exists(core.WIFI_START))
            b._SWITCH_FUNCTIONS["sw_wifi"](False)                 # off ends it
            self.assertTrue(os.path.exists(core.WIFI_STOP))
            os.remove(core.WIFI_STOP)
            set_state("idle")
            b._SWITCH_FUNCTIONS["sw_wifi"](False)                 # idle + off: nothing to stop
            self.assertFalse(os.path.exists(core.WIFI_STOP))
            b._SWITCH_FUNCTIONS["sw_wifi_off"](False)             # the opposite switch: open = Wi-Fi setup
            self.assertTrue(os.path.exists(core.WIFI_START))
        finally:
            core.time.time = core_time

    def test_wifi_hold_ignores_switch_buttons(self):
        e = b.effective_wifi_assignment
        self.assertEqual(e("1", "toggle", "sw_wifi"), "1")
        self.assertEqual(e("1", "sw_dcnet", "off"), "")
        self.assertEqual(e("2", "toggle", "sw_dcnet"), "")
        self.assertEqual(e("12", "toggle", "dcnet"), "12")
        self.assertEqual(e("12", "toggle", "sw_dcnet"), "")
        self.assertEqual(e("", "toggle", "off"), "")

    def test_every_function_is_known_to_the_service(self):
        for f in core.BUTTON_FUNCTIONS:
            self.assertTrue(f[0] in b._BUTTON_FUNCTIONS or f[0] in b._SWITCH_FUNCTIONS, f[0])

    def test_pull_constants_differ_per_register(self):
        import netswitch_gpio as g
        # classic GPPUD and the Pi 4 register encode up/down opposite ways round
        self.assertEqual(g.PI4_PULL_UP, g.GPPUD_PULL_DOWN)
        self.assertEqual(g.PI4_PULL_DOWN, g.GPPUD_PULL_UP)
        self.assertNotEqual(g.PI4_PULL_UP, g.PI4_PULL_DOWN)


if __name__ == "__main__":
    unittest.main()
