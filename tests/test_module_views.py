"""What the modules hand to the standard widgets: the texts, lists and flags in /api and in the modules' own answers
(layout.json binds to them, so a wrong word here is a wrong word on the page)."""
import json
import os
import time
import unittest

from support import core, sandbox, cleanup
import rebootupdate_web as ru
import clock_web as clock
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

    def test_reboot_confirm_names_the_pi(self):
        d = {}
        ru.api(d, [])
        self.assertIn("Reboot the computer", d["reboot"]["confirm"])


class ClockView(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        self.tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()

    def tearDown(self):
        if self.tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.tz
        time.tzset()
        tzmod.use_zoneinfo = tzmod.ZoneInfo is not None
        cleanup(self.tmp)

    def test_the_settings_are_a_core_path_and_default_to_24h_only(self):
        self.assertTrue(clock.CLOCK_CONFIG.startswith(self.tmp))
        self.assertEqual(clock.read_config(), {"format": "24h", "beat": False, "world": False, "large": False, "zone": "", "cities": clock.DEFAULT_CITIES})
        self.assertEqual(clock.save_config({"format": " 12H "})["format"], "12h")
        self.assertEqual(clock.save_config({"format": "12h-ampm"})["format"], "12h-ampm")
        self.assertEqual(clock.save_config({"format": "nonsense"})["format"], "24h")
        self.assertEqual(clock.save_config({"format": "beat"})["format"], "24h")           # .beat is a switch of its own now
        got = clock.save_config({"beat": "true", "world": 1})
        self.assertEqual((got["beat"], got["world"]), (True, True))
        self.assertEqual(clock.save_config({"beat": False})["world"], True)               # a key that is not given stays as it was
        self.assertEqual(clock.save_config({"zone": "Asia/Tokyo"})["zone"], "")             # the time zone is not the clock's setting any more ...
        self.assertNotIn("zone", json.load(open(clock.CLOCK_CONFIG)))
        self.assertEqual(core.save_time_zone("Asia/Tokyo"), "Asia/Tokyo")                  # ... it is the common one (Settings > About)
        self.assertEqual(clock.read_config()["zone"], "Asia/Tokyo")
        self.assertEqual(core.save_time_zone("../../etc/passwd"), "")                      # only zones of the list
        self.assertEqual(core.save_time_zone("Mars/Olympus"), "")

    def test_an_older_clock_json_zone_is_carried_over_to_the_common_one(self):
        with open(clock.CLOCK_CONFIG, "w") as f:
            json.dump({"format": "24h", "zone": "Europe/Stockholm"}, f)
        clock.read_config()                                                               # the clock module carries it over when it reads its settings
        self.assertEqual(core.time_zone(), "Europe/Stockholm")
        core.save_time_zone("")                                                           # once set (even to the computer's own) the file wins
        self.assertEqual(core.time_zone(), "")

    def test_an_older_mode_file_is_carried_over(self):
        with open(clock.CLOCK_MODE, "w") as f:
            f.write("beat")
        self.assertEqual((clock.read_config()["format"], clock.read_config()["beat"]), ("24h", True))
        with open(clock.CLOCK_MODE, "w") as f:
            f.write("12h")
        self.assertEqual((clock.read_config()["format"], clock.read_config()["beat"]), ("12h", False))

    def test_the_map_puts_the_clocks_own_place_in_its_winter_band(self):
        cfg = {"zone": "Europe/Stockholm", "format": "24h"}
        summer = 1782000000                                   # 21 June 2026: Stockholm is on UTC+2
        d = clock.here(cfg, summer, 7200)
        self.assertEqual((d["name"], d["text"]), ("Stockholm", "%02d:%02d" % divmod(((summer + 7200) % 86400) // 60, 60)))
        self.assertEqual(round(d["lon"] / 15), 1)             # it sits in the UTC+1 band, not in the +2 one that summer time makes of it
        zone = clock.here({"zone": "Europe/Zurich", "format": "24h"}, summer, 7200)     # a zone with no city of its own
        self.assertEqual(zone["lon"], 15.0)                   # the middle of the band of its winter offset (+1)
        self.assertEqual(clock.view(summer)["map"], None)     # no map while world time is off
        clock.save_config({"world": True})
        core.save_time_zone("Europe/Stockholm")
        m = clock.view(summer)["map"]
        self.assertEqual((m["here"], m["dot"]["name"]), (2.0, "Stockholm"))

    def test_the_city_list_keeps_known_cities_once_and_at_most_twelve(self):
        self.assertEqual(clock.DEFAULT_CITIES, ["Los Angeles", "New York", "São Paulo", "London", "Berlin", "Moscow", "Mumbai", "Tokyo", "Sydney", "Auckland"])
        self.assertEqual(clock.save_config({"cities": ["Tokyo", "Nowhere", "Tokyo", 3, "Stockholm"]})["cities"], ["Tokyo", "Stockholm"])
        many = [c[0] for c in clock.CATALOGUE][:20]
        self.assertEqual(clock.save_config({"cities": many})["cities"], many[:12])
        self.assertEqual(clock.save_config({"cities": []})["cities"], [])                 # all removed is allowed
        self.assertEqual(clock.save_config({"cities": "Tokyo"})["cities"], clock.DEFAULT_CITIES)   # not a list: the defaults
        r = clock._cities_reply()
        self.assertEqual((r["rules"]["per_group"], r["defaults"]["cities"]), (12, clock.DEFAULT_CITIES))
        self.assertEqual(len(r["groups"][0]["choices"]), len(clock.CATALOGUE))
        self.assertTrue(all("now" in o["sub"] for o in r["groups"][0]["choices"]))
        clock.save_config({"cities": many})
        self.assertEqual(clock._cities_reply()["groups"][0]["choices"], [])               # full: nothing more to add

    def test_beat_is_biel_mean_time_not_the_pi_time_zone(self):
        self.assertEqual(clock.format_time("beat", 0), "@041")             # 00:00 UTC = 01:00 BMT
        self.assertEqual(clock.format_time("beat", 23 * 3600), "@000")     # 23:00 UTC = BMT midnight
        self.assertEqual(clock.format_time("beat", 23 * 3600 - 1), "@999")
        os.environ["TZ"] = "Asia/Tokyo"
        time.tzset()
        self.assertEqual(clock.format_time("beat", 0), "@041")             # the same moment everywhere

    def test_12h_and_24h_use_local_time(self):
        t = 13 * 3600 + 5 * 60 + 9
        self.assertEqual(clock.format_time("24h", t), "13:05:09")
        self.assertEqual(clock.format_time("12h-ampm", t), "1:05:09 PM")
        self.assertEqual(clock.format_time("12h-ampm", 0), "12:00:00 AM")
        self.assertEqual(clock.format_time("12h", t), "1:05:09")                          # 12h without the AM / PM
        self.assertEqual(clock.format_time("12h", 0), "12:00:00")

    def test_the_clock_follows_the_picked_zone_with_summer_time(self):
        summer, winter = 1783080000, 1767268800                           # 2026-07-03 12:00 UTC, 2026-01-01 12:00 UTC
        self.assertEqual(clock.view(summer)["time"], "12:00:00")           # the computer's own zone (UTC here)
        core.save_time_zone("Europe/Stockholm")
        self.assertEqual(clock.view(summer)["time"], "14:00:00")
        self.assertEqual(clock.view(winter)["time"], "13:00:00")

    def test_the_three_lines_are_empty_unless_switched_on(self):
        t = 13 * 3600 + 5 * 60 + 9
        v = clock.view(t)
        self.assertEqual((v["time"], v["beat"], v["items"], v["cities"], v["map"]), ("13:05:09", "", [], [], None))
        clock.save_config({"beat": True, "world": True, "format": "12h-ampm"})
        v = clock.view(t)
        self.assertEqual((v["time"], v["beat"]), ("1:05:09 PM", "@%03d .beats" % clock.beats(t)))
        self.assertEqual(len(v["items"]), len(clock.DEFAULT_CITIES))
        self.assertEqual(v["cities"][0], {"title": "Los Angeles", "tag": "5:05 AM"})       # each city with its time, together (the kit list's title and tag)
        self.assertEqual((v["map"]["utc"], v["map"]["here"]), (t, 0.0))
        clock.save_config({"cities": []})
        self.assertEqual((clock.view(t)["world"], clock.view(t)["world_on"]), (False, True))   # nothing to show, the switch stays on

    def test_world_times_follow_the_offsets_with_summer_time(self):
        jan, jul = 1767268800, 1783080000
        got = dict((c["name"], c["text"]) for c in clock.world(clock.read_config(), jan))
        self.assertEqual((got["London"], got["Berlin"], got["Tokyo"], got["Mumbai"], got["Sydney"]), ("12:00", "13:00", "21:00", "17:30", "23:00"))
        got = dict((c["name"], c["text"]) for c in clock.world(clock.read_config(), jul))
        self.assertEqual((got["London"], got["Berlin"], got["New York"], got["Sydney"]), ("13:00", "14:00", "08:00", "22:00"))
        cfg = dict(clock.read_config(), format="12h-ampm")
        self.assertEqual(dict((c["name"], c["text"]) for c in clock.world(cfg, jan))["Tokyo"], "9:00 PM")

    def test_summer_time_also_without_zoneinfo(self):
        tzmod.use_zoneinfo = False                                         # what Python before 3.9 gets: the tz files read by hand
        got = dict((c["name"], c["text"]) for c in clock.world(clock.read_config(), 1783080000))
        self.assertEqual((got["London"], got["Berlin"], got["New York"], got["Sydney"], got["Mumbai"]), ("13:00", "14:00", "08:00", "22:00", "17:30"))

    def test_api_and_form_answer(self):
        clock.save_config({"beat": True})
        d = {}
        clock.api(d, [])
        self.assertRegex(d["clock"]["beat"], r"^@\d{3} \.beats$")
        r = clock._reply()
        self.assertEqual(r["values"], {"format": "24h"})
        self.assertEqual([(o["value"], o["label"]) for o in r["options"]["formats"]], [("12h", "12h"), ("12h-ampm", "12h am/pm"), ("24h", "24h")])
        self.assertNotIn("zones", r["options"])                                            # the time zone is in About now
        self.assertEqual(r["texts"]["clock"], "Shown as 24h")

    def test_the_large_clock_takes_the_rows_beat_and_world_leave_free(self):
        t = 13 * 3600
        self.assertEqual(clock.view(t)["size"], "")                                        # off: always the middle row
        clock.save_config({"large": True})
        self.assertEqual((clock.view(t)["size"], clock.view(t)["large_on"]), ("full", True))     # neither: all three rows
        clock.save_config({"beat": True})
        self.assertEqual(clock.view(t)["size"], "lower")                                   # .beat on: middle and bottom
        clock.save_config({"beat": False, "world": True})
        self.assertEqual(clock.view(t)["size"], "upper")                                   # world time on: top and middle
        clock.save_config({"beat": True})
        self.assertEqual(clock.view(t)["size"], "")                                        # both: the middle row again
        clock.save_config({"beat": False, "cities": []})
        self.assertEqual(clock.view(t)["size"], "full")                                    # world time on without cities shows nothing: counts as off

    def test_the_time_zone_is_a_base_setting_any_module_reads(self):
        self.assertEqual(core.time_zone(), "")
        core.save_time_zone("Asia/Tokyo")
        self.assertEqual(core.time_zone(), "Asia/Tokyo")
        self.assertIn("Tokyo", tzmod.zone_text("Asia/Tokyo"))
        self.assertIn("own time zone", tzmod.zone_text(""))


if __name__ == "__main__":
    unittest.main()
