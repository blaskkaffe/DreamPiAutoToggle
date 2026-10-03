"""The global palette (16 named colours) and the colours a module picks from it. The network switcher picks one for DCNow!
and one for DCNET; the page, the status dot and the LED follow them."""
import json
import threading
import unittest
from urllib.request import urlopen, Request

from support import web, core, ledconfig, sandbox, cleanup


class PaletteTests(unittest.TestCase):
    def test_sixteen_named_colours_in_eight_hue_groups(self):
        pal = core.colours()
        self.assertEqual(len(pal), 16)
        self.assertEqual(len(set(c["id"] for c in pal)), 16)
        self.assertEqual(sorted(set(c["group"] for c in pal)), ["blue", "cyan", "green", "orange", "pink", "purple", "red", "yellow"])
        for g in set(c["group"] for c in pal):
            self.assertEqual([c["id"] for c in pal if c["group"] == g], [g, "bright-" + g])      # each hue: normal, then bright

    def test_the_two_original_ui_colours_are_still_there(self):
        self.assertEqual(core.colour("orange")["ui"], "#e8761c")
        self.assertEqual(core.colour("blue")["ui"], "#1c6fe8")

    def test_an_unknown_id_is_orange(self):
        self.assertEqual(core.colour("nope")["id"], "orange")

    def test_every_colour_has_page_and_led_values(self):
        for c in core.colours():
            for k in ("ui", "ui_l", "led"):
                self.assertRegex(c[k], r"^#[0-9a-f]{6}$", (c["id"], k))

    def test_css_has_variables_and_a_class_per_colour(self):
        css = core.colours_css()
        for c in core.colours():
            self.assertIn("--c-%s:%s;" % (c["id"], c["ui"]), css)
            self.assertIn(".c-%s{--primary:var(--c-%s)" % (c["id"], c["id"]), css)


class ModuleColourTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()

    def tearDown(self):
        cleanup(self.tmp)

    def test_the_switcher_defaults_are_orange_and_blue(self):
        self.assertEqual(core.module_colours("switcher"), {"dcnow": "orange", "dcnet": "blue"})
        self.assertEqual(core.network_colour("dcnow")["ui"], "#e8761c")
        self.assertEqual(core.network_colour("dcnet")["ui"], "#1c6fe8")

    def test_choice_persists_and_any_palette_colour_works(self):
        core.set_module_colour("switcher", "dcnow", "bright-pink")
        self.assertEqual(core.module_colours("switcher"), {"dcnow": "bright-pink", "dcnet": "blue"})
        self.assertEqual(core.network_colour("dcnow")["id"], "bright-pink")

    def test_picking_the_others_colour_swaps(self):
        core.set_module_colour("switcher", "dcnow", "blue")
        self.assertEqual(core.module_colours("switcher"), {"dcnow": "blue", "dcnet": "orange"})

    def test_invalid_input_is_ignored(self):
        self.assertIsNone(core.set_module_colour("switcher", "dcnow", "chartreuse"))
        self.assertIsNone(core.set_module_colour("switcher", "other", "red"))
        self.assertIsNone(core.set_module_colour("nosuchmodule", "dcnow", "red"))
        self.assertEqual(core.module_colours("switcher"), {"dcnow": "orange", "dcnet": "blue"})

    def test_a_broken_file_gives_the_defaults(self):
        with open(core.MODULE_COLOURS, "w") as f:
            f.write("{nonsense")
        self.assertEqual(core.module_colours("switcher"), {"dcnow": "orange", "dcnet": "blue"})

    def test_a_module_without_colours_has_none(self):
        self.assertEqual(core.module_colours("numbers"), {})


class TintTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()

    def tearDown(self):
        cleanup(self.tmp)

    def test_every_colour_has_a_coloured_background_until_the_user_says_otherwise(self):
        self.assertEqual(core.module_tints("switcher"), {"dcnow": True, "dcnet": True})
        self.assertEqual(core.set_module_tint("switcher", "dcnet", False), {"dcnow": True, "dcnet": False})
        self.assertEqual(core.module_tints("switcher")["dcnet"], False)
        self.assertEqual(core.set_module_tint("switcher", "dcnet", True), {"dcnow": True, "dcnet": True})

    def test_unknown_things_are_refused(self):
        self.assertIsNone(core.set_module_tint("switcher", "nope", False))
        self.assertIsNone(core.set_module_tint("nomodule", "dcnow", False))
        self.assertIsNone(core.set_module_tint("switcher", "dcnow", "yes"))

    def test_the_dashboard_modules_each_have_a_colour_of_their_own(self):
        for name in ("switcher", "clock", "players", "debuglog"):
            self.assertTrue(core.module_colours(name), name)
        self.assertEqual(core.module_colours("players"), {"players": "purple"})


class LedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()

    def tearDown(self):
        cleanup(self.tmp)

    def look(self, state="ok"):
        ctx = ledconfig.gather(live=False)
        ctx["state"] = state
        return ledconfig.active_messages(ctx)

    def test_the_network_tokens_follow_the_network_colour(self):
        cfg = ledconfig.led_config()
        cfg["groups"] = [{"id": "g1", "colour": "dcnow", "messages": ["sel-dcnow"]}]
        ledconfig.save_led_config(cfg)
        self.assertEqual(self.look()[0]["color"], core.network_colour("dcnow")["led"])
        core.set_module_colour("switcher", "dcnow", "green")
        self.assertEqual(self.look()[0]["color"], "#00ff00")

    def test_selected_network_token_follows_the_selected_network(self):
        cfg = ledconfig.led_config()
        cfg["groups"] = [{"id": "g1", "colour": "network", "messages": ["ready"]}]
        ledconfig.save_led_config(cfg)
        self.assertEqual(self.look()[0]["color"], core.network_colour("dcnow")["led"])
        open(core.FLAG, "w").close()
        self.assertEqual(self.look()[0]["color"], core.network_colour("dcnet")["led"])


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = sandbox()
        cls.srv = web.Server(("127.0.0.1", 0), web.Handler)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cleanup(cls.tmp)

    def post(self, path, body):
        req = Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                      headers={"X-Requested-With": "netswitch", "Content-Type": "application/json"})
        return urlopen(req, timeout=10)

    def test_round_trip(self):
        got = json.loads(urlopen(self.base + "/colours", timeout=10).read())
        self.assertEqual(len(got["palette"]), 16)
        self.assertEqual(got["modules"]["switcher"], {"dcnow": "orange", "dcnet": "blue"})
        r = json.loads(self.post("/colour", {"module": "switcher", "key": "dcnet", "colour": "bright-green"}).read())
        self.assertEqual(r["colours"]["dcnet"], "bright-green")
        api = json.loads(urlopen(self.base + "/api", timeout=10).read())
        self.assertEqual(api["colours"]["switcher"]["dcnet"], "bright-green")       # /api carries them, so another device follows at once
        page = urlopen(self.base + "/", timeout=10).read().decode()
        self.assertIn("--c-bright-green:#4cd964", page)                              # the palette is in the page's CSS
        self.assertIn('"dcnet": "bright-green"', page)                               # and the module's pick in its layout
        self.post("/colour", {"module": "switcher", "key": "dcnet", "colour": "blue"})

    def test_the_primary_colour_follows_the_selected_network(self):
        self.post("/colour", {"module": "switcher", "key": "dcnow", "colour": "bright-orange"})
        api = json.loads(urlopen(self.base + "/api", timeout=10).read())
        self.assertEqual(api["primary"]["switcher"], "bright-orange")                # DCNow! is selected: its colour is the primary
        self.post("/dcnet", {})
        api = json.loads(urlopen(self.base + "/api", timeout=10).read())
        self.assertEqual(api["primary"]["switcher"], "blue")
        self.post("/dcnow", {})
        self.post("/colour", {"module": "switcher", "key": "dcnow", "colour": "orange"})

    def test_the_background_setting_goes_through_the_colour_endpoint_and_into_api(self):
        r = json.loads(self.post("/colour", {"module": "switcher", "key": "dcnow", "tint": False}).read())
        self.assertEqual(r["tints"], {"dcnow": False, "dcnet": True})
        api = json.loads(urlopen(self.base + "/api", timeout=10).read())
        self.assertEqual(api["tints"]["switcher"]["dcnow"], False)
        self.assertEqual(api["primary_key"]["switcher"], "dcnow")                    # the box follows the selected network's setting
        self.assertEqual(api["colours"]["switcher"]["dcnow"], "orange")              # the colour itself is untouched
        self.post("/colour", {"module": "switcher", "key": "dcnow", "tint": True})

    def test_a_bad_background_setting_is_refused(self):
        from urllib.error import HTTPError
        with self.assertRaises(HTTPError) as e:
            self.post("/colour", {"module": "switcher", "key": "dcnow", "tint": "no"})
        self.assertEqual(e.exception.code, 400)

    def test_a_bad_colour_is_refused(self):
        from urllib.error import HTTPError
        with self.assertRaises(HTTPError) as e:
            self.post("/colour", {"module": "switcher", "key": "dcnet", "colour": "nope"})
        self.assertEqual(e.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
