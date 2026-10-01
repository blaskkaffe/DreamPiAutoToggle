"""The optional online-players list: tolerant parsing of status JSON, the cache
and the HTTP endpoint (no network: fetch is faked)."""
import json
import os
import threading
import time
import unittest
from urllib.request import urlopen

from support import core, web, sandbox, cleanup
import netswitch_players as pl


class ParseTests(unittest.TestCase):
    def test_list_of_player_objects(self):
        got = pl.parse_players([{"name": "Ana", "game": "Phantasy Star Online", "network": "dcnet"},
                                {"username": "Bob", "title": "Quake III", "service": "DreamPi"},
                                {"nothing": "here"}], "")
        self.assertEqual([(p["player"], p["game"], p["network"]) for p in got],
                         [("Ana", "Phantasy Star Online", "DCNET"), ("Bob", "Quake III", "DCNow!")])

    def test_object_with_a_players_list(self):
        got = pl.parse_players({"updated": 1, "players": [{"player": "Cy", "game": {"name": "Toy Racer"}}]}, "DCNow!")
        self.assertEqual((got[0]["player"], got[0]["game"], got[0]["network"]), ("Cy", "Toy Racer", "DCNow!"))

    def test_games_that_list_their_players(self):
        got = pl.parse_players({"games": [{"name": "Outtrigger", "players": ["Di", {"name": "Ed"}]},
                                          {"name": "Empty", "players": []}]}, "DCNET")
        self.assertEqual([(p["player"], p["game"], p["network"]) for p in got],
                         [("Di", "Outtrigger", "DCNET"), ("Ed", "Outtrigger", "DCNET")])

    def test_game_to_players_mapping(self):
        got = pl.parse_players({"Chu Chu Rocket": ["Flo", "Gus"], "Sonic Adventure 2": ["Hal"]}, "DCNow!")
        self.assertEqual(sorted((p["player"], p["game"]) for p in got),
                         [("Flo", "Chu Chu Rocket"), ("Gus", "Chu Chu Rocket"), ("Hal", "Sonic Adventure 2")])

    def test_unknown_shapes_are_empty_not_errors(self):
        for data in (None, 5, "text", {}, [], {"a": 1}, [1, 2, None], {"players": "none"}):
            self.assertEqual(pl.parse_players(data), [])

    def test_network_labels(self):
        self.assertEqual(pl.network_label("Flycast DCNet"), "DCNET")
        self.assertEqual(pl.network_label("DCNow"), "DCNow!")
        self.assertEqual(pl.network_label("", "DCNET"), "DCNET")
        self.assertEqual(pl.network_label("Other"), "Other")

    def test_long_values_are_cut(self):
        p = pl.parse_players([{"name": "x" * 200, "game": "g" * 200}])[0]
        self.assertTrue(len(p["player"]) <= 40 and len(p["game"]) <= 60)


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        self._fetch = pl.fetch
        pl._cache.update({"time": 0, "refreshing": False, "players": [], "sources": []})

    def tearDown(self):
        pl.fetch = self._fetch
        cleanup(self.tmp)

    def write_sources(self, data):
        with open(core.PLAYERS_SOURCES, "w") as f:
            json.dump(data, f)

    def test_not_configured_by_default(self):
        self.assertEqual(pl.sources(), [])
        self.assertFalse(pl.status()["configured"])

    def test_only_http_urls_count(self):
        self.write_sources([{"name": "a", "url": "file:///etc/passwd"}, {"name": "b", "url": "https://x.test/p.json"}, "junk"])
        self.assertEqual([s["name"] for s in pl.sources()], ["b"])

    def test_refresh_merges_sorts_and_reports_each_source(self):
        self.write_sources([{"name": "One", "url": "https://one.test/p", "network": "DCNET"},
                            {"name": "Two", "url": "https://two.test/p"},
                            {"name": "Down", "url": "https://down.test/p"}])
        def fetch(url):
            if "down" in url:
                raise IOError("HTTP 503")
            if "one" in url:
                return json.dumps([{"name": "Zed", "game": "B Game"}, {"name": "Amy", "game": "A Game"}])
            return json.dumps({"players": [{"name": "Kim", "game": "C Game", "network": "dcnow"}]})
        pl.fetch = fetch
        pl.refresh()
        st = pl.status()
        self.assertEqual([(p["network"], p["player"]) for p in st["players"]], [("DCNow!", "Kim"), ("DCNET", "Amy"), ("DCNET", "Zed")])
        by = dict((s["name"], s) for s in st["sources"])
        self.assertEqual((by["One"]["ok"], by["One"]["count"]), (True, 2))
        self.assertFalse(by["Down"]["ok"])
        self.assertIn("503", by["Down"]["error"])
        self.assertTrue(st["configured"])
        self.assertTrue(any(l[0] == "DC99" for l in st["links"]))

    def test_bad_json_is_reported_as_an_error(self):
        self.write_sources([{"name": "Bad", "url": "https://bad.test/p"}])
        pl.fetch = lambda url: "<html>not json</html>"
        pl.refresh()
        self.assertFalse(pl.status()["sources"][0]["ok"])


class IntegrationTests(unittest.TestCase):
    def test_page_and_endpoints(self):
        tmp = sandbox()
        srv = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        try:
            html = urlopen(base + "/", timeout=10).read().decode()
            self.assertIn('<script src="/players.js" defer></script>', html)
            js = urlopen(base + "/players.js", timeout=10).read().decode()
            self.assertIn("/players", js)
            r = json.loads(urlopen(base + "/players", timeout=10).read().decode())
            self.assertFalse(r["configured"])
            self.assertIn("links", r)
        finally:
            srv.shutdown()
            srv.server_close()
            cleanup(tmp)

    def test_page_builds_without_the_module(self):
        saved = web.players
        web.players = None
        try:
            self.assertNotIn("players.js", web.build_page())
        finally:
            web.players = saved

    def test_page_builds_without_players_js(self):
        import shutil
        tmp = sandbox()
        d = os.path.join(tmp, "page")
        shutil.copytree(web.PAGE_DIR, d, ignore=shutil.ignore_patterns("players.js"))
        saved, web.PAGE_DIR = web.PAGE_DIR, d
        try:
            self.assertNotIn("players", web.build_page())
        finally:
            web.PAGE_DIR = saved
            cleanup(tmp)


if __name__ == "__main__":
    unittest.main()
