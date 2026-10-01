"""LED colour pipeline, wire order encoding and message composing (no hardware)."""
import unittest

from support import web, sandbox, cleanup
import netswitch_led as led


class PipelineTests(unittest.TestCase):
    def setUp(self):
        led.reset_dither()

    def test_full_on_is_unaffected_by_gamma(self):
        self.assertEqual(led.to_bytes([(1, 1, 1)], 1.0, dither=False), [(255, 255, 255)])

    def test_mid_value_compressed_by_gamma(self):
        px = led.to_bytes([(0.5, 0.5, 0.5)], 1.0, gamma=2.2, dither=False)[0]
        self.assertEqual(px, (55, 55, 55))            # 0.5 ** 2.2 * 255

    def test_black_stays_black_regardless_of_white_balance(self):
        self.assertEqual(led.to_bytes([(0, 0, 0)], 1.0, (0.2, 0.5, 1.0), dither=False), [(0, 0, 0)])

    def test_white_balance_scales_only_its_channel(self):
        px = led.to_bytes([(1, 1, 1)], 1.0, (1.0, 0.5, 1.0), dither=False)[0]
        self.assertEqual(px, (255, 128, 255))

    def test_max_brightness_applied_last(self):
        px = led.to_bytes([(1, 1, 1)], 0.5, (1.0, 0.5, 1.0), dither=False)[0]
        self.assertEqual(px, (128, 64, 128))

    def test_lit_channel_never_rounds_to_zero(self):
        self.assertEqual(led.to_bytes([(1, 0, 0)], 0.0005, dither=False)[0][0], 1)

    def test_dither_averages_to_the_exact_value(self):
        total, n = 0, 400
        for _ in range(n):
            total += led.to_bytes([(1, 0, 0)], 0.0123, dither=True)[0][0]
        self.assertAlmostEqual(total / float(n), 0.0123 * 255, delta=0.05)

    def test_wb_helper(self):
        self.assertEqual(led._wb({"white_balance": {"r": 0.5}}), (0.5, 1.0, 1.0))
        self.assertEqual(led._wb(None), (1.0, 1.0, 1.0))


class EncodingTests(unittest.TestCase):
    def test_wire_orders(self):
        for name, order in led.ORDERS.items():
            data = led.encode_bytes([(1, 2, 3)], order)
            expect = b"".join(led._TABLE[(1, 2, 3)[i]] for i in order)
            self.assertEqual(data[:9], expect, name)

    def test_default_is_grb(self):
        self.assertEqual(led.DEFAULT_ORDER, led.ORDERS["GRB"])

    def test_bit_symbols(self):
        self.assertEqual(led._symbols(0), bytes([0b10010010, 0b01001001, 0b00100100]))
        self.assertEqual(led._symbols(255), bytes([0b11011011, 0b01101101, 0b10110110]))


class RenderTests(unittest.TestCase):
    def setUp(self):
        led.reset_dither()

    def msg(self, key, colour, leds=None):
        return {"key": key, "effect": "solid", "speed": "slow", "color": colour,
                "brightness": 1.0, "leds": leds}

    def test_later_message_draws_over_earlier(self):
        frame = led.render([self.msg("a", "#ff0000"), self.msg("b", "#0000ff", [2, 3])], 0.0, 4)
        self.assertEqual(frame[0], (255, 1, 1)[0:1] + frame[0][1:])
        self.assertEqual(frame[1][2], 255)
        self.assertEqual(frame[3][0] > 0, True)       # red still on LED 4

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


class ActiveMessageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()

    def tearDown(self):
        cleanup(self.tmp)

    def test_errors_outrank_information(self):
        msgs = web.active_messages("ok", {"network": False}, wifi=False)
        keys = [m["key"] for m in msgs]
        self.assertEqual(keys[-1], "no-network")        # last = drawn on top
        self.assertIn("ok", keys)

    def test_disabled_message_is_left_out(self):
        cfg = web.led_config()
        cfg["colours"]["dcnow"]["ok"]["enabled"] = False
        web.save_led_config(cfg)
        keys = [m["key"] for m in web.active_messages("ok", {"network": True}, wifi=False)]
        self.assertNotIn("ok", keys)

    def test_brightness_falls_back_to_max(self):
        m = web.active_messages("ok", {"network": True}, wifi=False)[0]
        self.assertEqual(m["brightness"], web.led_config()["max_brightness"])


if __name__ == "__main__":
    unittest.main()
