"""The openMenu link module: openMenu's poll / game upload, the phone page's launch request, events and player matching."""
import json
import os
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from support import web, core, sandbox, cleanup
import netswitch_security as security

import netswitch_openmenu as om

UPLOAD = ("#openmenu-games 1 abc12345 3\n"
          "T1234N\t1\t1/1\tU\t\tSonic Adventure 2 (USA)\n"
          "MK51035\t2\t1/2\tU\tRacing\tCrazy Taxi\n"
          "bad line\n"
          "HDR-0001\t3\t1/1\tJ\t\tDeath\tCrypt\n")


class OpenMenu(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        self.saved = dict(om._state)
        om._state.update({"seen": 0.0, "pending": None, "launched": None, "launched_time": 0.0, "games": None,
                          "events": [], "events_time": 1e18, "events_refreshing": False, "events_error": ""})
        self.srv = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]
        web.refresh_page(force=True)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        om._state.clear()
        om._state.update(self.saved)
        cleanup(self.tmp)

    def call(self, method, path, body=None, headers=None):
        req = Request(self.base + path, data=body, method=method, headers=headers or {})
        try:
            r = urlopen(req, timeout=10)
            return r.status, r.read().decode()
        except HTTPError as e:
            return e.code, e.read().decode()

    def upload(self):
        return self.call("POST", "/openmenu/games", UPLOAD.encode(), {"X-Requested-With": "openMenu"})

    def test_poll_asks_for_games_then_stops(self):
        status, text = self.call("GET", "/openmenu/poll?v=1&n=0&h=00000000")
        self.assertEqual(status, 200)
        self.assertEqual(text.splitlines(), ["openmenu 1", "NEED games"])
        self.assertEqual(self.upload()[0], 200)
        _, text = self.call("GET", "/openmenu/poll?v=1&n=3&h=abc12345")
        self.assertEqual(text.splitlines(), ["openmenu 1"])
        _, text = self.call("GET", "/openmenu/poll?v=1&n=3&h=other")
        self.assertIn("NEED games", text)

    def test_upload_parsed_and_kept(self):
        self.upload()
        shown = json.loads(self.call("GET", "/openmenu/games.json")[1])
        self.assertEqual([g["title"] for g in shown["games"]], ["Crazy Taxi", "Death", "Sonic Adventure 2 (USA)"])
        self.assertEqual(shown["count"], 3)
        self.assertTrue(os.path.exists(core.OPENMENU_GAMES))
        om._state["games"] = None                       # a restart reads it back
        self.assertEqual(len(om.games()["games"]), 3)

    def test_bad_upload_refused(self):
        self.assertEqual(self.call("POST", "/openmenu/games", b"hello", {"X-Requested-With": "openMenu"})[0], 400)

    def test_upload_from_another_site_refused(self):
        self.assertEqual(self.call("POST", "/openmenu/games", UPLOAD.encode(), {"Origin": "http://evil.example"})[0], 403)

    def test_launch_needs_connected_dreamcast_and_known_game(self):
        self.upload()
        h = {"X-Requested-With": "netswitch"}
        self.assertEqual(self.call("POST", "/openmenu/launch", json.dumps({"product": "MK51035"}).encode(), h)[0], 409)   # not connected
        self.call("GET", "/openmenu/poll?v=1&n=3&h=abc12345")
        self.assertEqual(self.call("POST", "/openmenu/launch", json.dumps({"product": "NOPE"}).encode(), h)[0], 409)     # not on the card
        self.assertEqual(self.call("POST", "/openmenu/launch", json.dumps({"product": "MK51035"}).encode(), h)[0], 200)

    def test_launch_delivered_once(self):
        self.upload()
        self.call("GET", "/openmenu/poll?v=1&n=3&h=abc12345")
        self.call("POST", "/openmenu/launch", json.dumps({"product": "MK51035"}).encode(), {"X-Requested-With": "netswitch"})
        _, text = self.call("GET", "/openmenu/poll?v=1&n=3&h=abc12345")
        self.assertEqual(text.splitlines(), ["openmenu 1", "LAUNCH MK51035"])
        _, text = self.call("GET", "/openmenu/poll?v=1&n=3&h=abc12345")
        self.assertEqual(text.splitlines(), ["openmenu 1"])

    def test_old_launch_dropped(self):
        self.upload()
        self.call("GET", "/openmenu/poll?v=1&n=3&h=abc12345")
        self.call("POST", "/openmenu/launch", json.dumps({"product": "MK51035"}).encode(), {"X-Requested-With": "netswitch"})
        om._state["pending_time"] -= om.LAUNCH_TTL + 1
        self.assertNotIn("LAUNCH", self.call("GET", "/openmenu/poll?v=1&n=3&h=abc12345")[1])

    def test_launch_from_another_site_refused(self):
        self.assertEqual(self.call("POST", "/openmenu/launch", b'{"product":"MK51035"}', {"Origin": "http://evil.example"})[0], 403)

    def test_matching_players_to_games(self):
        glist = om.parse_games(UPLOAD)[1]
        self.assertEqual(om.match_game("Crazy Taxi", glist)["product"], "MK51035")
        self.assertEqual(om.match_game("sonic adventure 2", glist)["product"], "T1234N")
        self.assertIsNone(om.match_game("Quake III", glist))
        self.assertIsNone(om.match_game("", glist))

    PAGE = ("<html><head><script>var x = 1;\nconst EVENTS = [\n"
            '{"title": "Crazy Taxi night", "date": "2026-10-10T20:00", "end": "2026-10-10T22:00", "location": "Discord",'
            ' "summary": "Come play {braces} here", "source": "discord", "url": "/events/taxi-night"},\n'
            '{"name": "Open lobby", "start": "2026-10-09T19:00", "source": "manual", "url": "javascript:alert(1)"},\n'
            '{"nothing": "here"}\n];\nconst OTHER = [1];</script></head><body>drawn calendar</body></html>')

    def test_events_read_from_the_page(self):
        events, error = om.parse_events(self.PAGE)
        self.assertEqual(error, "")
        self.assertEqual([e["title"] for e in events], ["Open lobby", "Crazy Taxi night"])     # soonest first
        taxi = events[1]
        self.assertEqual((taxi["start"], taxi["end"], taxi["location"], taxi["source"]), ("2026-10-10T20:00", "2026-10-10T22:00", "Discord", "discord"))
        self.assertEqual(taxi["url"], "https://dc99.net/events/taxi-night")
        self.assertIn("{braces}", taxi["text"])
        self.assertEqual(events[0]["url"], "")                                                  # not a web address: dropped

    def test_page_without_events_list_is_reported(self):
        for html in ("<html>nothing</html>", "const EVENTS = [ not json ];", "const EVENTS = [1, 2"):
            events, error = om.parse_events(html)
            self.assertEqual(events, [])
            self.assertIn("EVENTS", error)

    def test_game_found_in_event_text(self):
        glist = om.parse_games(UPLOAD)[1]
        self.assertEqual(om.match_in_text("Crazy Taxi night", glist)["product"], "MK51035")
        self.assertEqual(om.match_in_text("Sonic Adventure 2 (USA) battle", glist)["product"], "T1234N")
        self.assertIsNone(om.match_in_text("Movie night", glist))

    def test_events_get_game_ids_and_survive_a_failed_fetch(self):
        self.upload()
        om.fetch = lambda url: self.PAGE
        om.refresh_events()
        state = json.loads(self.call("GET", "/openmenu/view")[1])
        self.assertEqual([e["product"] for e in state["events"]], ["", "MK51035"])
        def broken(url):
            raise IOError("offline")
        om.fetch = broken
        om.refresh_events()
        state = json.loads(self.call("GET", "/openmenu/view")[1])
        self.assertEqual(len(state["events"]), 2)


    # ---- what the widgets get (layout.json binds to these texts)
    def players_file(self, players, age=0):
        with open(core.PLAYERS_CACHE, "w") as f:
            json.dump({"time": int(time.time()) - age, "players": players}, f)

    def view(self):
        return json.loads(self.call("GET", "/openmenu/view")[1])

    def test_the_status_line_follows_the_dreamcast(self):
        self.assertEqual(self.view()["title"], "Not seen yet")
        self.assertIn("No game list yet", self.view()["message"])
        self.upload()
        self.call("GET", "/openmenu/poll?v=1&n=3&h=abc12345")
        v = self.view()
        self.assertEqual((v["title"], v["message"]), ("Connected", "3 games on the card."))
        om._state["seen"] -= om.SEEN_WINDOW + 1
        v = self.view()
        self.assertEqual(v["title"], "Not connected")
        self.assertIn("Start works while the Dreamcast is connected", v["message"])

    def test_a_queued_and_a_started_game_are_named(self):
        self.upload()
        self.call("GET", "/openmenu/poll?v=1&n=3&h=abc12345")
        self.call("POST", "/openmenu/launch", json.dumps({"product": "MK51035"}).encode(), {"X-Requested-With": "netswitch"})
        self.assertEqual(self.view()["message"], "Waiting for the Dreamcast to start Crazy Taxi...")
        self.call("GET", "/openmenu/poll?v=1&n=3&h=abc12345")
        self.assertEqual(self.view()["message"], "Starting Crazy Taxi on the Dreamcast.")

    def test_a_refused_launch_says_why(self):
        self.upload()
        status, text = self.call("POST", "/openmenu/launch", json.dumps({"product": "MK51035"}).encode(), {"X-Requested-With": "netswitch"})
        self.assertEqual(status, 409)
        self.assertIn("not connected", json.loads(text)["message"])

    def test_players_in_a_game_can_be_joined_when_the_game_is_on_the_card(self):
        self.upload()
        self.players_file([{"player": "Dave", "game": "Crazy Taxi", "network": "DCNow!"}, {"player": "Eve", "game": "Quake III Arena", "network": "DCNET"},
                           {"player": "Idle Ida", "game": "", "network": "DCNow!"}])
        join = self.view()["join"]
        self.assertEqual(join, [{"title": "Dave \u2022 DCNow!", "sub": "Crazy Taxi", "product": "MK51035"},
                                {"title": "Eve \u2022 DCNET", "sub": "Quake III Arena (not on your card)", "product": ""}])     # no game, not listed; not on the card, no product

    def test_the_players_list_is_only_used_while_it_is_current_and_that_module_is_on(self):
        self.upload()
        self.players_file([{"player": "Dave", "game": "Crazy Taxi", "network": "DCNow!"}], age=om.PLAYERS_FRESH + 5)
        self.assertEqual(self.view()["join"], [])                                     # an old list
        self.players_file([{"player": "Dave", "game": "Crazy Taxi", "network": "DCNow!"}])
        self.assertEqual(len(self.view()["join"]), 1)
        core.save_module_enabled("players", False)
        self.assertEqual(self.view()["join"], [])                                     # the module that keeps the list is off

    def test_events_become_rows_with_a_start_button_for_a_game_on_the_card(self):
        self.upload()
        om.fetch = lambda url: self.PAGE
        om.refresh_events()
        rows = self.view()["events"]
        self.assertEqual([r["title"] for r in rows], ["Open lobby", "Crazy Taxi night"])
        taxi = rows[1]
        self.assertEqual((taxi["product"], taxi["game"], taxi["href"]), ("MK51035", "Crazy Taxi", "https://dc99.net/events/taxi-night"))
        self.assertEqual(taxi["sub"].split("\n")[0], "2026-10-10T20:00 \u2013 2026-10-10T22:00 \u2022 Discord \u2022 discord")
        self.assertIn("Come play {braces} here", taxi["sub"])
        self.assertEqual(rows[0]["product"], "")

    def test_the_games_come_as_rows_for_the_search_list(self):
        self.assertEqual(json.loads(self.call("GET", "/openmenu/games.json")[1])["empty"], "No game list yet")
        self.upload()
        rows = json.loads(self.call("GET", "/openmenu/games.json")[1])["games"]
        self.assertEqual(rows[0], {"title": "Crazy Taxi", "sub": "MK51035 \u2022 disc 1/2", "product": "MK51035"})

    def test_starting_a_game_needs_the_pin_when_one_is_set_but_the_dreamcast_does_not(self):
        self.upload()
        self.call("GET", "/openmenu/poll?v=1&n=3&h=abc12345")
        security.set_pin("1234")
        body = json.dumps({"product": "MK51035"}).encode()
        self.assertEqual(self.call("POST", "/openmenu/launch", body, {"X-Requested-With": "netswitch"})[0], 401)
        self.assertEqual(self.call("POST", "/openmenu/launch", body, {"X-Requested-With": "netswitch", "X-Netswitch-Pin": "1234"})[0], 200)
        self.assertEqual(self.call("GET", "/openmenu/poll?v=1&n=3&h=abc12345")[0], 200)                          # openMenu's own calls need no PIN
        self.assertEqual(self.upload()[0], 200)


if __name__ == "__main__":
    unittest.main()
