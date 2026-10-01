"""The optional online-players list: tolerant parsing of status JSON, the cache
and the HTTP endpoint (no network: fetch is faked)."""
import json
import os
import threading
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


DC99 = {"generated": 1790000000,
        "dreampi": {"users": [
            {"username": "Ana", "country": "SE", "current_game_display": "Phantasy Star Online", "current_game": "PSO", "online": True, "history": [{"x": 1}]},
            {"username": "Offline Olle", "country": "NO", "current_game_display": "Quake III", "online": False},
            {"username": "Idle Ida", "country": "US", "current_game_display": "", "online": True}]},
        "dcnet": {"online": True, "error": None, "games": [{"id": "x"}], "users": [],
                  "players": [{"name": "Bo", "gameId": "G1", "gameName": "Outtrigger", "geoloc": {"country": "DE", "lat": 1}}]}}


class ShapeTests(unittest.TestCase):
    """The shapes openMenu's working player list reads (checked there against live responses)."""
    def test_dc99_combined_feed(self):
        got = pl.parse_players(DC99)
        self.assertEqual([(p["player"], p["game"], p["network"], p["country"]) for p in got],
                         [("Ana", "Phantasy Star Online", "DCNow!", "SE"), ("Idle Ida", "", "DCNow!", "US"),
                          ("Bo", "Outtrigger", "DCNET", "DE")])

    def test_dcnet_offline_adds_nobody_but_dreampi_still_counts(self):
        data = json.loads(json.dumps(DC99))
        data["dcnet"]["online"] = False
        self.assertEqual([p["network"] for p in pl.parse_players(data)], ["DCNow!", "DCNow!"])

    def test_missing_sections_are_fine(self):
        self.assertEqual(len(pl.parse_players({"dcnet": {"players": [{"name": "Bo", "gameName": "G"}]}})), 1)
        self.assertEqual(pl.parse_players({"dreampi": {}}), [])

    def test_any_network_section_is_read_kosnet_included(self):
        data = json.loads(json.dumps(DC99))
        data["kosnet"] = {"online": True, "players": [{"name": "Kay", "gameName": "Some KOS Game", "geoloc": {"country": "JP"}}]}
        got = pl.parse_players(data)
        self.assertIn(("Kay", "Some KOS Game", "KOSnet", "JP"), [(p["player"], p["game"], p["network"], p["country"]) for p in got])
        self.assertEqual(len(got), 4)

    def test_section_info_says_what_each_section_listed(self):
        players, info = pl.parse_players_info(DC99)
        by = dict((i["section"], i) for i in info)
        self.assertEqual((by["dreampi"]["listed"], by["dreampi"]["shown"]), (3, 2))      # one is offline
        self.assertEqual((by["dcnet"]["listed"], by["dcnet"]["shown"]), (1, 1))
        self.assertEqual(len(players), 3)

    def test_users_without_an_online_field_count_as_online_in_a_section(self):
        got = pl.parse_players({"dreampi": {"users": [{"username": "A", "current_game_display": "G"}]}})
        self.assertEqual([(p["player"], p["network"]) for p in got], [("A", "DCNow!")])

    def test_dreamcast_online_feed(self):
        got = pl.parse_players({"users": [{"username": "Cy", "country": "GB", "current_game_display": "Toy Racer", "online": True},
                                          {"username": "Gone", "online": False}]})
        self.assertEqual([(p["player"], p["game"], p["network"]) for p in got], [("Cy", "Toy Racer", "DCNow!")])


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

    def test_defaults_are_the_two_feeds_openmenu_uses(self):
        self.assertEqual([(s["name"], s["url"]) for s in pl.sources()],
                         [("DC99", "https://dc99.net/online/dcnet_status.php"),
                          ("Dreamcast.online", "https://dreamcast.online/now/api/users.json")])

    def test_https_failure_falls_back_to_http(self):
        self.write_sources([{"name": "DC99", "url": "https://dc99.test/p"}])
        calls = []
        def fetch(url):
            calls.append(url)
            if url.startswith("https://"):
                raise IOError("tls")
            return json.dumps(DC99)
        pl.fetch = fetch
        pl.refresh()
        self.assertEqual(calls, ["https://dc99.test/p", "http://dc99.test/p"])
        self.assertTrue(pl.status()["sources"][0]["ok"])
        self.assertEqual(len(pl.status()["sources"][0]["sections"]), 2)

    def test_an_empty_file_switches_the_list_off(self):
        self.write_sources([])
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

    def test_two_sources_do_not_list_a_player_twice(self):
        self.write_sources([{"name": "DC99", "url": "https://a.test/p"}, {"name": "DCO", "url": "https://b.test/p"}])
        pl.fetch = lambda url: json.dumps(DC99) if "a.test" in url else json.dumps(
            {"users": [{"username": "ana", "current_game_display": "x", "online": True}]})
        pl.refresh()
        self.assertEqual(sorted(p["player"] for p in pl.status()["players"]), ["Ana", "Bo", "Idle Ida"])

    def test_a_duplicate_fills_in_what_the_first_copy_lacks(self):
        self.write_sources([{"name": "A", "url": "https://a.test/p"}, {"name": "B", "url": "https://b.test/p"}])
        pl.fetch = lambda url: json.dumps({"users": [{"username": "Zed", "current_game_display": "" if "a.test" in url else "Sonic", "online": True}]})
        pl.refresh()
        players = pl.status()["players"]
        self.assertEqual([(p["player"], p["game"]) for p in players], [("Zed", "Sonic")])

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
        saved_fetch, pl.fetch = pl.fetch, lambda url: json.dumps(DC99)
        pl._cache.update({"time": 0, "refreshing": False, "players": [], "sources": []})
        try:
            html = urlopen(base + "/", timeout=10).read().decode()
            self.assertIn('<script src="/players.js" defer></script>', html)
            js = urlopen(base + "/players.js", timeout=10).read().decode()
            self.assertIn("/players", js)
            self.assertIn("60000", js)                       # polls at most once a minute
            self.assertIn("netswitch-players", js)           # show/hide setting, per browser
            self.assertIn('id="pl-b"', js)
            self.assertIn("pl-toggle", js)
            r = json.loads(urlopen(base + "/players", timeout=10).read().decode())
            self.assertTrue(r["configured"])
            self.assertIn("links", r)
        finally:
            pl.fetch = saved_fetch
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
