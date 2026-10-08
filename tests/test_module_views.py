"""What the modules hand to the standard widgets: the texts, lists and flags in /api and in the modules' own answers
(layout.json binds to them, so a wrong word here is a wrong word on the page)."""
import json
import os
import time
import unittest

from support import core, sandbox, cleanup
import rebootupdate_web as ru
import base_tz as tzmod


class UpdateView(unittest.TestCase):
    def base(self, **kw):
        r = {"state": "idle", "checking": False, "time": 1, "error": None, "addon": {"available": False, "current": "v1"},
             "can_update": True, "branch": "main"}
        r.update(kw)
        return r

    def test_up_to_date_and_available(self):
        self.assertEqual(ru.view(self.base())["text"], "Up to date (v1).")
        v = ru.view(self.base(addon={"available": True, "latest": "v2", "latest_date": "2026-10-02T10:00:00Z", "behind": 4, "current": "v1"}))
        self.assertEqual(v["text"], "A newer add-on version is available: v2 (2026-10-02), 4 new changes. You have v1.")
        self.assertTrue(v["show_update"])
        self.assertIn("main branch", v["do_sub"])

    def test_no_update_button_without_a_git_checkout_or_while_busy(self):
        a = {"available": True, "latest": "v2", "current": "v1"}
        self.assertFalse(ru.view(self.base(addon=a, can_update=False))["show_update"])
        self.assertFalse(ru.view(self.base(addon=a, state="running"))["show_update"])

    def test_states(self):
        self.assertTrue(ru.view(self.base(state="running"))["busy"])
        self.assertIn("unavailable", ru.view(self.base(state="running"))["text"])
        self.assertEqual(ru.view(self.base(state="failed"))["text"], "The update failed. Details below.")
        self.assertEqual(ru.view(self.base(checking=True))["text"], "Checking...")
        self.assertTrue(ru.view(self.base(checking=True))["check_disabled"])
        self.assertEqual(ru.view(self.base(time=0))["text"], "Not checked yet")
        self.assertEqual(ru.view(self.base(error="offline"))["text"], "offline")

    def test_reboot_confirm_names_the_computer(self):
        d = {}
        ru.api(d, [])
        self.assertIn("Reboot the computer", d["reboot"]["confirm"])


class TimeZone(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()

    def tearDown(self):
        cleanup(self.tmp)

    def test_the_time_zone_is_a_base_setting_any_module_reads(self):
        self.assertEqual(core.time_zone(), "")
        core.save_time_zone("Asia/Tokyo")
        self.assertEqual(core.time_zone(), "Asia/Tokyo")
        self.assertIn("Tokyo", tzmod.zone_text("Asia/Tokyo"))
        self.assertIn("own time zone", tzmod.zone_text(""))


if __name__ == "__main__":
    unittest.main()
