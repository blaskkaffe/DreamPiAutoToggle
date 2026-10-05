"""The openMenu link module: openMenu's poll / game upload, the phone page's launch request and the texts the box shows."""
import json
import os
import threading
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


class OpenMenu(unittest.TestCase):
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

    # ---- what openMenu does
    def test_poll_asks_for_games_then_stops(self):
        status, text = self.call("GET", "/openmenu/poll?v=1&n=0&h=00000000")
        self.assertEqual(status, 200)
        self.assertEqual(text.splitlines(), ["openmenu 1", "NEED games"])
        self.assertEqual(self.upload()[0], 200)
        self.assertEqual(self.call("GET", POLL)[1].splitlines(), ["openmenu 1"])
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
        self.assertEqual(self.call("GET", POLL)[1].splitlines(), ["openmenu 1", "LAUNCH MK51035"])
        self.assertEqual(self.call("GET", POLL)[1].splitlines(), ["openmenu 1"])

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


if __name__ == "__main__":
    unittest.main()
