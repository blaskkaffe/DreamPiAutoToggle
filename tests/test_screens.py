"""A screen that names itself (X-Screen) keeps its own layout settings, tile places and building filter on the host."""
import json
import os
import shutil
import threading
import unittest
from urllib.error import HTTPError
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
        self.post("/modules/dashboard-layout", {"cols": 2, "columns": [["checkin"], ["contacts"]]}, "serial-1")
        mine = self.api("serial-1")                                    # a reload or a reboot of that computer: asks again with its id
        self.assertTrue(mine["screen"]["stretch"])
        self.assertEqual(mine["screen"]["locations"], ["Område A", "B"])
        self.assertEqual(mine["tile_layout"], {"2": [["checkin"], ["contacts"]]})
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


class TextSettings(unittest.TestCase):
    def test_text_scale_and_colour_are_validated(self):
        tmp = sandbox()
        try:
            self.assertEqual((core.screen_settings()["font_scale"], core.screen_settings()["font_colour"]), (1.0, "auto"))       # automatic: black on light boxes, white on dark ones
            self.assertEqual(core.save_screen_settings({"font_scale": 1.25, "font_colour": "white"})["font_scale"], 1.25)
            self.assertEqual(core.save_screen_settings({"font_scale": 9})["font_scale"], 2.0)             # 0.5 to 2
            self.assertEqual(core.save_screen_settings({"font_scale": 0.1})["font_scale"], 0.5)
            self.assertEqual(core.save_screen_settings({"font_scale": "x"})["font_scale"], 0.5)           # not a number: unchanged
            self.assertEqual(core.save_screen_settings({"font_scale": True})["font_scale"], 0.5)
            self.assertEqual(core.save_screen_settings({"font_colour": "nope"})["font_colour"], "white")
            self.assertEqual(core.save_screen_settings({"font_colour": "auto"})["font_colour"], "auto")
            core.save_screen_settings({"font_colour": "white"})
            self.assertEqual(core.save_screen_settings({"font_colour": core.palette_ids()[0]})["font_colour"], core.palette_ids()[0])
        finally:
            cleanup(tmp)


class ButtonSounds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = sandbox()
        os.makedirs(core.SOUNDS_DIR)
        for name in os.listdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "base", "sounds")):
            shutil.copy(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "base", "sounds", name), core.SOUNDS_DIR)
        cls.srv = web.Server(("127.0.0.1", 0), web.Handler)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cleanup(cls.tmp)

    def test_the_shipped_sounds_are_listed_and_served_and_more_can_be_copied_in(self):
        self.assertEqual(core.list_sounds(), ["bubble.wav", "pop.wav", "tick.wav"])
        r = urlopen(self.base + "/sounds/pop.wav", timeout=10)
        self.assertEqual((r.status, r.headers["Content-Type"]), (200, "audio/wav"))
        self.assertEqual(r.read()[:4], b"RIFF")
        with open(os.path.join(core.SOUNDS_DIR, "my click.mp3"), "wb") as f:
            f.write(b"ID3")
        with open(os.path.join(core.SOUNDS_DIR, "notes.txt"), "w") as f:
            f.write("x")
        self.assertIn("my click.mp3", core.list_sounds())
        self.assertNotIn("notes.txt", core.list_sounds())                                    # only sound files
        self.assertEqual(urlopen(self.base + "/sounds/my%20click.mp3", timeout=10).headers["Content-Type"], "audio/mpeg")
        for bad in ("notes.txt", "..%2Fscreen.json", "nope.wav"):
            with self.assertRaises(HTTPError, msg=bad) as e:
                urlopen(self.base + "/sounds/" + bad, timeout=10)
            self.assertEqual(e.exception.code, 404)

    def test_the_sound_settings(self):
        d = core.screen_settings()
        self.assertEqual((d["sound"], d["sound_name"], d["sound_volume"]), (True, "pop.wav", 0.6))
        self.assertEqual(core.save_screen_settings({"sound": False, "sound_volume": 7, "sound_name": "tick.wav"})["sound_volume"], 1.0)
        self.assertEqual(core.save_screen_settings({"sound_name": "../x"})["sound_name"], "tick.wav")      # not a plain file name: unchanged
        self.assertFalse(core.screen_settings()["sound"])
        core.save_screen_settings({"sound": True, "sound_volume": 0.6, "sound_name": "pop.wav"})


class DayAndNight(unittest.TestCase):
    def test_the_suns_height(self):
        import calendar
        import base_tz as tz
        noon = calendar.timegm((2026, 6, 21, 11, 0, 0))            # Stockholm, midsummer, about solar noon
        self.assertAlmostEqual(tz.sun_elevation(59.3, 18.1, noon), 54.1, delta=1.0)
        self.assertLess(tz.sun_elevation(59.3, 18.1, calendar.timegm((2026, 12, 21, 23, 0, 0))), -50)       # midwinter night
        self.assertAlmostEqual(tz.sun_elevation(-33.9, 151.2, calendar.timegm((2026, 12, 21, 1, 0, 0))), 74.4, delta=1.5)
        self.assertEqual(tz.zone_place("Europe/Stockholm"), (59.3, 18.1))
        self.assertEqual(tz.zone_place("UTC")[0], 50.0)             # a zone with no city: the middle of its band

    def test_daylight_follows_the_time_zone_and_the_theme_can_follow_it(self):
        import calendar
        tmp = sandbox()
        try:
            core.save_time_zone("Europe/Stockholm")
            day = core.daylight(calendar.timegm((2026, 6, 21, 11, 0, 0)))
            night = core.daylight(calendar.timegm((2026, 6, 21, 23, 30, 0)))
            self.assertEqual((day["day"], night["day"], day["zone"]), (True, False, "Europe/Stockholm"))
            core.save_time_zone("Australia/Sydney")
            self.assertFalse(core.daylight(calendar.timegm((2026, 6, 21, 11, 0, 0)))["day"])      # the same moment is night in Sydney
            self.assertEqual(core.save_screen_settings({"theme": "time"})["theme"], "time")        # the theme that follows the time of day
            self.assertEqual(core.screen_settings()["theme"], "time")
        finally:
            cleanup(tmp)


if __name__ == "__main__":
    unittest.main()
