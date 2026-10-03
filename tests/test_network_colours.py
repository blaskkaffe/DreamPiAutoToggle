"""Network colours are global: one choice for DCNow! and DCNET that the page, the dot and the LED all follow."""
import json
import threading
import unittest
from urllib.request import urlopen, Request

from support import web, core, ledconfig, sandbox, cleanup


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()

    def tearDown(self):
        cleanup(self.tmp)

    def test_defaults_are_orange_and_blue(self):
        self.assertEqual(core.network_colours(), {"dcnow": "orange", "dcnet": "blue"})
        self.assertEqual(core.network_colour("dcnow")["ui"], "#e8761c")
        self.assertEqual(core.network_colour("dcnet")["ui"], "#1c6fe8")

    def test_the_list_has_the_two_ui_colours_then_red_and_green(self):
        self.assertEqual([c[0] for c in core.NETWORK_COLOURS], ["orange", "blue", "red", "green"])

    def test_choice_persists(self):
        core.set_network_colour("dcnow", "green")
        self.assertEqual(core.network_colours(), {"dcnow": "green", "dcnet": "blue"})

    def test_picking_the_others_colour_swaps(self):
        core.set_network_colour("dcnow", "blue")
        self.assertEqual(core.network_colours(), {"dcnow": "blue", "dcnet": "orange"})

    def test_invalid_input_is_ignored(self):
        core.set_network_colour("dcnow", "pink")
        core.set_network_colour("other", "red")
        self.assertEqual(core.network_colours(), {"dcnow": "orange", "dcnet": "blue"})

    def test_a_broken_file_gives_the_defaults(self):
        with open(core.NET_COLOURS, "w") as f:
            f.write("{nonsense")
        self.assertEqual(core.network_colours(), {"dcnow": "orange", "dcnet": "blue"})

    def test_css_variables_follow_the_choice(self):
        core.set_network_colour("dcnet", "red")
        css = core.network_colours_css()
        self.assertIn("--dcnet:#d9363e", css)
        self.assertIn("--dcnet-rgb:217,54,62", css)
        self.assertIn("--dcnow:#e8761c", css)


class LedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()

    def tearDown(self):
        cleanup(self.tmp)

    def colour_of(self, key):
        return [m for m in ledconfig.active_messages("ok", {}, False) if m["key"] == key][0]["color"]

    def test_led_messages_follow_the_network_colour(self):
        self.assertEqual(self.colour_of("ready-dcnow"), core.network_colour("dcnow")["led"])
        core.set_network_colour("dcnow", "green")
        self.assertEqual(self.colour_of("ready-dcnow"), "#00ff00")

    def test_a_colour_saved_for_a_net_bound_message_is_ignored(self):
        cfg = ledconfig.led_config()
        cfg["messages"]["ready-dcnow"]["color"] = "#123456"
        ledconfig.save_led_config(cfg)
        self.assertEqual(self.colour_of("ready-dcnow"), core.network_colour("dcnow")["led"])


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

    def post(self, body):
        req = Request(self.base + "/netcolour", data=json.dumps(body).encode(), method="POST",
                      headers={"X-Requested-With": "netswitch", "Content-Type": "application/json"})
        return urlopen(req, timeout=10).status

    def test_round_trip(self):
        got = json.loads(urlopen(self.base + "/colours", timeout=10).read())
        self.assertEqual([o["id"] for o in got["options"]], ["orange", "blue", "red", "green"])
        self.post({"network": "dcnet", "colour": "green"})
        got = json.loads(urlopen(self.base + "/colours", timeout=10).read())
        self.assertEqual(got["current"]["dcnet"], "green")
        api = json.loads(urlopen(self.base + "/api", timeout=10).read())
        self.assertEqual(api["netcolours"]["dcnet"]["id"], "green")
        page = urlopen(self.base + "/", timeout=10).read().decode()
        self.assertIn("--dcnet:#2fa84f", page)
        self.post({"network": "dcnet", "colour": "blue"})


if __name__ == "__main__":
    unittest.main()
