"""The openMenu link module: openMenu's poll / game upload, the phone page's launch request and the texts the box shows."""
import json
import os
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from support import web, core, sandbox, cleanup

import netswitch_openmenu as om

UPLOAD = ("#openmenu-games 1 abc12345 3\n"
          "T1234N\t1\t1/1\tU\t\tSonic Adventure 2 (USA)\n"
          "MK51035\t2\t1/2\tU\tRacing\tCrazy Taxi\n"
          "bad line\n"
          "HDR-0001\t3\t1/1\tJ\t\tDeath\tCrypt\n")
POLL = "/openmenu/poll?v=1&n=3&h=abc12345"
PAGE = {"X-Requested-With": "netswitch"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        self.saved = dict(om._state)
        om._state.update({"seen": 0.0, "pending": None, "launched": None, "launched_time": 0.0, "games": None})
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

    def launch(self, product, headers=PAGE):
        return self.call("POST", "/openmenu/launch", json.dumps({"product": product}).encode(), headers)

    def view(self):
        return json.loads(self.call("GET", "/openmenu/view")[1])



class OpenMenu(Base):
    # ---- what openMenu does
    def test_poll_asks_for_games_then_stops(self):
        status, text = self.call("GET", "/openmenu/poll?v=1&n=0&h=00000000")
        self.assertEqual(status, 200)
        self.assertEqual(text.splitlines(), ["openmenu 1", "NEED games", "NET dcnow", "DCNET off inactive"])
        self.assertEqual(self.upload()[0], 200)
        self.assertEqual(self.call("GET", POLL)[1].splitlines(), ["openmenu 1", "NET dcnow", "DCNET off inactive"])
        self.assertIn("NEED games", self.call("GET", "/openmenu/poll?v=1&n=3&h=other")[1])

    def test_upload_parsed_sorted_and_kept(self):
        self.upload()
        got = json.loads(self.call("GET", "/openmenu/games")[1])
        self.assertEqual([g["name"] for g in got["games"]], ["Crazy Taxi", "Death", "Sonic Adventure 2 (USA)"])
        self.assertEqual(got["hash"], "abc12345")
        self.assertTrue(os.path.exists(core.OPENMENU_GAMES))
        om._state["games"] = None                       # a restart reads it back
        self.assertEqual(len(om.games()["games"]), 3)

    def test_bad_upload_refused(self):
        self.assertEqual(self.call("POST", "/openmenu/games", b"hello", {"X-Requested-With": "openMenu"})[0], 400)

    def test_upload_from_another_site_refused(self):
        self.assertEqual(self.call("POST", "/openmenu/games", UPLOAD.encode(), {"Origin": "http://evil.example"})[0], 403)

    # ---- launching a game from the phone
    def test_launch_needs_connected_dreamcast_and_known_game(self):
        self.upload()
        status, text = self.launch("MK51035")                                    # nothing has polled yet
        self.assertEqual(status, 409)
        self.assertIn("not connected", json.loads(text)["message"])
        self.call("GET", POLL)
        status, text = self.launch("NOPE")
        self.assertEqual(status, 409)
        self.assertIn("not on the card", json.loads(text)["message"])
        self.assertEqual(self.launch("MK51035")[0], 200)

    def test_launch_delivered_once(self):
        self.upload()
        self.call("GET", POLL)
        self.launch("MK51035")
        self.assertEqual(self.call("GET", POLL)[1].splitlines(), ["openmenu 1", "LAUNCH MK51035", "NET dcnow", "DCNET off inactive"])
        self.assertEqual(self.call("GET", POLL)[1].splitlines(), ["openmenu 1", "NET dcnow", "DCNET off inactive"])

    def test_old_launch_dropped(self):
        self.upload()
        self.call("GET", POLL)
        self.launch("MK51035")
        om._state["pending_time"] -= om.LAUNCH_TTL + 1
        self.assertNotIn("LAUNCH", self.call("GET", POLL)[1])

    def test_launch_from_another_site_refused(self):
        self.assertEqual(self.launch("MK51035", {"Origin": "http://evil.example"})[0], 403)

    # ---- what the box shows (layout.json binds to these)
    def test_the_title_follows_the_dreamcast(self):
        self.assertEqual(self.view()["title"], "Not seen yet")
        self.assertIn("No game list yet", self.view()["note"])
        self.upload()
        self.call("GET", POLL)
        v = self.view()
        self.assertEqual((v["title"], v["connected"], v["note"], v["count"], v["hash"]), ("Connected", True, "3 games on the card", 3, "abc12345"))
        om._state["seen"] -= om.SEEN_WINDOW + 1
        v = self.view()
        self.assertEqual((v["title"], v["connected"]), ("Not connected", False))

    def test_a_queued_and_a_started_game_are_named(self):
        self.upload()
        self.call("GET", POLL)
        self.launch("MK51035")
        v = self.view()
        self.assertEqual((v["note"], v["busy"]), ("Waiting for the Dreamcast to start Crazy Taxi...", True))
        self.call("GET", POLL)
        v = self.view()
        self.assertEqual((v["note"], v["busy"]), ("Starting Crazy Taxi on the Dreamcast.", False))

    def test_the_page_can_tell_when_the_list_changed_by_its_hash(self):
        self.upload()
        first = self.view()["hash"]
        self.call("POST", "/openmenu/games", UPLOAD.replace("abc12345", "def67890").encode(), {"X-Requested-With": "openMenu"})
        self.assertNotEqual(self.view()["hash"], first)


class LiveInfo(Base):
    """What goes back to the Dreamcast (NET, PLY) and which games are announced as online."""
    UPLOAD2 = ("#openmenu-games 1 abc12345 4\n"
               "T1234N\t1\t1/1\tU\tgame01\tSonic Adventure 2 (USA)\n"
               "MK51035\t2\t1/2\tU\tgame02\tCrazy Taxi\n"
               "T9999N\t3\t1/1\tU\tgame03\tQuake III Arena\n"
               "HDR-0001\t4\t1/1\tJ\tRacing games\tDeath Crimson 2\n")

    def players_file(self, players, games=None, age=0):
        with open(core.PLAYERS_CACHE, "w") as f:
            json.dump({"time": int(time.time()) - age, "players": players,
                       "games": [{"name": "Sonic Adventure 2", "status": "online"}, {"name": "Quake III Arena", "status": "wip"},
                                 {"name": "Death Crimson 2", "status": "offline"}] if games is None else games}, f)

    def upload2(self):
        self.call("POST", "/openmenu/games", self.UPLOAD2.encode(), {"X-Requested-With": "openMenu"})

    def poll_lines(self):
        return self.call("GET", POLL)[1].splitlines()

    def test_the_selected_network_goes_back_to_the_dreamcast(self):
        from unittest import mock
        self.upload2()
        self.assertIn("NET dcnow", self.poll_lines())
        with mock.patch.object(core, "tag", return_value="DCNET"):               # DCNET is selected and DreamPi can use it
            self.assertIn("NET dcnet", self.poll_lines())
        with mock.patch.object(core, "tag", return_value="DCNET_OFF"):           # selected, but calls go to DCNow! anyway
            self.assertIn("NET dcnow", self.poll_lines())

    def test_the_slots_of_the_games_played_online_go_back(self):
        self.upload2()
        self.players_file([{"player": "Dave", "game": "Crazy Taxi", "network": "DCNow!"}, {"player": "Eve", "game": "Quake III Arena", "network": "DCNET"},
                           {"player": "Fay", "game": "Quake III Arena", "network": "DCNow!"}, {"player": "Gus", "game": "Not On The Card", "network": "DCNow!"},
                           {"player": "Idle", "game": "", "network": "DCNow!"}])
        lines = self.poll_lines()
        self.assertIn("PLY 3 2", lines)                             # the slots, the most played game first; unknown and idle ones are left out
        self.players_file([])
        self.assertFalse([l for l in self.poll_lines() if l.startswith("PLY")])     # nobody: no line

    def test_a_game_without_a_slot_is_left_out(self):
        self.call("POST", "/openmenu/games", self.UPLOAD2.replace("T9999N\t3", "T9999N\tx").encode(), {"X-Requested-With": "openMenu"})
        self.players_file([{"player": "Eve", "game": "Quake III Arena", "network": "DCNET"}, {"player": "Dave", "game": "Crazy Taxi", "network": "DCNow!"}])
        self.assertIn("PLY 2", self.poll_lines())

    def test_the_dcnet_line_says_why_dcnet_does_not_work(self):
        from unittest import mock
        self.upload2()
        with mock.patch.object(core, "hook_problem", return_value=None):
            for code, line in ((None, "DCNET ok"), ("config", "DCNET off config"), ("disabled", "DCNET off disabled"), ("noupdates", "DCNET off noupdates")):
                with mock.patch.object(core, "_dcnet_check", return_value=(code, "why" if code else None)):
                    self.assertIn(line, self.poll_lines())
        self.assertIn("DCNET off inactive", self.poll_lines())             # DreamPi is not running the add-on

    def test_the_event_line_is_the_one_due_else_the_soonest(self):
        self.upload2()
        now = int(time.time())

        def reminders(items, upcoming):
            with open(core.EVENT_REMINDERS, "w") as f:
                json.dump({"lead": 15, "after": 10, "items": items, "upcoming": upcoming, "dismissed": [], "written": now}, f)
        reminders([], [])
        self.assertFalse([l for l in self.poll_lines() if l.startswith("EVENT")])
        soon = {"id": "1", "title": "Game\nNight  UK", "start": now + 3600}
        reminders([], [soon])
        self.assertIn("EVENT %d 0 Game Night UK" % (now + 3600), self.poll_lines())                  # the soonest, one line, no reminder due
        due = {"id": "2", "title": "Power Smash", "start": now + 300}
        reminders([due], [due, soon])
        self.assertIn("EVENT %d 1 Power Smash" % (now + 300), self.poll_lines())                     # a reminder is due: that one, flagged
        reminders([], [{"id": "3", "title": "Over", "start": now - 3600}])
        self.assertFalse([l for l in self.poll_lines() if l.startswith("EVENT")])                    # it is over
        reminders([], [soon])
        core.save_module_enabled("events", False)
        self.assertFalse([l for l in self.poll_lines() if l.startswith("EVENT")])                    # the events module is off

    def test_an_old_players_list_says_nobody_plays(self):
        self.upload2()
        self.players_file([{"player": "Dave", "game": "Crazy Taxi", "network": "DCNow!"}], age=om.PLAYERS_FRESH + 5)
        self.assertFalse([l for l in self.poll_lines() if l.startswith("PLY")])

    def test_only_games_in_the_online_table_are_announced_as_online(self):
        self.upload2()
        self.players_file([])
        got = json.loads(self.call("GET", "/openmenu/games")[1])
        self.assertTrue(got["filtered"])
        self.assertEqual(dict((g["name"], g["online"]) for g in got["games"]),
                         {"Sonic Adventure 2 (USA)": True, "Crazy Taxi": False, "Quake III Arena": True, "Death Crimson 2": False})      # work in progress counts, offline does not

    def test_without_a_table_every_game_counts(self):
        self.upload2()
        self.assertFalse(json.loads(self.call("GET", "/openmenu/games")[1])["filtered"])               # no players file at all
        self.players_file([], games=[])
        got = json.loads(self.call("GET", "/openmenu/games")[1])
        self.assertTrue(not got["filtered"] and all(g["online"] for g in got["games"]))
        self.players_file([])
        core.save_module_enabled("players", False)                                                    # the module that knows the table is off
        got = json.loads(self.call("GET", "/openmenu/games")[1])
        self.assertTrue(not got["filtered"] and all(g["online"] for g in got["games"]))

    def test_a_polling_dreamcast_asks_for_a_new_players_list_when_it_is_old(self):
        self.upload2()
        self.players_file([], age=om.PLAYERS_ASK + 10)
        self.assertIsNone(core.poke_stamp("players"))
        self.poll_lines()
        first = core.poke_stamp("players")
        self.assertIsNotNone(first)
        self.poll_lines()
        self.assertEqual(core.poke_stamp("players"), first)                     # not on every poll
        om._state["asked"] -= om.PLAYERS_ASK_EVERY + 1
        self.players_file([], age=1)
        self.poll_lines()
        self.assertEqual(core.poke_stamp("players"), first)                     # a fresh list: nothing to ask for

    def test_the_module_announces_a_launcher_and_the_page_gets_it(self):
        import netswitch_modules as mods
        lay = mods.layout()
        self.assertEqual(lay["launcher"], {"mod": "openmenu", "title": "openMenu", "state": "openmenu", "games": "om_games", "start": "/openmenu/launch"})
        self.assertIn("om_games", lay["data"])
        core.save_module_enabled("openmenu", False)
        web.refresh_page(force=True)
        self.assertNotIn("launcher", mods.layout())                              # off: no launcher, no buttons anywhere


if __name__ == "__main__":
    unittest.main()
