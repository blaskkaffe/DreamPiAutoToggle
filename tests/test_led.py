"""LED colour pipeline, wire order encoding and message composing (no hardware)."""
import unittest

from support import ledconfig, sandbox, cleanup
import netswitch_led as led
import netswitch_led_drivers as drivers


class PipelineTests(unittest.TestCase):
    def test_full_on_is_unaffected_by_gamma(self):
        self.assertEqual(led.to_bytes([(1, 1, 1)], 1.0), [(255, 255, 255)])

    def test_mid_value_compressed_by_gamma(self):
        px = led.to_bytes([(0.5, 0.5, 0.5)], 1.0, gamma=2.2)[0]
        self.assertIn(px, [(55, 55, 55), (56, 56, 56)])      # 0.5 ** 2.2 * 255 = 55.5

    def test_black_stays_black_regardless_of_white_balance(self):
        self.assertEqual(led.to_bytes([(0, 0, 0)], 1.0, (0.2, 0.5, 1.0)), [(0, 0, 0)])

    def test_white_balance_scales_only_its_channel(self):
        px = led.to_bytes([(1, 1, 1)], 1.0, (1.0, 0.5, 1.0))[0]
        self.assertEqual(px, (255, 128, 255))

    def test_max_brightness_applied_last(self):
        px = led.to_bytes([(1, 1, 1)], 0.5, (1.0, 0.5, 1.0))[0]
        self.assertEqual(px, (128, 64, 128))

    def test_a_faint_colour_still_lights_the_lowest_step(self):
        self.assertEqual(led.to_bytes([(1, 0, 0)], 0.005)[0], (1, 0, 0))      # 0.005 * 255 = 1.3

    def test_too_faint_for_the_lowest_step_is_off(self):
        self.assertEqual(led.to_bytes([(1, 0, 0)], 0.001)[0], (0, 0, 0))

    def test_wb_helper(self):
        self.assertEqual(led._wb({"white_balance": {"r": 0.5}}), (0.5, 1.0, 1.0))
        self.assertEqual(led._wb(None), (1.0, 1.0, 1.0))


class EncodingTests(unittest.TestCase):
    def test_wire_orders(self):
        for name, order in drivers.ORDERS.items():
            data = drivers.encode_bytes([(1, 2, 3)], order)
            expect = b"".join(drivers._TABLE[(1, 2, 3)[i]] for i in order)
            self.assertEqual(data[:9], expect, name)

    def test_default_is_grb(self):
        self.assertEqual(drivers.DEFAULT_ORDER, drivers.ORDERS["GRB"])

    def test_bit_symbols(self):
        self.assertEqual(drivers._symbols(0), bytes([0b10010010, 0b01001001, 0b00100100]))
        self.assertEqual(drivers._symbols(255), bytes([0b11011011, 0b01101101, 0b10110110]))


class RenderTests(unittest.TestCase):
    def msg(self, key, colour, leds=None):
        return {"key": key, "effect": "solid", "speed": "slow", "color": colour,
                "brightness": 1.0, "leds": leds}

    def test_later_message_draws_over_earlier(self):
        frame = led.render([self.msg("a", "#ff0000"), self.msg("b", "#0000ff", [2, 3])], 0.0, 4)
        self.assertEqual(frame[0], (255, 0, 0))
        self.assertEqual(frame[1], (0, 0, 255))
        self.assertEqual(frame[3], (255, 0, 0))       # red still on LED 4

    def test_uncovered_leds_stay_dark(self):
        frame = led.render([self.msg("a", "#ff0000", [1, 1])], 0.0, 3)
        self.assertEqual(frame[1], (0, 0, 0))
        self.assertEqual(frame[2], (0, 0, 0))

    def test_section_beyond_strip_is_skipped(self):
        frame = led.render([self.msg("a", "#ff0000", [5, 6])], 0.0, 3)
        self.assertEqual(frame, [(0, 0, 0)] * 3)

    def test_clocks_forget_vanished_messages(self):
        clocks = {}
        led.render([self.msg("a", "#ff0000")], 5.0, 1, clocks)
        self.assertIn("a", clocks)
        led.render([], 6.0, 1, clocks)
        self.assertNotIn("a", clocks)


class SwitchOutputTests(unittest.TestCase):
    """Changing the LED count/pin on the page (including to 0 = off)."""
    class Fake(object):
        def __init__(self, count, gpio):
            self.count, self.gpio, self.closed, self.shown = count, gpio, False, []
        def show(self, frame):
            self.shown.append(frame)
        def close(self):
            self.closed = True

    def setUp(self):
        self._open = drivers.open_output
        self.opened = []
        def fake_open(count, gpio):
            o = self.Fake(count, gpio)
            self.opened.append(o)
            return o
        drivers.open_output = fake_open
        self._sleep, led.time.sleep = led.time.sleep, lambda s: None

    def tearDown(self):
        drivers.open_output = self._open
        led.time.sleep = self._sleep

    def test_unchanged_does_nothing(self):
        out = self.Fake(3, 18)
        self.assertEqual(led.switch_output(out, 3, 18, 3, 18), (out, 3, 18, False))
        self.assertEqual(self.opened, [])

    def test_count_change_opens_new_then_closes_old(self):
        old = self.Fake(3, 18)
        out, count, gpio, switched = led.switch_output(old, 3, 18, 10, 18)
        self.assertTrue(switched)
        self.assertEqual((out.count, count, gpio), (10, 10, 18))
        self.assertTrue(old.closed)
        self.assertEqual(old.shown[-1], [(0, 0, 0)] * 3)          # blanked before closing

    def test_zero_closes_and_leaves_no_output(self):
        old = self.Fake(3, 18)
        out, count, gpio, switched = led.switch_output(old, 3, 18, 0, 18)
        self.assertEqual((out, count, switched), (None, 0, True))
        self.assertTrue(old.closed)
        self.assertEqual(self.opened, [])

    def test_from_zero_opens(self):
        out, count, gpio, switched = led.switch_output(None, 0, 18, 2, 18)
        self.assertTrue(switched)
        self.assertEqual((out.count, count), (2, 2))

    def test_failed_open_keeps_the_old_output(self):
        def boom(count, gpio):
            raise IOError("no spi")
        drivers.open_output = boom
        old = self.Fake(3, 18)
        self.assertEqual(led.switch_output(old, 3, 18, 3, 10), (old, 3, 18, False))
        self.assertFalse(old.closed)


class ActiveMessageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()

    def tearDown(self):
        cleanup(self.tmp)

    def test_errors_outrank_information(self):
        msgs = ledconfig.active_messages("ok", {"network": False}, wifi=False)
        keys = [m["key"] for m in msgs]
        self.assertEqual(keys[-1], "no-network")        # last = drawn on top
        self.assertIn("ready-dcnow", keys)

    def test_disabled_message_is_left_out(self):
        cfg = ledconfig.led_config()
        cfg["messages"]["ready-dcnow"]["enabled"] = False
        ledconfig.save_led_config(cfg)
        keys = [m["key"] for m in ledconfig.active_messages("ok", {"network": True}, wifi=False)]
        self.assertNotIn("ready-dcnow", keys)

    def test_brightness_falls_back_to_max(self):
        m = ledconfig.active_messages("ok", {"network": True}, wifi=False)[0]
        self.assertEqual(m["brightness"], ledconfig.led_config()["max_brightness"])


if __name__ == "__main__":
    unittest.main()
