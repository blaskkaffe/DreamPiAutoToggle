"""How fast the LED sees a change: the pokes between processes, the checker's state file and the LED loop's quick look."""
import json
import os
import time
import types
import unittest
from unittest import mock

from support import core, probes, sandbox, cleanup, ROOT
import netswitch_update as up  # noqa: E402
import sys
sys.path.insert(0, os.path.join(ROOT, "modules", "led"))
import netswitch_led as led  # noqa: E402
import netswitch_dreampi as hook  # noqa: E402
import builtins  # noqa: E402

builtins.__import__ = hook._original_import     # importing the hook may arm its import hook; undo that here

LINKS = {"ethernet": True, "wifi": False, "network": True}
PI = {"problem": False, "undervoltage": False, "throttled": 0, "temp": 45.0}


class PokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox(hook)

    def tearDown(self):
        cleanup(self.tmp)

    def test_a_poke_changes_the_stamp_every_time(self):
        self.assertIsNone(core.poke_stamp("internet"))
        core.poke("internet")
        first = core.poke_stamp("internet")
        self.assertIsNotNone(first)
        core.poke("internet")
        self.assertNotEqual(core.poke_stamp("internet"), first)               # a new file each time, even in the same clock tick
        self.assertIsNone(core.poke_stamp("players"))                         # one name does not poke another

    def test_the_hook_poke_is_the_same_file(self):
        hook._poked[0] = 0.0
        hook._poke_internet()
        self.assertIsNotNone(core.poke_stamp("internet"))
        first = core.poke_stamp("internet")
        hook._poke_internet()                                                 # at most every 5 seconds
        self.assertEqual(core.poke_stamp("internet"), first)

    def test_dreampi_saying_it_sees_no_internet_pokes(self):
        hook._poked[0] = 0.0
        record = types.SimpleNamespace(getMessage=lambda: "Unable to detect an internet connection. Waiting...")
        hook._ModemStatusHandler().emit(record)
        self.assertIsNotNone(core.poke_stamp("internet"))


class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        self.patches = [mock.patch.object(probes, "link_state", side_effect=lambda: dict(LINKS)),
                        mock.patch.object(probes, "pi_health", side_effect=lambda: dict(PI)),
                        mock.patch.object(probes, "modem_plugged", return_value=True),
                        mock.patch.object(probes, "wifi_level", return_value=None)]
        for p in self.patches:
            p.start()
        probes._net["links"] = None
        probes._net["internet"] = {"state": "ok", "text": "Connected", "time": 1}
        probes._net["recheck"].clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        cleanup(self.tmp)

    def written(self):
        with open(core.NET_STATE) as f:
            return json.load(f)

    def test_a_poke_makes_the_internet_check_run_now(self):
        seen = probes.new_checker_state()
        probes.checker_step(seen)
        probes._net["recheck"].clear()
        probes.checker_step(seen)
        self.assertFalse(probes._net["recheck"].is_set())                     # nothing to do
        core.poke("internet")
        probes.checker_step(seen)
        self.assertTrue(probes._net["recheck"].is_set())

    def test_a_change_is_written_at_once_and_an_unchanged_state_only_now_and_then(self):
        seen = probes.new_checker_state()
        probes.checker_step(seen, now=100.0)
        self.assertTrue(self.written()["modem"])
        stamp = os.stat(core.NET_STATE).st_ino
        probes.checker_step(seen, now=100.5)
        self.assertEqual(os.stat(core.NET_STATE).st_ino, stamp)               # unchanged: not rewritten every half second
        with mock.patch.object(probes, "modem_plugged", return_value=False):
            probes.checker_step(seen, now=101.0)
        self.assertFalse(self.written()["modem"])                             # the modem was unplugged: written in the same round
        probes.checker_step(seen, now=101.0 + probes.STATE_BEAT + 0.1)
        self.assertEqual(self.written()["time"], 101.0 + probes.STATE_BEAT + 0.1)    # a sign of life, so the file never looks stale

    def test_the_pi_health_is_measured_less_often_than_the_links(self):
        seen = probes.new_checker_state()
        probes.checker_step(seen, now=10.0)
        probes.checker_step(seen, now=10.5)
        probes.checker_step(seen, now=11.0)
        self.assertEqual(probes.pi_health.call_count, 1)
        probes.checker_step(seen, now=10.0 + probes.HEALTH_EVERY)
        self.assertEqual(probes.pi_health.call_count, 2)
        self.assertEqual(probes.link_state.call_count, 4)


class LedQuickLookTests(unittest.TestCase):
    def test_a_state_file_written_by_another_program_is_noticed(self):
        tmp = sandbox(led)
        try:
            a = led.watched_state_files()
            self.assertEqual(led.watched_state_files(), a)
            for name, path in (("DreamPi's state", core.STATE), ("the network", core.NET_STATE), ("Wi-Fi setup", core.WIFI_STATE),
                               ("the active mark", core.STATUS), ("the update", up.UPDATE_STATUS)):
                before = led.watched_state_files()
                with open(path, "w") as f:
                    f.write("x")
                self.assertNotEqual(led.watched_state_files(), before, name)
        finally:
            cleanup(tmp)

    def test_a_quick_change_needs_less_waiting_than_an_ordinary_one(self):
        def msgs(key):
            return [{"key": key, "effect": "solid", "speed": "slow", "color": "#ff0000", "brightness": 0.08, "leds": None}]
        s = led.Steady()
        s.feed(msgs("ready"), 0.0)
        s.feed(msgs("call"), 1.0, hold=led.QUICK_HOLD)
        self.assertEqual(s.feed(msgs("call"), 1.0 + led.QUICK_HOLD + 0.01, hold=led.QUICK_HOLD), msgs("call"))
        s.feed(msgs("ready"), 2.0)
        self.assertEqual(s.feed(msgs("ready"), 2.0 + led.QUICK_HOLD + 0.01), msgs("call"))     # no quick hold given: the ordinary wait still applies

    def test_the_loop_reads_quickly_for_a_moment_after_a_state_file_changed(self):
        with open(led.__file__.replace(".pyc", ".py")) as f:
            src = f.read()
        for text in ("watched_state_files()", "hold=QUICK_HOLD if quick else None", "QUICK_REFRESH if quick else REFRESH"):
            self.assertIn(text, src)
        self.assertLess(led.QUICK_HOLD, led.Steady.HOLD)
        self.assertLess(led.QUICK_REFRESH, led.REFRESH)


if __name__ == "__main__":
    unittest.main()
