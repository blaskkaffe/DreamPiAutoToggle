"""What the modules hand to the standard widgets: the texts, lists and flags in /api and in the modules' own answers
(layout.json binds to them, so a wrong word here is a wrong word on the page)."""
import json
import os
import time
import unittest

from support import core, sandbox, cleanup
import netswitch_wifi_setup as wf  # noqa: E402
import netswitch_switcher_state as swstate  # noqa: E402
import netswitch_players as pl
import netswitch_wifi_web as wifi
import netswitch_rebootupdate as ru
import netswitch_switcher as sw
import netswitch_switcher_probes as probes
import netswitch_clock as clock
import base_tz as tzmod


class PlayersView(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        self.saved = dict(pl._cache)
        self.saved_fetch = pl.fetch

    def tearDown(self):
        pl._cache.clear()
        pl._cache.update(self.saved)
        pl.fetch = self.saved_fetch
        cleanup(self.tmp)

    def prime(self, players, sources=None, refreshing=False, when=None):
        pl._cache.update({"time": time.time() if when is None else when, "refreshing": refreshing, "players": players, "sources": sources or []})

    def p(self, name, game, net):
        return {"player": name, "game": game, "network": net, "country": "", "source": "x"}

    def test_games_most_played_first_with_counts(self):
        self.assertEqual(pl.games_line([self.p("a", "Quake", "DCNow!"), self.p("b", "Daytona", "DCNow!"), self.p("c", "Daytona", "DCNET"), self.p("d", "", "DCNow!")]),
                         [{"text": "Daytona", "n": 2}, {"text": "Quake", "n": 1}])
        self.assertEqual(pl.games_line([]), [])

    def test_counts_are_per_network_and_follow_the_switcher_colours(self):
        self.prime([self.p("a", "Q", "DCNow!"), self.p("b", "Q", "DCNow!"), self.p("c", "D", "DCNET")], [{"name": "S", "ok": True, "count": 3, "error": None}])
        v = pl.view()
        self.assertEqual(v["parts"], [{"text": "DCNow! 2", "colour": "switcher.dcnow"}, {"text": "DCNET 1", "colour": "switcher.dcnet"}])
        self.assertEqual(v["games"], [{"text": "Q", "n": 2}, {"text": "D", "n": 1}])
        self.assertEqual([(x["title"], x["sub"], x["tag"], x["colour"]) for x in v["list"]][0], ("a", "Q", "DCNow!", "switcher.dcnow"))
        self.assertFalse(v["retry"])

    def test_empty_states_have_a_sentence(self):
        self.prime([], [{"name": "S", "ok": True, "count": 0, "error": None}])
        self.assertEqual(pl.view()["games"], ["Nobody is online"])
        self.prime([self.p("a", "", "DCNow!")], [{"name": "S", "ok": True, "count": 1, "error": None}])
        v = pl.view()
        self.assertEqual(v["games"], ["Nobody is in a game"])
        self.assertEqual(v["list"][0]["sub"], "(Idle)")

    def test_loading_and_refreshing_ask_again_soon(self):
        self.prime([], when=0)
        v = pl.view()
        self.assertEqual(v["games"], ["Loading..."])
        self.assertTrue(v["retry"])
        self.prime([self.p("a", "Q", "DCNow!")], [{"name": "S", "ok": True, "count": 1, "error": None}], refreshing=True)
        self.assertTrue(pl.view()["retry"])

    def test_no_source_says_how_to_add_one(self):
        with open(pl.PLAYERS_SOURCES, "w") as f:
            f.write("[]")
        v = pl.view()
        self.assertEqual(v["games"], ["No player list source is set up"])
        self.assertIn("players_sources.json", v["status"])
        self.assertFalse(v["retry"])

    def test_the_status_line_names_each_source_and_its_errors(self):
        self.prime([self.p("a", "Q", "DCNow!")], [
            {"name": "DC99", "ok": True, "count": 3, "error": None, "sections": [{"section": "dreampi", "shown": 3, "listed": 340, "offline": False}]},
            {"name": "Other", "ok": False, "count": 0, "error": "timed out"}])
        self.assertEqual(pl.view()["status"], "Other: timed out  ·  DC99: dreampi 3/340")


class WifiView(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()

    def tearDown(self):
        cleanup(self.tmp)

    def state(self, state, **extra):
        with open(wf.WIFI_STATE, "w") as f:
            json.dump(dict(extra, state=state, time=time.time()), f)
        d = {}
        wifi.api(d, [])
        return d["wifi"]

    def test_strength_words(self):
        self.assertEqual([wifi.strength(x) for x in (-40, -60, -70, -90, None)], ["Strong", "Good", "Fair", "Weak", ""])

    def test_networks_are_listed_with_what_the_row_says(self):
        got = wifi.networks_list([{"ssid": "Home", "secured": True, "signal": -50}, {"ssid": "Cafe", "secured": False, "signal": None}])
        self.assertEqual([(n["ssid"], n["info"]) for n in got], [("Home", "Secured · Strong"), ("Cafe", "Open")])

    def test_each_state_has_a_button_and_a_sentence(self):
        for st, button in (("idle", "Search"), ("scanning", "Stop"), ("hosting", "Stop"), ("connecting", "Stop"), ("ok", "Connected"), ("failed", "Stop")):
            w = self.state(st, ssid="Home")
            self.assertEqual(w["button"], button, st)
            self.assertTrue(w["sub"], st)
        self.assertIn("“Home”", self.state("connecting", ssid="Home")["sub"])
        self.assertTrue(self.state("ok", ssid="Home")["disabled"])
        self.assertFalse(self.state("idle")["disabled"])

    def test_the_list_shows_only_while_scanning_or_hosting(self):
        nets = [{"ssid": "Home", "secured": True, "signal": -50}]
        self.assertTrue(self.state("hosting", networks=nets)["show_list"])
        self.assertTrue(self.state("scanning", networks=nets)["show_list"])
        self.assertFalse(self.state("idle", networks=nets)["show_list"])
        self.assertEqual(self.state("hosting", networks=nets)["list"][0]["info"], "Secured · Strong")

    def test_demo_mode_says_so(self):
        open(wf.WIFI_DEMO, "w").close()
        w = self.state("hosting")
        self.assertIn("DEMO", w["sub"])
        self.assertTrue(w["sub"].startswith("Pick a network below"))


class UpdateView(unittest.TestCase):
    def base(self, **kw):
        r = {"state": "idle", "checking": False, "time": 1, "error": None, "addon": {"available": False, "current": "v1"}, "dreampi": None,
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

    def test_newer_dreampi_scripts_are_named(self):
        d = {"newer": True, "auto_updates": True, "files": [{"name": "dreampi.py", "current": "1", "latest": "2", "newer": True}, {"name": "netlink.py", "newer": False}]}
        text = ru.view(self.base(dreampi=d))["dreampi_text"]
        self.assertTrue(text.startswith("DreamPi has newer scripts: dreampi.py 1 → 2."))
        self.assertIn("updates itself", text)
        self.assertNotIn("netlink.py", text)
        self.assertEqual(ru.view(self.base())["dreampi_text"], "")

    def test_reboot_confirm_mentions_a_call_in_progress(self):
        tmp = sandbox()
        try:
            d = {}
            ru.api(d, [])
            self.assertNotIn("call", d["reboot"]["confirm"])
            with open(ru.STATE, "w") as f:
                f.write("call dcnow 123")
            ru.api(d, [])
            self.assertIn("A call is in progress", d["reboot"]["confirm"])
        finally:
            cleanup(tmp)


class SwitcherView(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()

    def tearDown(self):
        probes._hangup.update(busy=False, text="")
        cleanup(self.tmp)

    def api(self):
        d, w = {}, []
        sw.api(d, w)
        return d, w

    def test_ago(self):
        self.assertEqual([sw._ago(100, 130), sw._ago(100, 400), sw._ago(100, 7300), sw._ago(0, 5)], ["30s ago", "5 min ago", "2 h ago", ""])

    def test_the_selected_network_and_the_primary_colour(self):
        d, _ = self.api()
        self.assertEqual((d["network"], d["selected"]), ("dcnow", {"id": "dcnow", "title": "DCNow!", "parts": [{"text": "DCNow!", "colour": "switcher.dcnow"}]}))     # parts: the name in its network's colour
        self.assertEqual(d["primary"]["switcher"], "orange")
        open(swstate.FLAG, "w").close()
        d, _ = self.api()
        self.assertEqual((d["network"], d["selected"]["title"], d["primary"]["switcher"]), ("dcnet", "DCNET", "blue"))
        core.set_module_colour("switcher", "dcnet", "bright-cyan")
        self.assertEqual(self.api()[0]["primary"]["switcher"], "bright-cyan")

    def test_hang_up_only_shows_in_a_call_or_while_hanging_up(self):
        self.assertFalse(self.api()[0]["hangup"]["visible"])
        with open(swstate.STATE, "w") as f:
            f.write("call dcnow 123")
        self.assertTrue(self.api()[0]["hangup"]["visible"])
        os.remove(swstate.STATE)
        probes._hangup.update(busy=True, text="")
        h = self.api()[0]["hangup"]
        self.assertTrue(h["visible"] and h["busy"])
        self.assertEqual(h["text"], "hanging up...")

    def test_the_led_modules_dot_look_is_kept(self):
        d = {"dreampi": {"look": {"colour": "purple", "effect": "blink", "speed": "slow"}}}
        sw.api(d, [])
        self.assertEqual(d["dreampi"]["look"]["colour"], "purple")           # the LED module ran first: the switcher does not overwrite it
        self.assertIn("state", d["dreampi"])

    def test_the_pi_row_has_its_lines(self):
        with probes._checks_lock:
            old = dict(probes._checks)
            probes._checks["pi"] = {"state": "ok", "text": "t", "line1": "Pi 3, 40°C", "line2": "up 2 h", "warn": "slowed down"}
        try:
            pi = self.api()[0]["pi"]
            self.assertEqual(pi["lines"], ["Pi 3, 40°C", "up 2 h", "slowed down"])
            with probes._checks_lock:
                probes._checks["pi"] = {"state": "ok", "text": "Fine"}
            self.assertEqual(self.api()[0]["pi"]["lines"], ["Fine"])
        finally:
            with probes._checks_lock:
                probes._checks.clear()
                probes._checks.update(old)


class InternetRow(unittest.TestCase):
    """The Internet row: the ping and the Pi's IP address are its subtitle (the Pi row no longer has the IP)."""
    def setUp(self):
        self.tmp = sandbox()
        with probes._checks_lock:
            self.old = dict(probes._checks)

    def tearDown(self):
        with probes._checks_lock:
            probes._checks.clear()
            probes._checks.update(self.old)
        cleanup(self.tmp)

    def row(self, internet, pi):
        with probes._checks_lock:
            probes._checks["internet"], probes._checks["pi"] = internet, pi
        d = {}
        sw.api(d, [])
        return d["internet"]

    def test_the_ping_and_the_ip_are_the_subtitle(self):
        r = self.row({"state": "ok", "text": "Connected via Ethernet", "ms": 23}, {"state": "ok", "text": "t", "ip": "192.168.1.20"})
        self.assertEqual((r["text"], r["sub"]), ("Connected via Ethernet", "Ping 23 ms \u2022 IP 192.168.1.20"))

    def test_without_internet_there_is_no_ping_but_the_ip_is_still_shown(self):
        r = self.row({"state": "bad", "text": "No internet connection"}, {"state": "ok", "text": "t", "ip": "192.168.1.20"})
        self.assertEqual(r["sub"], "IP 192.168.1.20")
        r = self.row({"state": "bad", "text": "No network connection"}, {"state": "ok", "text": "t", "ip": None})
        self.assertEqual(r["sub"], "No IP address")

    def test_nothing_is_said_before_the_pi_has_been_measured(self):
        self.assertEqual(self.row({"state": "checking", "text": "Checking..."}, {"state": "checking", "text": "Checking..."})["sub"], "")

    def test_the_check_keeps_the_ping_out_of_the_text(self):
        from unittest import mock
        with mock.patch.object(probes.socket, "create_connection", return_value=mock.Mock()), mock.patch.object(probes.socket, "gethostbyname", return_value="1.2.3.4"):
            r = probes.check_internet()
        self.assertEqual((r["state"], r["text"]), ("ok", "Connected"))
        self.assertIsInstance(r["ms"], int)

    def test_the_pi_row_has_no_ip_any_more(self):
        pi = probes.pi_health()
        self.assertNotIn("IP", pi["line2"])
        self.assertNotIn("IP", pi["text"])
        self.assertIn("ip", pi)                                                # it is still measured: the Internet row shows it


class ModemDot(unittest.TestCase):
    def test_the_modem_row_has_a_dot_in_the_states_of_the_other_rows(self):
        import netswitch_switcher as sw
        self.assertEqual(sw._modem_dot("ok", True, True), "ok")
        self.assertEqual(sw._modem_dot("ok", True, None), "ok")
        self.assertEqual(sw._modem_dot("ok", True, False), "warn")       # plugged in, but a modem known not to work well
        self.assertEqual(sw._modem_dot("ok", False, None), "bad")        # the serial port is gone
        self.assertEqual(sw._modem_dot("off", True, True), "bad")        # DreamPi is not running
        self.assertEqual(sw._modem_dot("unknown", None, None), "unknown")


class ModemCompat(unittest.TestCase):
    def usb(self, manufacturer, product):
        return {"vendor": "0572", "product": "1340", "manufacturer": manufacturer, "product_name": product, "serial": ""}

    def test_the_conexant_usb_modem_is_known_to_work(self):
        self.assertEqual(probes.modem_compat(self.usb("Conexant", "USB Modem")), (True, "Conexant USB Modem"))

    def test_the_others_are_unchanged(self):
        self.assertTrue(probes.modem_compat(self.usb("USRobotics", "5637"))[0])
        self.assertFalse(probes.modem_compat(self.usb("Conceptronic", "C56U"))[0])         # the original, not the -v2
        self.assertTrue(probes.modem_compat(self.usb("Conceptronic", "C56U-V2"))[0])
        self.assertIsNone(probes.modem_compat(self.usb("Acme", "Fax Thing"))[0])
        self.assertEqual(probes.modem_compat(None), (None, None))


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
        core.save_time_zone("")                                                           # once set (even to the Pi's own) the file wins
        self.assertEqual(core.time_zone(), "")

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

    def test_an_older_mode_file_is_carried_over(self):
        with open(clock.CLOCK_MODE, "w") as f:
            f.write("beat")
        self.assertEqual((clock.read_config()["format"], clock.read_config()["beat"]), ("24h", True))
        with open(clock.CLOCK_MODE, "w") as f:
            f.write("12h")
        self.assertEqual((clock.read_config()["format"], clock.read_config()["beat"]), ("12h", False))

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
        self.assertEqual(clock.view(summer)["time"], "12:00:00")           # the Pi's own zone (UTC here)
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


class ModemAboutRow(unittest.TestCase):
    """The Modem row of Settings > System > About is the switcher's (it knows the modem): in its /api answer, shown in the shared box."""
    def test_rows(self):
        import netswitch_switcher as sw
        self.assertEqual(sw._modem_about("Conexant USB Modem", True, True), [["Modem", "Conexant USB Modem"]])
        self.assertIn("not known to work", sw._modem_about("Conceptronic C56U", False, True)[0][1])
        self.assertIn("not a modem DreamPi is confirmed", sw._modem_about("Acme", None, True)[0][1])
        self.assertEqual(sw._modem_about(None, None, False), [["Modem", "Not detected (check the USB connection)"]])
        self.assertEqual(sw._modem_about(None, None, None), [])

    def test_the_about_rows_are_collected_by_the_base_from_every_module(self):
        from unittest import mock
        import base_modules as modules
        import netswitch_system as system
        with mock.patch.object(modules, "collect", return_value=[["Modem", "Acme"]]):
            captured = []
            class H(object):
                def send(self, body, ctype): captured.append(json.loads(body))
            system._about(H())
        self.assertIn(["Modem", "Acme"], captured[0])
        self.assertEqual(captured[0][0][0], "Add-on")
