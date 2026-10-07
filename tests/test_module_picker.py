"""The module picker: module.json v2 (name / description / enabled / visible), the order the user sets (top = first, wins)
and the rules for modules that can't be switched off."""
import json
import os
import shutil
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from support import ROOT, web, core, sandbox, cleanup

REAL_MODULES = os.path.join(ROOT, "modules")


class PickerBase(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        self.modules = os.path.join(self.tmp, "modules")
        shutil.copytree(REAL_MODULES, self.modules, ignore=shutil.ignore_patterns("__pycache__"))
        self.saved, core.MODULES_DIR = core.MODULES_DIR, self.modules

    def tearDown(self):
        core.MODULES_DIR = self.saved
        web.refresh_page(force=True)
        cleanup(self.tmp)

    def add(self, name, manifest):
        os.makedirs(os.path.join(self.modules, name))
        with open(os.path.join(self.modules, name, "module.json"), "w") as f:
            json.dump(manifest, f)

    def layout(self, name, lay):
        with open(os.path.join(self.modules, name, "layout.json"), "w") as f:
            json.dump(lay, f)


class ManifestTests(PickerBase):
    def test_new_and_old_keys_both_work(self):
        self.add("newkeys", {"name": "New", "description": "d", "enabled": False, "visible": True})
        self.add("oldkeys", {"title": "Old", "description": "d", "default": False})
        self.assertEqual(core.module_title("newkeys"), "New")
        self.assertEqual(core.module_title("oldkeys"), "Old")
        self.assertFalse(core.module_enabled("newkeys"))
        self.assertFalse(core.module_enabled("oldkeys"))
        core.save_module_enabled("newkeys", True)
        self.assertTrue(core.module_enabled("newkeys"))

    def test_a_module_that_is_not_visible_is_always_on_and_cannot_be_switched(self):
        self.add("fixed", {"name": "Fixed", "description": "d", "enabled": False, "visible": False})
        self.assertTrue(core.module_enabled("fixed"))
        self.assertFalse(core.save_module_enabled("fixed", False))
        self.assertTrue(core.module_enabled("fixed"))

    def test_the_picker_lists_the_always_on_modules_too_so_they_can_be_moved(self):
        import netswitch_modules as mods
        self.add("fixed", {"name": "Fixed", "description": "d", "enabled": True, "visible": False})
        self.layout("fixed", {"settings": [{"box": "x", "items": [{"type": "text", "text": "a"}]}]})
        got = dict((m["name"], m) for m in mods.listing())
        self.assertIs(got["fixed"]["visible"], False)                    # the page shows it without a switch
        self.assertIs(got["system"]["visible"], False)
        self.assertIs(got["contacts"]["visible"], True)
        self.assertTrue(got["fixed"]["enabled"])
        core.save_module_order(["fixed", "contacts"])
        settings_only = [m["name"] for m in mods.listing() if m["group"] == 1]
        self.assertEqual(settings_only[:2], ["fixed", "contacts"])     # and it can be placed anywhere in the order of its group


class ShownInThePickerTests(PickerBase):
    def names(self):
        import netswitch_modules as mods
        return [m["name"] for m in mods.listing()]

    def test_a_module_with_a_dashboard_box_a_settings_box_or_a_background_is_always_listed(self):
        for name, lay in (("dash", {"dashboard": [{"box": "a", "items": []}]}), ("sett", {"settings": [{"box": "b", "items": []}]}),
                          ("back", {"background": {"type": "fullscreen"}})):
            self.add(name, {"name": name, "description": "d", "enabled": False, "visible": False})      # off, and not switchable
            self.layout(name, lay)
            self.assertIn(name, self.names(), name)

    def test_a_plain_service_without_any_of_them_has_nothing_to_move(self):
        self.add("service", {"name": "Service", "description": "d", "enabled": True, "visible": False})
        self.add("empty", {"name": "Empty", "description": "d", "enabled": True, "visible": False})
        self.layout("empty", {"dashboard": [], "settings": []})
        self.assertNotIn("service", self.names())
        self.assertNotIn("empty", self.names())
        self.add("shown", {"name": "Shown", "description": "d", "enabled": True, "visible": True})      # a visible one is listed whatever it has
        self.assertIn("shown", self.names())


class OrderTests(PickerBase):
    def test_default_order_follows_the_manifest_hint_then_the_name(self):
        self.add("zzz", {"name": "Z", "description": "d", "enabled": True})
        self.add("aaa", {"name": "A", "description": "d", "enabled": True})
        names = core.module_names()
        plain = [n for n in names if core.module_group(n) == 1]            # modules with no layout.json are settings-only: group 1
        self.assertEqual(plain[-2:], ["aaa", "zzz"])                     # no hint = 100: after the hinted ones of the group, by name
        self.assertLess(names.index("checkin"), names.index("contacts"))

    def test_the_saved_order_wins_and_new_modules_go_last(self):
        core.save_module_order(["wifi", "contacts", "nosuchmodule"])
        settings_only = lambda: [n for n in core.module_names() if core.module_group(n) == 1]          # the order is kept inside each group
        self.assertEqual(settings_only()[:2], ["wifi", "contacts"])
        self.assertNotIn("nosuchmodule", core.module_names())
        self.add("later", {"name": "Later", "description": "d", "enabled": True, "order": 1})
        self.assertEqual(settings_only()[:2], ["wifi", "contacts"])
        self.assertEqual(settings_only()[-1], "later")                # not in the saved list yet: after it

    def test_a_bad_order_is_refused_and_a_broken_file_is_ignored(self):
        self.assertIsNone(core.save_module_order("contacts"))
        self.assertIsNone(core.save_module_order([1, 2]))
        with open(core.MODULE_ORDER, "w") as f:
            f.write("{oops")
        self.assertEqual(core.module_names()[0], "checkin")

    def test_a_partial_order_keeps_the_others_in_their_places(self):
        new = core.save_module_order(["wifi"])
        self.assertEqual(new[0], "wifi")
        self.assertEqual(sorted(new), sorted(core.module_names()))


class HttpOrderTests(PickerBase):
    def setUp(self):
        PickerBase.setUp(self)
        web.refresh_page(force=True)
        self.srv = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        PickerBase.tearDown(self)

    def post(self, path, body):
        req = Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                      headers={"X-Requested-With": "x", "Content-Type": "application/json"})
        return urlopen(req, timeout=10)

    def test_post_order_moves_modules_and_the_menu_follows(self):
        got = json.loads(self.post("/modules/order", {"order": ["rebootupdate", "checkin"]}).read())["modules"]
        names = [m["name"] for m in got]
        self.assertLess(names.index("checkin"), names.index("rebootupdate"))               # a dashboard module stays above the settings-only ones
        again = json.loads(urlopen(self.base + "/modules", timeout=10).read())["modules"]
        self.assertEqual([m["name"] for m in again], [m["name"] for m in got])

    def test_api_carries_which_modules_are_on(self):
        en = json.loads(urlopen(self.base + "/api", timeout=10).read())["enabled"]
        self.assertTrue(en["system"] and en["contacts"])
        self.assertFalse(en["wifi"])                                       # off by default, but listed
        self.post("/modules", {"name": "wifi", "enabled": True})
        self.assertTrue(json.loads(urlopen(self.base + "/api", timeout=10).read())["enabled"]["wifi"])

    def test_post_order_rejects_junk(self):
        with self.assertRaises(HTTPError) as e:
            self.post("/modules/order", {"order": "contacts"})
        self.assertEqual(e.exception.code, 400)

    def test_a_hidden_module_cannot_be_switched_off_over_http(self):
        with self.assertRaises(HTTPError) as e:
            self.post("/modules", {"name": "system", "enabled": False})
        self.assertEqual(e.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
