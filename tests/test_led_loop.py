"""The LED service's loop against a fake output: how fast a change reaches the LED, and that a frame that did not take is replaced."""
import os
import signal
import threading
import time
import unittest

from support import core, ledconfig, sandbox, cleanup
import netswitch_led as led


class Out(object):
    order = None

    def __init__(self):
        self.shows = []

    def show(self, frame):
        self.shows.append((time.monotonic(), list(frame)))

    def close(self):
        pass


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        self.out = Out()
        self._open, self._signal, self._rt = led.drivers.open_output, signal.signal, led._realtime
        led.drivers.open_output = lambda count, gpio: self.out
        signal.signal = lambda *a, **k: None
        led._realtime = lambda: None
        with open(ledconfig.LED_COUNT, "w") as f:
            f.write("1")
        self.stop = threading.Event()
        self.thread = threading.Thread(target=led.main, args=(self.stop,))
        self.thread.daemon = True
        self.thread.start()
        time.sleep(0.6)

    def tearDown(self):
        self.stop.set()
        self.thread.join(5)
        led.drivers.open_output, signal.signal, led._realtime = self._open, self._signal, self._rt
        cleanup(self.tmp)

    def wait_for_change(self, base, limit=1.0):
        end = time.monotonic() + limit
        while time.monotonic() < end:
            if self.out.shows and self.out.shows[-1][1] != base:
                return True
            time.sleep(0.005)
        return False

    def test_a_selected_network_shows_within_a_fraction_of_a_second_and_is_sent_again_at_once(self):
        base = self.out.shows[-1][1]
        t0 = time.monotonic()
        open(core.FLAG, "w").close()                              # DCNET selected (the page's button, a phone number or a physical button)
        self.assertTrue(self.wait_for_change(base))
        self.assertLess(self.out.shows[-1][0] - t0, 0.3)
        time.sleep(0.3)
        same = [s for s in self.out.shows if s[0] >= t0 and s[1] == self.out.shows[-1][1]]
        self.assertGreaterEqual(len(same), 4)                     # the new colour went out several times in a row, 40 ms apart

    def test_an_unchanged_frame_is_still_sent_often_enough_to_repair_a_bad_one(self):
        time.sleep(1.3)
        times = [s[0] for s in self.out.shows if s[0] > time.monotonic() - 1.2]
        self.assertGreaterEqual(len(times), 2)
        self.assertLessEqual(max(b - a for a, b in zip(times, times[1:])), led.KEEPALIVE + 0.2)

    def test_a_colour_edit_shows_at_once(self):
        base = self.out.shows[-1][1]
        t0 = time.monotonic()
        cfg = ledconfig.led_config()
        cfg["groups"][-1]["colour"] = "green"                     # the row that is lit while DreamPi is ready
        ledconfig.save_led_config(cfg)
        self.assertTrue(self.wait_for_change(base))
        self.assertLess(self.out.shows[-1][0] - t0, 0.3)


if __name__ == "__main__":
    unittest.main()
