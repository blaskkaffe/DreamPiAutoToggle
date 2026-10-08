"""A screen that names itself (X-Screen) keeps its own layout settings, tile places and building filter on the host."""
import json
import os
import threading
import unittest
from urllib.request import urlopen, Request

from support import web, core, sandbox, cleanup


class PerScreen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = sandbox()
        cls.srv = web.Server(("127.0.0.1", 0), web.Handler)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cleanup(cls.tmp)

    def api(self, screen=None):
        req = Request(self.base + "/api", headers={"X-Screen": screen} if screen else {})
        return json.loads(urlopen(req, timeout=10).read().decode())

    def post(self, path, body, screen=None):
        headers = {"X-Requested-With": "checkin", "Content-Type": "application/json"}
        if screen:
            headers["X-Screen"] = screen
        return json.loads(urlopen(Request(self.base + path, data=json.dumps(body).encode(), method="POST", headers=headers), timeout=10).read().decode())

    def test_a_screens_settings_stay_with_it(self):
        self.post("/screen/stretch", {"value": True}, "serial-1")
        self.post("/screen/locations", {"value": ["Område A", " ", "B"]}, "serial-1")
        self.post("/modules/dashboard-layout", {"cols": 2, "columns": [["checkin"], ["clock"]]}, "serial-1")
        mine = self.api("serial-1")                                    # a reload or a reboot of that computer: asks again with its id
        self.assertTrue(mine["screen"]["stretch"])
        self.assertEqual(mine["screen"]["locations"], ["Område A", "B"])
        self.assertEqual(mine["tile_layout"], {"2": [["checkin"], ["clock"]]})
        other = self.api("serial-2")                                   # another screen and a plain browser are not touched
        plain = self.api()
        for d in (other, plain):
            self.assertFalse(d["screen"]["stretch"])
            self.assertEqual(d["tile_layout"], {})
        self.assertEqual(other["screen"]["locations"], [])
        self.assertTrue(os.path.exists(os.path.join(core.SCREENS_DIR, "serial-1", "screen.json")))

    def test_a_new_screen_starts_from_the_shared_settings(self):
        self.post("/screen", {"values": {"dash_cols": 3}})
        self.assertEqual(self.api("fresh-screen")["screen"]["dash_cols"], 3)
        self.post("/screen", {"values": {"dash_cols": 2}}, "fresh-screen")
        self.assertEqual(self.api("fresh-screen")["screen"]["dash_cols"], 2)
        self.assertEqual(self.api()["screen"]["dash_cols"], 3)        # the shared setting is as it was

    def test_buildings_are_only_kept_for_a_screen_with_an_id(self):
        self.post("/screen/locations", {"value": ["X"]})
        self.assertNotIn("locations", self.api()["screen"])

    def test_a_bad_id_is_a_plain_browser(self):
        self.assertEqual(core.set_screen("../etc"), "")
        self.assertEqual(core.set_screen("a" * 65), "")
        self.assertEqual(core.set_screen("ok_1-2"), "ok_1-2")
        core.set_screen("")

    def test_the_number_of_screens_is_limited(self):
        old = core.MAX_SCREENS
        core.MAX_SCREENS = len(os.listdir(core.SCREENS_DIR))
        try:
            self.post("/screen/stretch", {"value": True}, "one-too-many")
            self.assertFalse(os.path.exists(os.path.join(core.SCREENS_DIR, "one-too-many")))
        finally:
            core.MAX_SCREENS = old


if __name__ == "__main__":
    unittest.main()
