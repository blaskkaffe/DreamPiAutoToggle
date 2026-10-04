"""The optional online-players list: tolerant parsing of status JSON, the cache
and the HTTP endpoint (no network: fetch is faked)."""
import json
import os
import threading
import unittest
from urllib.error import HTTPError
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
        self.assertEqual([c for c in calls if "dc99.test" in c], ["https://dc99.test/p", "http://dc99.test/p"])
        src = [x for x in pl.status()["sources"] if x["name"] == "DC99"][0]
        self.assertTrue(src["ok"])
        self.assertEqual(len(src["sections"]), 2)

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
            self.assertIn('"url": "/players", "every": 60', html)         # the layout's data source: asked at most once a minute
            self.assertNotIn("netswitch-players", html)        # no show/hide setting: always shown while the module is on
            self.assertIn("Online players:", html)
            self.assertIn('"@players.games"', html)
            self.assertIn('"@players.list"', html)
            r = json.loads(urlopen(base + "/players", timeout=10).read().decode())
            self.assertTrue(r["configured"])
            self.assertIn("links", r)
            for key in ("parts", "games", "list", "status", "retry"):          # what the widgets bind to
                self.assertIn(key, r)
        finally:
            pl.fetch = saved_fetch
            srv.shutdown()
            srv.server_close()
            cleanup(tmp)

    def test_switched_off_the_page_and_endpoint_are_gone(self):
        tmp = sandbox()
        srv = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        try:
            core.save_module_enabled("players", False)
            html = urlopen(base + "/", timeout=10).read().decode()
            self.assertNotIn("pl-box", html)
            with self.assertRaises(HTTPError) as cm:
                urlopen(base + "/players", timeout=10)
            self.assertEqual(cm.exception.code, 404)
        finally:
            srv.shutdown()
            srv.server_close()
            cleanup(tmp)
            web.refresh_page(force=True)


if __name__ == "__main__":
    unittest.main()


class FavoritesTests(unittest.TestCase):
    GAMES = [{"name": "Phantasy Star Online", "status": "green"}, {"name": "Quake III Arena", "status": "work in progress"},
             {"title": "Dead Game", "colour": "red"}, {"name": "Mystery"}]

    def setUp(self):
        self.tmp = sandbox()
        self._fetch = pl.fetch
        pl._cache.update({"time": 0, "refreshing": False, "players": [], "sources": [], "games": [], "games_time": 0, "games_live": False, "restored": False})
        pl._disk["tried"] = True

    def tearDown(self):
        pl.fetch = self._fetch
        cleanup(self.tmp)

    def test_game_status_words(self):
        for text, want in (("green", "online"), ("Fully online", "online"), (True, "online"), ("WIP", "wip"), ("Work in progress", "wip"),
                           ("yellow", "wip"), ("red", "offline"), ("Not online", "offline"), (False, "offline"), ("", "unknown"), ("?", "unknown")):
            self.assertEqual(pl.game_status(text), want, text)

    def test_parse_games_shapes(self):
        got = dict((g["name"], g["status"]) for g in pl.parse_games({"games": self.GAMES}))
        self.assertEqual(got, {"Phantasy Star Online": "online", "Quake III Arena": "wip", "Dead Game": "offline", "Mystery": "unknown"})
        self.assertEqual(pl.parse_games({"Sonic": "green", "Dee Dee": "wip"}),
                         [{"name": "Sonic", "status": "online"}, {"name": "Dee Dee", "status": "wip"}])
        for bad in (None, 5, "x", {}, [], [1, None]):
            self.assertEqual(pl.parse_games(bad), [])

    def test_favorites_are_cleaned_and_saved(self):
        got = pl.save_favorites({"games": [" Sonic  Adventure ", "sonic adventure", "", 5], "players": ["Ana", "ana", "Bo"]})
        self.assertEqual(got, {"games": ["Sonic Adventure", "5"], "players": ["Ana", "Bo"]})
        self.assertEqual(pl.favorites(), got)
        self.assertEqual(pl.favorites.__name__, "favorites")

    def test_missing_or_broken_file_means_no_favorites(self):
        self.assertEqual(pl.favorites(), {"games": [], "players": []})
        with open(core.PLAYERS_FAVORITES, "w") as f:
            f.write("{broken")
        self.assertEqual(pl.favorites(), {"games": [], "players": []})

    def test_watch_matches_games_and_players(self):
        online = [{"player": "Ana", "game": "Phantasy Star Online Ver.2", "network": "DCNET"}, {"player": "Bo", "game": "", "network": "DCNow!"}]
        favs = {"games": ["Phantasy Star Online", "Quake III Arena"], "players": ["ANA", "Cy"]}
        self.assertEqual(pl.watch_result(online, favs), {"games": ["Phantasy Star Online"], "friends": ["ANA"]})
        self.assertFalse(pl.same_game("Sonic", "Sonic Adventure 2"))      # too short to count as "inside"

    def test_refresh_writes_the_watch_file_the_leds_read(self):
        pl.save_favorites({"games": ["Phantasy Star Online"], "players": ["Ana"]})
        self.assertEqual(core.players_watch(), {"games": [], "friends": []})     # nothing loaded yet
        pl.fetch = lambda url: json.dumps(self.GAMES if "dreamcastlive" in url else DC99)
        pl.refresh()
        self.assertEqual(core.players_watch(), {"games": ["Phantasy Star Online"], "friends": ["Ana"]})
        pl.save_favorites({"games": ["Quake III Arena"], "players": []})
        self.assertEqual(core.players_watch(), {"games": [], "friends": []})

    def test_stale_watch_file_is_ignored(self):
        with open(core.PLAYERS_WATCH, "w") as f:
            json.dump({"time": 1, "games": ["x"], "friends": ["y"]}, f)
        self.assertEqual(core.players_watch(), {"games": [], "friends": []})

    def test_choices_mark_what_is_not_fully_online(self):
        pl._cache.update({"time": 1, "games": pl.parse_games(self.GAMES),
                          "players": [{"player": "Ana", "game": "Outtrigger", "network": "DCNET"}]})
        by = dict((c["value"], c) for c in pl.game_choices())
        self.assertFalse(by["Phantasy Star Online"]["disabled"])
        self.assertEqual(by["Phantasy Star Online"]["sub"], "")
        self.assertFalse(by["Quake III Arena"]["disabled"])
        self.assertEqual(by["Quake III Arena"]["sub"], "work in progress")
        self.assertTrue(by["Dead Game"]["disabled"])
        self.assertEqual(by["Outtrigger"]["sub"], "playing now")
        order = [c["value"] for c in pl.game_choices()]
        self.assertTrue(order.index("Phantasy Star Online") < order.index("Quake III Arena") < order.index("Dead Game"))

    def test_games_played_now_come_first_and_are_marked_for_the_picker(self):
        pl._cache.update({"time": 1, "games": pl.parse_games(self.GAMES),
                          "players": [{"player": "Ana", "game": "Quake III Arena", "network": "DCNET"},
                                      {"player": "Bo", "game": "Outtrigger", "network": "DCNow!"}]})
        choices = pl.game_choices()
        self.assertEqual([c["value"] for c in choices if c["now"]], ["Outtrigger", "Quake III Arena"])
        self.assertEqual([c["value"] for c in choices[:2]], ["Outtrigger", "Quake III Arena"])
        by = dict((c["value"], c) for c in choices)
        self.assertEqual(by["Quake III Arena"]["sub"], "work in progress \u00b7 playing now")
        self.assertFalse(by["Phantasy Star Online"]["now"])
        group = pl._favorites_reply()["groups"][0]
        self.assertTrue(group["initial"])
        self.assertEqual(group["notes"]["Quake III Arena"], "work in progress")

    def test_http_round_trip(self):
        web.start_background = getattr(web, "start_background", None)
        pl._cache.update({"time": 1, "games": pl.parse_games(self.GAMES), "players": []})
        class H(object):
            sent = None
            def send(self, body, ctype, status=200):
                self.sent = (json.loads(body) if ctype == "application/json" else body, status)
            def _body(self, limit):
                return json.dumps({"games": ["Quake III Arena"], "players": ["Ana"]}).encode()
        h = H()
        pl._post_favorites(h)
        groups = dict((g["key"], g) for g in h.sent[0]["groups"])
        self.assertEqual(groups["games"]["items"], ["Quake III Arena"])
        self.assertEqual(groups["games"]["notes"], {"Quake III Arena": "work in progress", "Dead Game": "not online yet"})
        self.assertEqual(groups["players"]["items"], ["Ana"])
        self.assertTrue(groups["players"]["free"] and not groups["games"]["free"])

    def test_stars_set_and_clear_the_same_favorites_as_settings(self):
        self.assertTrue(pl.star("player", "Ana", True))
        self.assertTrue(pl.star("game", "Quake III Arena", True))
        self.assertEqual(pl.favorites(), {"games": ["Quake III Arena"], "players": ["Ana"]})
        self.assertTrue(pl.star("player", " ana ", True))                      # already a favorite (same name, any case): no second one
        self.assertEqual(pl.favorites()["players"], ["Ana"])
        self.assertTrue(pl.star("player", "ANA", False))
        self.assertTrue(pl.star("game", "Quake III Arena Online", False))      # the same game by its other name (same_game)
        self.assertEqual(pl.favorites(), {"games": [], "players": []})
        self.assertFalse(pl.star("team", "x", True))                           # not a kind
        self.assertFalse(pl.star("player", "  ", True))
        for i in range(pl.MAX_FAVORITES):
            pl.star("player", "P%d" % i, True)
        self.assertFalse(pl.star("player", "One too many", True))             # a full list says no

    def test_the_view_has_the_games_list_and_what_is_starred(self):
        pl._cache.update({"time": 5, "players": [{"player": "Ana", "game": "Quake III Arena", "network": "DCNow!"},
                                                 {"player": "Bo", "game": "Quake III Arena", "network": "DCNow!"},
                                                 {"player": "Cy", "game": "", "network": "DCNET"}]})
        pl.star("player", "Bo", True)
        pl.star("game", "Quake III Arena", True)
        v = pl.view()
        self.assertEqual([(x["title"], x["starred"]) for x in v["list"]], [("Ana", False), ("Bo", True), ("Cy", False)])
        self.assertEqual(v["games_list"], [{"title": "Quake III Arena", "sub": "2 playing", "starred": True}])

    def test_the_star_endpoint_answers_with_the_new_view(self):
        pl._cache.update({"time": 5, "players": [{"player": "Ana", "game": "", "network": "DCNow!"}]})
        class H(object):
            body = {"kind": "player", "name": "Ana", "on": True}
            def send(self, body, ctype, status=200):
                self.sent = (json.loads(body) if ctype == "application/json" else body, status)
            def _body(self, limit):
                return json.dumps(self.body).encode()
        h = H()
        pl._post_star(h)
        self.assertEqual((h.sent[1], h.sent[0]["list"][0]["starred"]), (200, True))
        h.body = {"kind": "nope", "name": "Ana", "on": True}
        pl._post_star(h)
        self.assertEqual(h.sent[1], 400)

    def test_the_status_is_about_the_player_feeds_not_the_game_list(self):
        pl._cache.update({"time": 5, "players": [], "sources": [{"name": "Dreamcast Live", "ok": False, "count": 0, "error": "no games found", "kind": "games"},
                                                                  {"name": "DC99", "ok": True, "count": 0, "error": None, "sections": []}]})
        self.assertNotIn("Dreamcast Live", pl.view()["status"])
        self.assertNotIn("DreamPi on GitHub", [x[0] for x in pl.LINKS])

    def test_the_list_on_the_page_stays_when_no_feed_answers(self):
        pl.fetch = lambda url: json.dumps(self.GAMES if "dreamcastlive" in url else DC99)
        pl.refresh()
        before = list(pl.status()["players"])
        self.assertTrue(before)
        def broken(url):
            raise IOError("offline")
        pl.fetch = broken
        pl.refresh()
        got = pl.status()
        self.assertEqual(got["players"], before)                                # not replaced by an empty list
        self.assertFalse(got["refreshing"])
        self.assertTrue(any(not x["ok"] for x in got["sources"]))               # the report says what went wrong

    def test_the_last_list_is_kept_on_disk_and_shown_again_after_a_restart(self):
        pl.fetch = lambda url: json.dumps(self.GAMES if "dreamcastlive" in url else DC99)
        pl.refresh()
        before = list(pl.status()["players"])
        self.assertTrue(before)
        self.assertTrue(os.path.exists(core.PLAYERS_CACHE))
        pl._cache.update({"time": 0, "players": [], "sources": [], "games": [], "restored": False})      # what a restarted service has
        pl._disk["tried"] = False
        pl.fetch = lambda url: (_ for _ in ()).throw(IOError("slow"))                                      # and the feeds are not answering yet
        pl._cache["refreshing"] = True                                                                     # (a refresh is running, so status() starts none)
        got = pl.view()
        self.assertEqual(got["players"], before)                                                           # the old list is there at once ...
        self.assertTrue(got["restored"] and got["list"] and got["busy"])                                   # ... and the rows say they are being refreshed
        pl.save_favorites({"games": [], "players": [before[0]["player"]]})
        self.assertEqual(core.players_watch(), {"games": [], "friends": []})                               # a list from disk does not light the LEDs

    def test_nothing_is_said_about_a_list_that_is_not_known_yet(self):
        pl._cache.update({"time": 0, "refreshing": True, "players": [], "sources": []})
        pl._disk["tried"] = True
        v = pl.view()
        self.assertEqual((v["list"], v["games_list"], v["games"]), (None, None, ["Loading..."]))          # null, not []: the page shows no "Nobody is online" yet

    def test_remove_all_asks_first(self):
        self.assertTrue(pl._favorites_reply()["rules"]["restore_confirm"])


def _row(name, icon, link=True):
    cell = '<a href="https://dreamcastlive.net/x/">%s</a>' % name if link else name
    return ('<tr><td class="c"><img src="https://dreamcastlive.net/wp-content/uploads/a-cover.jpg" alt=""></td><td>%s</td>'
            '<td>4</td><td>Modem</td><td>Multiplayer</td><td><img src="https://dreamcastlive.net/wp-content/uploads/us-flag-rnd.png" alt=""></td>'
            '<td class="c"><img src="https://dreamcastlive.net/wp-content/uploads/2023/03/%s.png" alt=""></td><td>N/A</td></tr>' % (cell, icon))


HTML = ('<table><thead><tr><th>Game</th><th></th><th>Players</th><th>Status</th></tr></thead><tbody>'
        + _row("4&times;4 Evolution", "online-icon") + _row("Capcom &amp; Psikyo All Stars", "wip-icon-v2", False)
        + _row("Gundam Battle Online", "offline-icon") + _row("JoJo\u2019s Matching Service", "wip-icon-v2") + '</tbody></table>')


class GameTableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        self._fetch = pl.fetch
        pl._cache.update({"time": 0, "refreshing": False, "players": [], "sources": [], "games": [], "games_time": 0, "games_live": False})

    def tearDown(self):
        pl.fetch = self._fetch
        cleanup(self.tmp)

    def test_the_html_table_gives_names_and_status_from_the_icon(self):
        got = [(g["name"], g["status"]) for g in pl.parse_games_html(HTML)]
        self.assertEqual(got, [("4\u00d74 Evolution", "online"), ("Capcom & Psikyo All Stars", "wip"),
                               ("Gundam Battle Online", "offline"), ("JoJo\u2019s Matching Service", "wip")])

    def test_text_is_json_or_html(self):
        self.assertEqual(pl.parse_games_text('{"Sonic": "green"}'), [{"name": "Sonic", "status": "online"}])
        self.assertEqual(len(pl.parse_games_text(HTML)), 4)
        self.assertEqual(pl.parse_games_text("<html>nothing</html>"), [])

    def test_the_snapshot_holds_the_whole_list(self):
        games = dict((g["name"], g["status"]) for g in pl.snapshot_games())
        self.assertGreater(len(games), 90)
        self.assertEqual((games["Quake III Arena"], games["QuakeWorld"], games["Net Versus: Chess"]), ("online", "wip", "offline"))

    def test_the_addresses_are_tried_in_turn(self):
        calls = []
        def fetch(url):
            calls.append(url)
            if url.endswith("/online-games/"):
                return HTML
            raise IOError("404")
        pl.fetch = fetch
        pl.refresh()
        self.assertEqual(len(pl._cache["games"]), 4)
        self.assertTrue(pl._cache["games_live"])
        self.assertIn("https://dreamcastlive.net/online-games/", calls)
        before = len(calls)
        pl.refresh()                                                  # the list is kept for hours: not fetched again
        self.assertEqual([c for c in calls[before:] if "dreamcastlive" in c], [])

    def test_when_nothing_can_be_read_the_snapshot_fills_the_picker(self):
        def fetch(url):
            raise IOError("blocked")
        pl.fetch = fetch
        pl.refresh()
        self.assertFalse(pl._cache["games_live"])
        self.assertGreater(len(pl._cache["games"]), 90)
        by = dict((c["value"], c) for c in pl.game_choices())
        self.assertFalse(by["Quake III Arena"]["disabled"])
        self.assertTrue(by["Net Versus: Chess"]["disabled"])
        self.assertEqual(by["QuakeWorld"]["sub"], "work in progress")
