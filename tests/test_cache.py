"""The page asks for the same settings hundreds of times per request; on a Pi that was most of the time a request took. The reads are
kept for core.CACHE_SECONDS and every write in core clears them."""
import json
import os
import unittest
from unittest import mock

from support import core, sandbox, cleanup


class Cache(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        core.CACHE_SECONDS = 5
        core.invalidate()

    def tearDown(self):
        core.CACHE_SECONDS = 0
        core.invalidate()
        cleanup(self.tmp)

    def test_a_read_is_kept_and_a_copy_is_returned(self):
        names = core.module_names()
        with mock.patch.object(core.os, "listdir", side_effect=AssertionError("read again")):
            self.assertEqual(core.module_names(), names)
        names.append("junk")                                        # the caller may change what it got
        self.assertNotIn("junk", core.module_names())

    def test_every_write_clears_it(self):
        self.assertTrue(core.module_enabled("clock"))
        core.save_module_enabled("clock", False)
        self.assertFalse(core.module_enabled("clock"))
        core.palette_edit("red", name="Cherry", ui="#c00000")
        self.assertEqual(core.colour("red")["name"], "Cherry")
        core.palette_reset()
        self.assertEqual(core.colour("red")["name"], "Red")
        core.set_module_colour("clock", "clock", "bright-pink")
        self.assertEqual(core.module_colours("clock")["clock"], "bright-pink")
        order = core.module_names()
        core.save_module_order(list(reversed(order)))
        self.assertNotEqual(core.module_names(), order)

    def test_a_change_made_by_another_process_shows_after_the_time_is_up(self):
        core.palette_ids()
        with open(core.PALETTE_CUSTOM, "w") as f:
            json.dump({"deleted": ["red"]}, f)
        self.assertIn("red", core.palette_ids())                    # still the kept answer
        core.CACHE_SECONDS = 0.001
        import time
        time.sleep(0.01)
        self.assertNotIn("red", core.palette_ids())

    def test_a_colour_token_is_never_kept(self):
        """It follows the selected network, which another process changes: colours() asks the module's service every time."""
        calls = []
        with mock.patch.object(core, "service", side_effect=lambda n, *a: calls.append(n)):
            core.colours()
            core.colours()
        self.assertEqual(len(calls), 2 * len(core.colour_tokens()))


if __name__ == "__main__":
    unittest.main()
