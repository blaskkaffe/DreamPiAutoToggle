"""The global palette (16 named colours) and the colours a module picks from it. The network switcher picks one for DCNow!
and one for DCNET; the page, the status dot and the LED follow them."""
import json
import threading
import unittest
from urllib.request import urlopen, Request

from support import web, core, ledconfig, sandbox, cleanup


class PaletteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()

    def tearDown(self):
        cleanup(self.tmp)

    def test_fifteen_palette_colours_in_the_order_of_the_grid_and_the_switchers_own(self):
        pal = core.colours()
        self.assertEqual([c["id"] for c in pal if not c.get("token")], ["global", "red", "orange", "yellow", "green", "cyan", "blue", "purple",
                                                                       "white", "bright-red", "bright-green", "bright-cyan", "bright-blue",
                                                                       "bright-purple", "bright-pink"])
        self.assertEqual([c["id"] for c in pal if c.get("token")], ["network"])           # Selected network is not in the palette: the network switcher module adds it
        self.assertEqual([t["module"] for t in core.colour_tokens()], ["switcher"])
        self.assertNotIn("network", core.PALETTE_IDS)
        self.assertEqual(core.colour_ids(), core.palette_ids() + ("network",))
        self.assertEqual(len(set(c["id"] for c in pal)), 16)
        self.assertNotIn("pink", core.PALETTE_IDS)                                       # the dark pink, bright orange and bright yellow are gone
        self.assertNotIn("bright-orange", core.PALETTE_IDS)
        self.assertNotIn("bright-yellow", core.PALETTE_IDS)

    def test_a_saved_choice_of_a_removed_colour_becomes_its_nearest(self):
        with open(core.MODULE_COLOURS, "w") as f:
            json.dump({"switcher": {"dcnow": "bright-orange", "dcnet": "pink"}}, f)
        self.assertEqual(core.module_colours("switcher"), {"selector": "network", "dcnow": "orange", "dcnet": "bright-pink"})
        self.assertEqual(core.colour("bright-yellow")["id"], "yellow")

    def test_selected_network_is_the_colour_the_selected_network_has(self):
        self.assertEqual(core.colour("network")["ui"], core.colour("orange")["ui"])          # DCNow! is selected, and orange
        open(core.FLAG, "w").close()
        self.assertEqual(core.colour("network")["ui"], core.colour("blue")["ui"])            # DCNET: blue
        core.set_module_colour("switcher", "dcnet", "green")
        self.assertEqual(core.colour("network")["led"], core.colour("green")["led"])
        self.assertEqual(core.colour("network")["id"], "network")

    def test_the_network_buttons_cannot_be_the_selected_network(self):
        self.assertIsNone(core.set_module_colour("switcher", "dcnow", "network"))
        self.assertEqual(core.set_module_colour("clock", "clock", "network"), {"clock": "network"})    # a box can

    def test_global_main_is_a_colour_the_user_picks(self):
        self.assertTrue(core.set_palette_colour("global", ui="#112233"))
        self.assertEqual(core.colour("global")["ui"], "#112233")
        self.assertFalse(core.set_palette_colour("network", ui="#112233"))                   # that one follows the switch

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
        self.assertEqual(core.module_colours("switcher"), {"selector": "network", "dcnow": "orange", "dcnet": "blue"})
        self.assertEqual(core.network_colour("dcnow")["ui"], "#e8761c")
        self.assertEqual(core.network_colour("dcnet")["ui"], "#1c6fe8")

    def test_choice_persists_and_any_palette_colour_works(self):
        core.set_module_colour("switcher", "dcnow", "bright-pink")
        self.assertEqual(core.module_colours("switcher"), {"selector": "network", "dcnow": "bright-pink", "dcnet": "blue"})
        self.assertEqual(core.network_colour("dcnow")["id"], "bright-pink")

    def test_the_selector_may_be_the_selected_network_but_the_networks_may_not_and_never_swap_with_it(self):
        self.assertEqual(core.module_colours("switcher")["selector"], "network")
        self.assertIsNone(core.set_module_colour("switcher", "dcnow", "network"))            # a network cannot be "the selected network" (a circle)
        got = core.set_module_colour("switcher", "selector", "orange")                       # the selector may share DCNow!'s colour: no swap
        self.assertEqual(got, {"selector": "orange", "dcnow": "orange", "dcnet": "blue"})
        got = core.set_module_colour("switcher", "dcnet", "orange")                          # the two networks still swap with each other
        self.assertEqual(got, {"selector": "orange", "dcnow": "blue", "dcnet": "orange"})

    def test_picking_the_others_colour_swaps(self):
        core.set_module_colour("switcher", "dcnow", "blue")
        self.assertEqual(core.module_colours("switcher"), {"selector": "network", "dcnow": "blue", "dcnet": "orange"})

    def test_invalid_input_is_ignored(self):
        self.assertIsNone(core.set_module_colour("switcher", "dcnow", "chartreuse"))
        self.assertIsNone(core.set_module_colour("switcher", "other", "red"))
        self.assertIsNone(core.set_module_colour("nosuchmodule", "dcnow", "red"))
        self.assertEqual(core.module_colours("switcher"), {"selector": "network", "dcnow": "orange", "dcnet": "blue"})

    def test_a_broken_file_gives_the_defaults(self):
        with open(core.MODULE_COLOURS, "w") as f:
            f.write("{nonsense")
        self.assertEqual(core.module_colours("switcher"), {"selector": "network", "dcnow": "orange", "dcnet": "blue"})

    def test_a_module_without_colours_has_none(self):
        self.assertEqual(core.module_colours("numbers"), {})


class TintTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()

    def tearDown(self):
        cleanup(self.tmp)

    def test_the_boxes_start_neutral_and_the_network_buttons_highlighted(self):
        for name in ("clock", "players", "debuglog"):
            self.assertEqual(core.module_tints(name), {name: False}, name)
        self.assertEqual(core.module_tints("switcher"), {"selector": False, "dcnow": True, "dcnet": True})
        self.assertEqual(core.set_module_tint("players", "players", True), {"players": True})       # and the user can highlight one
        self.assertEqual(core.set_module_tint("players", "players", False), {"players": False})
        self.assertEqual(json.load(open(core.MODULE_TINTS)).get("players"), {})                   # a value that is the default is not kept

    def test_a_network_colour_can_be_switched_off_and_on(self):
        self.assertEqual(core.module_tints("switcher"), {"selector": False, "dcnow": True, "dcnet": True})
        self.assertEqual(core.set_module_tint("switcher", "dcnet", False), {"selector": False, "dcnow": True, "dcnet": False})
        self.assertEqual(core.module_tints("switcher")["dcnet"], False)
        self.assertEqual(core.set_module_tint("switcher", "dcnet", True), {"selector": False, "dcnow": True, "dcnet": True})

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
        self.assertEqual(got["modules"]["switcher"], {"selector": "network", "dcnow": "orange", "dcnet": "blue"})
        r = json.loads(self.post("/colour", {"module": "switcher", "key": "dcnet", "colour": "bright-green"}).read())
        self.assertEqual(r["colours"]["dcnet"], "bright-green")
        api = json.loads(urlopen(self.base + "/api", timeout=10).read())
        self.assertEqual(api["colours"]["switcher"]["dcnet"], "bright-green")       # /api carries them, so another device follows at once
        page = urlopen(self.base + "/", timeout=10).read().decode()
        self.assertIn("--c-bright-green:#4cd964", page)                              # the palette is in the page's CSS
        self.assertIn('"dcnet": "bright-green"', page)                               # and the module's pick in its layout
        self.post("/colour", {"module": "switcher", "key": "dcnet", "colour": "blue"})

    def test_the_primary_colour_follows_the_selected_network(self):
        self.post("/colour", {"module": "switcher", "key": "dcnow", "colour": "bright-green"})
        api = json.loads(urlopen(self.base + "/api", timeout=10).read())
        self.assertEqual(api["primary"]["switcher"], "bright-green")                # DCNow! is selected: its colour is the primary
        self.post("/dcnet", {})
        api = json.loads(urlopen(self.base + "/api", timeout=10).read())
        self.assertEqual(api["primary"]["switcher"], "blue")
        self.post("/dcnow", {})
        self.post("/colour", {"module": "switcher", "key": "dcnow", "colour": "orange"})

    def test_the_selector_has_its_own_colour_and_background(self):
        api = json.loads(urlopen(self.base + "/api", timeout=10).read())
        self.assertEqual((api["colours"]["switcher"]["selector"], api["tints"]["switcher"]["selector"]), ("network", False))      # grey, in the selected network's colour
        self.post("/colour", {"module": "switcher", "key": "selector", "colour": "bright-cyan"})
        self.post("/colour", {"module": "switcher", "key": "selector", "tint": True})
        api = json.loads(urlopen(self.base + "/api", timeout=10).read())
        self.assertEqual(api["primary"]["switcher"], "bright-cyan")                  # the box takes its own pick ...
        self.assertEqual(api["colours"]["switcher"]["dcnow"], "orange")              # ... and neither network colour is swapped or changed
        self.assertEqual(api["tints"]["switcher"], {"selector": True, "dcnow": True, "dcnet": True})
        self.post("/colour", {"module": "switcher", "key": "selector", "colour": "network"})
        self.post("/colour", {"module": "switcher", "key": "selector", "tint": False})

    def test_the_background_setting_goes_through_the_colour_endpoint_and_into_api(self):
        r = json.loads(self.post("/colour", {"module": "switcher", "key": "dcnow", "tint": False}).read())
        self.assertEqual(r["tints"], {"selector": False, "dcnow": False, "dcnet": True})
        api = json.loads(urlopen(self.base + "/api", timeout=10).read())
        self.assertEqual(api["tints"]["switcher"]["dcnow"], False)
        self.assertEqual(api["primary_key"]["switcher"], "selector")                 # the box follows the Network Selector's own setting, not a network's
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
