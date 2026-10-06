"""The DC99 events module: reading the community page, time zones, the SQLite store (duplicates, changes, removed events,
failed imports), the JSON API and its filters, reminders (banner, highlight, the LED message) and the settings."""
import calendar
import json
import os
import time
import unittest

from support import core, ledconfig, sandbox, cleanup
import netswitch_events as ev
import netswitch_tz as tz


def utc(*a):
    return calendar.timegm(a + (0,) * (6 - len(a)))


def page(events):
    """A community page the way dc99.net writes it (October 2026): the list in a script, the calendar code after it."""
    return ("<html><body><div id='calGrid'></div><script>\n(function(){\n  const EVENTS = %s;\n"
            "  const SOURCE_LABELS = { manual: 'DC99' };\n  // ... ];\n})();\n</script></body></html>" % json.dumps(events))


E_DISCORD = {"title": "US Game Night", "date": "2026-10-08 21:00:00", "endDate": None, "allDay": False, "location": None,
             "summary": "Join hawkzero for Thursday night dreamcastin'", "source": "discord", "url": "/events/us-game-night-2026-10-08",
             "external": False}
E_UK = {"title": "Game Night UK: F355 Challenge", "allDay": False, "location": None, "summary": None, "url": "https://dreamcastlive.net/schedule/",
        "source": "dreamcastlive", "external": True, "date": "2026-10-11 20:00:00", "endDate": "2026-10-11 21:30:00"}
E_US = {"title": "Game Night: Sega Tetris", "allDay": False, "location": None, "summary": None, "url": "https://dreamcastlive.net/schedule/",
        "source": "dreamcastlive", "external": True, "date": "2026-10-14 21:00:00", "endDate": "2026-10-14 22:30:00"}
NOW = utc(2026, 10, 4, 12)


class FakeTime(object):
    """The time module with a fixed now (the module under test asks time.time() in places; the tests must not age)."""
    def __init__(self, now):
        self.now = now

    def time(self):
        return self.now

    def __getattr__(self, name):
        return getattr(time, name)


class FakeHandler(object):
    def __init__(self, path="/", body=None):
        self.path, self.body, self.sent = path, json.dumps(body or {}).encode("utf-8"), None

    def _body(self, limit):
        return self.body[:limit]

    def send(self, body, ctype, status=200, **kw):
        self.sent = (status, ctype, body)

    def json(self):
        return json.loads(self.sent[2])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        self.saved_fetch = ev.fetch
        self.clock = ev.time = FakeTime(NOW)
        os.environ.pop("DC99_MOCK", None)
        os.environ.pop("DC99_SYNC_INTERVAL", None)

    def tearDown(self):
        ev.fetch = self.saved_fetch
        ev.time = time
        cleanup(self.tmp)

    def serve(self, events):
        ev.fetch = lambda url: page(events)

    def get(self, path, fn=None):
        h = FakeHandler(path)
        (fn or ev.GET.get(path.split("?")[0]) or ev.GET_PREFIX["/api/events/"])(h)
        return h

    def post(self, path, body):
        h = FakeHandler(path, body)
        ev.POST[path](h)
        return h


class Parsing(Base):
    def test_the_list_is_read_from_the_page(self):
        got = ev.extract_events(page([E_DISCORD, E_UK]))
        self.assertEqual([e["title"] for e in got], ["US Game Night", "Game Night UK: F355 Challenge"])

    def test_a_page_without_the_list_is_an_error(self):
        self.assertRaises(ValueError, ev.extract_events, "<html>no calendar here</html>")
        self.assertRaises(ValueError, ev.extract_events, "const EVENTS = [{broken")

    def test_normalized_event(self):
        r = ev.normalize(E_DISCORD)
        self.assertEqual((r["source"], r["source_event_id"], r["url"]), ("discord", "us-game-night-2026-10-08", "https://dc99.net/events/us-game-night-2026-10-08"))
        self.assertEqual((r["game"], r["network"], r["description"]), (None, None, "Join hawkzero for Thursday night dreamcastin'"))   # no guessing
        r = ev.normalize(E_US)
        self.assertEqual(r["game"], "Sega Tetris")
        self.assertEqual(r["url"], "https://dreamcastlive.net/schedule/")
        self.assertEqual(len(r["source_event_id"]), 16)               # DreamcastLive has no id: one is made from title and time
        self.assertIsNone(ev.normalize({"title": "", "date": "2026-10-01 10:00:00"}))
        self.assertIsNone(ev.normalize({"title": "x", "date": "tomorrow"}))

    def test_times_are_us_eastern_and_uk_events_uk_time(self):
        self.assertEqual(ev.normalize(E_DISCORD)["start_utc"], utc(2026, 10, 9, 1))      # 21:00 EDT
        self.assertEqual(ev.normalize(E_UK)["start_utc"], utc(2026, 10, 11, 19))         # 20:00 BST
        self.assertEqual(ev.normalize(E_UK)["end_utc"], utc(2026, 10, 11, 20, 30))
        winter = dict(E_DISCORD, date="2026-12-03 21:00:00")
        self.assertEqual(ev.normalize(winter)["start_utc"], utc(2026, 12, 4, 2))         # 21:00 EST
        self.assertEqual(ev.source_zone("Game Night UK: Starlancer"), "Europe/London")
        self.assertEqual(ev.source_zone("Ukulele night"), "America/New_York")           # "UK" as a word only

    def test_times_are_the_same_without_zoneinfo(self):
        tz.use_zoneinfo = False
        try:
            self.assertEqual(ev.normalize(E_DISCORD)["start_utc"], utc(2026, 10, 9, 1))
            self.assertEqual(ev.normalize(E_UK)["start_utc"], utc(2026, 10, 11, 19))
        finally:
            tz.use_zoneinfo = tz.ZoneInfo is not None

    def test_iso_times_in_the_display_zone(self):
        self.assertEqual(ev.iso(utc(2026, 10, 9, 1), "Europe/Stockholm"), "2026-10-09T03:00:00+02:00")
        self.assertEqual(ev.iso(utc(2026, 10, 9, 1), "America/New_York"), "2026-10-08T21:00:00-04:00")
        self.assertEqual(ev.iso(utc(2026, 12, 4, 2), "Asia/Kolkata"), "2026-12-04T07:30:00+05:30")


class Store(Base):
    def test_import_adds_then_finds_no_duplicates(self):
        self.serve([E_DISCORD, E_UK, E_US])
        r = ev.import_events(NOW)
        self.assertEqual((r["ok"], r["added"], r["changed"], r["removed"], r["total"]), (True, 3, 0, 0, 3))
        r = ev.import_events(NOW + 60)
        self.assertEqual((r["added"], r["changed"], r["total"]), (0, 0, 3))
        self.serve([E_DISCORD, E_DISCORD, E_UK, E_US])                   # the same event twice in the page: stored once
        self.assertEqual(ev.import_events(NOW + 120)["total"], 3)
        self.assertEqual(len(ev.query()), 3)

    def test_a_changed_event_is_updated_in_place(self):
        self.serve([E_DISCORD])
        ev.import_events(NOW)
        first = ev.query()[0]
        self.serve([dict(E_DISCORD, summary="Now with Quake III Arena")])
        r = ev.import_events(NOW + 3600)
        self.assertEqual((r["added"], r["changed"]), (0, 1))
        row = ev.query()[0]
        self.assertEqual((row["id"], row["description"], row["last_updated"]), (first["id"], "Now with Quake III Arena", NOW + 3600))

    def test_gone_future_events_are_marked_removed_and_come_back(self):
        past = dict(E_DISCORD, date="2026-09-03 21:00:00", url="/events/us-game-night-2026-09-03")
        self.serve([past, E_DISCORD, E_UK])
        ev.import_events(NOW)
        self.serve([E_UK])
        r = ev.import_events(NOW + 60)
        self.assertEqual(r["removed"], 1)                                 # the future one; the past one is history and stays
        removed = dict((x["source_event_id"], x["removed"]) for x in ev.query())
        self.assertEqual(removed, {"us-game-night-2026-09-03": 0, "us-game-night-2026-10-08": 1, ev.normalize(E_UK)["source_event_id"]: 0})
        self.serve([E_DISCORD, E_UK])
        self.assertEqual(ev.import_events(NOW + 120)["changed"], 1)
        self.assertEqual([x["removed"] for x in ev.query("source_event_id=?", ("us-game-night-2026-10-08",))], [0])

    def test_a_failed_import_keeps_everything(self):
        self.serve([E_DISCORD, E_UK])
        ev.import_events(NOW)
        tries = []

        def down(url):
            tries.append(url)
            raise IOError("no route to host")
        ev.fetch = down
        r = ev.import_events(NOW + 60, sleep=lambda s: None)
        self.assertFalse(r["ok"])
        self.assertIn("no route to host", r["error"])
        self.assertEqual(len(tries), ev.RETRIES + 1)                       # tried again before giving up
        self.assertEqual(len(ev.query("removed=0")), 2)                    # nothing lost
        st = ev.status(NOW + 60)
        self.assertEqual((st["events"], st["database"]), (2, "ok"))
        self.assertIn("no route to host", st["last_error"])
        self.assertTrue(st["last_import"])
        for broken in ("<html>DC99 is being rebuilt</html>", page([])):     # the page changed, or lists nothing
            ev.fetch = lambda url, b=broken: b
            self.assertFalse(ev.import_events(NOW + 120)["ok"])
            self.assertEqual(len(ev.query("removed=0")), 2)

    def test_mock_mode_reads_the_sample_ahead_of_now(self):
        os.environ["DC99_MOCK"] = "1"
        ev.fetch = lambda url: self.fail("mock mode must not download")
        self.clock.now = NOW + 60 * 86400
        r = ev.import_events(NOW + 60 * 86400)
        self.assertTrue(r["ok"])
        self.assertGreaterEqual(r["total"], 10)
        self.assertTrue(all(x["start_utc"] > NOW + 60 * 86400 - 7 * 86400 for x in ev.query()))
        self.assertTrue(ev.status()["mock"])

    def test_sync_interval(self):
        self.assertEqual(ev.sync_interval(), 60)
        ev.save_config({"interval": 15})
        self.assertEqual(ev.sync_interval(), 15)
        for env, minutes in (("15m", 15), ("2h", 120), ("90", 90), ("1800s", 30)):
            os.environ["DC99_SYNC_INTERVAL"] = env
            self.assertEqual(ev.sync_interval(), minutes, env)
        os.environ.pop("DC99_SYNC_INTERVAL")


class CommonSettings(Base):
    def test_the_time_zone_is_the_common_one_and_the_reminder_picker_has_no_info_text(self):
        self.assertEqual(ev.read_config()["zone"], "")
        core.save_time_zone("Asia/Tokyo")
        self.assertEqual(ev.display_zone(), "Asia/Tokyo")                       # read from the global setting
        self.assertNotIn("zones", ev._settings_reply()["options"])
        self.assertNotIn("zone", ev._settings_reply()["values"])
        self.assertNotIn("help", ev._series_reply()["rules"])                    # no (i) button: how a reminder reaches the clock is for the module rework


class Api(Base):
    def setUp(self):
        Base.setUp(self)
        self.serve([E_DISCORD, E_UK, E_US])
        ev.import_events(NOW)
        core.save_time_zone("Europe/Stockholm")

    def test_events_and_filters(self):
        d = self.get("/api/events").json()
        self.assertEqual((d["count"], d["timezone"]), (3, "Europe/Stockholm"))
        first = d["events"][0]
        self.assertEqual((first["title"], first["start_time"], first["source_label"]), ("US Game Night", "2026-10-09T03:00:00+02:00", "Sega Online Discord"))
        self.assertEqual(self.get("/api/events?source=dreamcastlive").json()["count"], 2)
        self.assertEqual([e["title"] for e in self.get("/api/events?game=sega%20tetris").json()["events"]], ["Game Night: Sega Tetris"])
        self.assertEqual(self.get("/api/events?from=2026-10-10&to=2026-10-11").json()["count"], 1)    # to: the whole day
        self.assertEqual(self.get("/api/events?from=2026-10-09&to=2026-10-09").json()["count"], 1)    # 03:00 Stockholm on the 9th
        self.assertEqual(self.get("/api/events?network=DCNET").json()["count"], 0)
        d = self.get("/api/events?tz=America/New_York").json()
        self.assertEqual(d["events"][0]["start_time"], "2026-10-08T21:00:00-04:00")
        self.assertEqual(self.get("/api/events?from=yesterday").sent[0], 400)
        self.assertEqual(self.get("/api/events?tz=Mars/Base").sent[0], 400)

    def test_upcoming_one_event_sources_games_status(self):
        up = self.get("/api/events/upcoming?limit=2").json()
        self.assertEqual([e["title"] for e in up["events"]], ["US Game Night", "Game Night UK: F355 Challenge"])
        eid = up["events"][0]["id"]
        one = self.get("/api/events/%d" % eid).json()
        self.assertEqual((one["id"], one["raw_data"]["source"]), (eid, "discord"))
        self.assertEqual(self.get("/api/events/99999").sent[0], 404)
        self.assertEqual(self.get("/api/events/x").sent[0], 404)
        src = dict((s["id"], s["events"]) for s in self.get("/api/sources").json()["sources"])
        self.assertEqual(src, {"discord": 1, "dreamcastlive": 2, "manual": 0})
        self.assertEqual(self.get("/api/games").json()["games"], [{"game": "F355 Challenge", "events": 1}, {"game": "Sega Tetris", "events": 1}])
        st = self.get("/api/status").json()
        self.assertEqual((st["database"], st["events"], st["source"]), ("ok", 3, "dc99"))


class Reminders(Base):
    def setUp(self):
        Base.setUp(self)
        self.serve([E_DISCORD, E_UK, E_US])
        ev.import_events(NOW)
        self.ids = dict((r["title"], str(r["id"])) for r in ev.query())

    def remind(self, title, on=True):
        return self.post("/events/remind", {"id": self.ids[title], "on": on}).json()

    def test_the_bell_and_the_reminder_file(self):
        v = self.remind("US Game Night")
        self.assertTrue([x for x in v["list"] if x["title"] == "US Game Night"][0]["reminded"])
        data = json.load(open(core.EVENT_REMINDERS))
        self.assertEqual([i["title"] for i in data["items"]], ["US Game Night"])
        start = utc(2026, 10, 9, 1)
        self.assertIsNone(core.event_reminder(start - 16 * 60))            # 15 minutes before by default
        self.assertEqual(core.event_reminder(start - 15 * 60)["title"], "US Game Night")
        self.assertEqual(core.event_reminder(start + 9 * 60)["title"], "US Game Night")
        self.assertIsNone(core.event_reminder(start + 10 * 60))
        self.remind("US Game Night", False)
        self.assertIsNone(core.event_reminder(start))

    def test_the_soonest_events_are_in_the_file_for_the_openmenu_link(self):
        self.remind("US Game Night")
        data = json.load(open(core.EVENT_REMINDERS))
        self.assertEqual([i["title"] for i in data["upcoming"]][0], "US Game Night")             # reminded or not: the soonest first
        self.assertEqual(len(data["upcoming"]), 3)
        start = utc(2026, 10, 9, 1)
        self.assertEqual(core.next_event(start - 3600)["title"], "US Game Night")
        self.assertEqual(core.next_event(start + 9 * 60)["title"], "US Game Night")             # still counts while its reminder window lasts
        self.assertNotEqual((core.next_event(start + 11 * 60) or {}).get("title"), "US Game Night")   # then the next one

    def test_banner_highlight_and_dismiss(self):
        self.remind("US Game Night")
        start = utc(2026, 10, 9, 1)
        d = {"notices": [], "highlight": {}}
        self.clock.now = start - 12 * 60
        ev.api(d, [])
        self.assertEqual(len(d["notices"]), 1)
        self.assertIn("US Game Night", d["notices"][0]["text"])
        self.assertIn("in 12 min", d["notices"][0]["text"])
        self.assertEqual(d["notices"][0]["post"], "/events/dismiss")
        self.assertEqual(set(d["highlight"]), {"clock", "events"})
        self.post("/events/dismiss", {"id": d["notices"][0]["id"]})
        self.assertIsNone(core.event_reminder(start - 12 * 60))

    def test_a_series_reminds_of_every_event_with_that_name(self):
        r = self.post("/events/series", {"series": ["Game Night UK: F355 Challenge", "", 5]}).json()
        self.assertEqual(r["groups"][0]["items"], ["Game Night UK: F355 Challenge"])
        self.assertIn("US Game Night", [c["value"] for c in r["groups"][0]["choices"]])
        self.assertEqual(core.event_reminder(utc(2026, 10, 11, 19) - 60)["title"], "Game Night UK: F355 Challenge")

    def test_the_led_message(self):
        self.remind("US Game Night")
        self.assertIn("event-soon", [m["key"] for m in ledconfig.messages()])
        ctx = ledconfig.gather(live=False)
        ctx["event"] = core.event_reminder(utc(2026, 10, 9, 1) - 60)
        self.assertIn("event-soon", ledconfig.active_keys(ctx))
        ctx["event"] = None
        self.assertNotIn("event-soon", ledconfig.active_keys(ctx))
        self.assertIn("event-soon", [m for g in ledconfig.default_groups() for m in g["messages"]])

    def test_settings(self):
        r = self.get("/events/settings").json()
        self.assertEqual(r["values"], {"lead": 15, "interval": 60})
        r = self.post("/events/settings", {"values": {"lead": 30, "zone": "Europe/Stockholm", "interval": 7}}).json()
        self.assertEqual(r["values"], {"lead": 30, "interval": 60})                                  # 7 is not a choice; the zone is not an events setting
        self.assertEqual(core.time_zone(), "")                                                       # and posting one here does not change the common one
        self.assertNotIn("zone", json.load(open(core.EVENTS_CONFIG)))
        self.remind("US Game Night")
        self.assertEqual(json.load(open(core.EVENT_REMINDERS))["lead"], 30)
        self.assertEqual(core.event_reminder(utc(2026, 10, 9, 1) - 29 * 60)["title"], "US Game Night")

    def test_the_box_view(self):
        v = ev.view(NOW)
        self.assertEqual(v["next"]["title"], "US Game Night")
        self.assertEqual([x["title"] for x in v["list"]], ["US Game Night", "Game Night UK: F355 Challenge", "Game Night: Sega Tetris"])
        self.assertEqual(v["list"][0]["source"], "Sega Online Discord")
        self.assertIn("Synced with DC99", v["status"])
        self.assertTrue(all(x["day"] and x["hm"] for x in v["list"]))


if __name__ == "__main__":
    unittest.main()
