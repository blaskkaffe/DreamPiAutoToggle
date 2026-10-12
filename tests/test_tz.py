"""base_tz: time zone offsets with summer time on any Python. Without zoneinfo (Python before 3.9) the module reads the system's
TZif files itself; these tests check that reader against zoneinfo (when this Python has it) and against known dates."""
import calendar
import random
import struct
import unittest

import support  # noqa: F401  (puts the repo on the path)
import base_tz as tz


def utc(*a):
    return calendar.timegm(a + (0,) * (6 - len(a)))


class Reader(unittest.TestCase):
    def setUp(self):
        tz.use_zoneinfo = False
        tz._cache.clear()

    def tearDown(self):
        tz.use_zoneinfo = tz.ZoneInfo is not None

    def test_known_offsets(self):
        self.assertEqual(tz.offset("Europe/Stockholm", utc(2026, 7, 1, 12)), 7200)
        self.assertEqual(tz.offset("Europe/Stockholm", utc(2026, 12, 1, 12)), 3600)
        self.assertEqual(tz.offset("America/New_York", utc(2026, 7, 1, 12)), -4 * 3600)
        self.assertEqual(tz.offset("Australia/Sydney", utc(2026, 1, 1, 12)), 11 * 3600)   # summer in January
        self.assertEqual(tz.offset("Asia/Kolkata", utc(2026, 7, 1)), 19800)
        self.assertEqual(tz.offset("Asia/Kathmandu", utc(2026, 7, 1)), 20700)
        self.assertEqual(tz.offset("UTC", utc(2026, 7, 1)), 0)

    def test_the_change_to_summer_time_to_the_second(self):
        change = utc(2026, 3, 29, 1)                          # Europe: the last Sunday in March, 01:00 UTC
        self.assertEqual(tz.offset("Europe/Stockholm", change - 1), 3600)
        self.assertEqual(tz.offset("Europe/Stockholm", change), 7200)
        back = utc(2026, 10, 25, 1)
        self.assertEqual(tz.offset("Europe/Stockholm", back - 1), 7200)
        self.assertEqual(tz.offset("Europe/Stockholm", back), 3600)

    def test_far_future_dates_use_the_rule_at_the_end_of_the_file(self):
        self.assertEqual(tz.offset("Europe/Stockholm", utc(2045, 7, 1)), 7200)
        self.assertEqual(tz.offset("America/Santiago", utc(2045, 1, 1)), -3 * 3600)
        self.assertEqual(tz.offset("Australia/Lord_Howe", utc(2045, 1, 1)), 11 * 3600)   # a half-hour summer time

    def test_unknown_or_odd_names(self):
        for z in ("Mars/Olympus", "../../etc/passwd", "", None, "Europe/Stockholm/../../x"):
            self.assertIsNone(tz.offset(z, 0), z)

    def test_renamed_zones_work_under_either_name(self):
        self.assertEqual(tz.offset("Europe/Kyiv", utc(2026, 7, 1)), 3 * 3600)
        self.assertEqual(tz.offset("Europe/Kiev", utc(2026, 7, 1)), 3 * 3600)

    def test_posix_rules(self):
        r = tz.parse_posix("CET-1CEST,M3.5.0,M10.5.0/3")
        self.assertEqual((r["std"], r["dst"]), (3600, 7200))
        self.assertEqual(tz.posix_offset(r, utc(2030, 7, 1)), 7200)
        self.assertEqual(tz.posix_offset(r, utc(2030, 1, 1)), 3600)
        r = tz.parse_posix("<-03>3")                          # no summer time
        self.assertEqual(tz.posix_offset(r, utc(2030, 7, 1)), -3 * 3600)
        r = tz.parse_posix("AEST-10AEDT,M10.1.0,M4.1.0/3")     # southern: summer over the new year
        self.assertEqual(tz.posix_offset(r, utc(2030, 1, 1)), 11 * 3600)
        self.assertEqual(tz.posix_offset(r, utc(2030, 7, 1)), 10 * 3600)
        self.assertIsNone(tz.parse_posix(""))

    def test_a_broken_file_is_no_zone(self):
        self.assertRaises(ValueError, tz.parse_tzif, b"nope")
        self.assertRaises((ValueError, struct.error), tz.parse_tzif, b"TZif2" + b"\0" * 10)

    @unittest.skipIf(tz.ZoneInfo is None, "this Python has no zoneinfo to compare with")
    def test_the_same_answers_as_zoneinfo(self):
        rnd = random.Random(7)
        zones = sorted(set(c[1] for c in tz.CITIES)) + ["America/Santiago", "Africa/Casablanca", "Pacific/Chatham", "Asia/Tehran"]
        for z in zones:
            for _ in range(200):
                t = rnd.randint(utc(1990, 1, 1), utc(2040, 1, 1))
                tz.use_zoneinfo = True
                want = tz.offset(z, t)
                tz.use_zoneinfo = False
                self.assertEqual(tz.offset(z, t), want, "%s at %d" % (z, t))


class Conversions(unittest.TestCase):
    def test_wall_clock_to_utc(self):
        for zi in (False, True):
            tz.use_zoneinfo = zi and tz.ZoneInfo is not None
            self.assertEqual(tz.local_to_utc("America/New_York", 2026, 10, 8, 21, 0), utc(2026, 10, 9, 1))
            self.assertEqual(tz.local_to_utc("Europe/London", 2026, 10, 11, 20, 0), utc(2026, 10, 11, 19))
            self.assertEqual(tz.local_to_utc("Europe/Stockholm", 2026, 3, 29, 2, 30), utc(2026, 3, 29, 1, 30))   # skipped: an hour later
            self.assertEqual(tz.local_to_utc("Europe/Stockholm", 2026, 10, 25, 2, 30), utc(2026, 10, 25, 0, 30))  # twice: the first
            self.assertIsNone(tz.local_to_utc("Mars/Olympus", 2026, 1, 1))
        tz.use_zoneinfo = tz.ZoneInfo is not None

    def test_texts_and_the_city_list(self):
        self.assertEqual((tz.utc_text(0), tz.utc_text(3600), tz.utc_text(-3 * 3600), tz.utc_text(19800)), ("UTC", "UTC+1", "UTC-3", "UTC+5:30"))
        self.assertEqual(tz.zone_name("Europe/Stockholm"), "Stockholm")
        self.assertEqual(tz.zone_name("America/Argentina/Buenos_Aires"), "Buenos Aires")
        self.assertEqual([c for c in tz.CITIES if tz.offset(c[1]) is None], [])          # every city's zone is known here
        opts = tz.zone_options()
        self.assertEqual((opts[0]["value"], opts[-1]["value"]), ("", "UTC"))


if __name__ == "__main__":
    unittest.main()
