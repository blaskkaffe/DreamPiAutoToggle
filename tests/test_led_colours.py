"""How the LED shows the palette's colours is the LED module's (netswitch_ledconfig), kept in its own file led_colours.json."""
import json
import os
import unittest

from support import core, ledconfig, sandbox, cleanup


class LedColours(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()

    def tearDown(self):
        cleanup(self.tmp)

    def test_the_shipped_values_and_a_colour_the_user_added(self):
        self.assertEqual(ledconfig.led_colour("red"), "#ff0000")
        self.assertEqual(ledconfig.led_default("orange"), "#ff8c00")
        mine = core.palette_add("Mine", "#102030")
        self.assertEqual(ledconfig.led_colour(mine), "#102030")                       # starts as its screen colour
        core.palette_edit(mine, ui="#405060")
        self.assertEqual(ledconfig.led_colour(mine), "#405060")                       # ... until the LED has a value of its own
        self.assertTrue(ledconfig.set_led_colour(mine, "#a0b0c0"))
        core.palette_edit(mine, ui="#111111")
        self.assertEqual(ledconfig.led_colour(mine), "#a0b0c0")

    def test_changing_and_resetting(self):
        self.assertTrue(ledconfig.set_led_colour("red", "#00ffff"))
        self.assertEqual(json.load(open(ledconfig.LED_COLOURS)), {"red": "#00ffff"})
        core.palette_edit("red", ui="#c00000")                                         # two owners, two files
        self.assertEqual(json.load(open(core.PALETTE_FILE)), {"red": {"ui": "#c00000"}})
        self.assertTrue(core.palette_reset())                                          # the palette's reset keeps what the LED shows ...
        self.assertEqual(ledconfig.led_colour("red"), "#00ffff")
        ledconfig.reset_led_colours()                                                  # ... and the LED's keeps what the screen shows
        self.assertEqual(ledconfig.led_colour("red"), "#ff0000")
        self.assertTrue(ledconfig.set_led_colour("red", "#ff0000"))                    # the default is not kept
        self.assertEqual(json.load(open(ledconfig.LED_COLOURS)), {})
        self.assertFalse(ledconfig.set_led_colour("red", "red"))
        self.assertFalse(ledconfig.set_led_colour("network", "#ffffff"))               # Selected network follows the network, it has no value of its own

    def test_a_deleted_colour_takes_its_led_value_with_it(self):
        mine = core.palette_add("Mine", "#102030")
        ledconfig.set_led_colour(mine, "#a0b0c0")
        core.palette_delete(mine)
        self.assertNotIn(mine, ledconfig.led_overrides())

    def test_the_table_for_the_page_has_the_tokens_fixed(self):
        table = dict((c["id"], c) for c in ledconfig.colour_table())
        self.assertFalse(table["red"]["fixed"])
        self.assertEqual((table["red"]["led"], table["red"]["led_default"]), ("#ff0000", "#ff0000"))
        self.assertTrue(table["network"]["fixed"])
        self.assertEqual(table["network"]["led"], ledconfig.led_colour("network"))


if __name__ == "__main__":
    unittest.main()
