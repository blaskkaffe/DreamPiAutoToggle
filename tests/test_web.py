"""Web service: config helpers, HTTP round trips and static checks of the page
(JS syntax, every $("id") exists). Runs the real Handler on a random port with
all paths redirected into a temp dir."""
import json
import os
import re
import shutil
import subprocess
import threading
import unittest
try:
    from urllib.request import urlopen, Request
    from urllib.error import HTTPError
except ImportError:   # pragma: no cover
    raise

from support import web, core, ledconfig, sandbox, cleanup
import netswitch_wifi_setup as wf  # noqa: E402
import netswitch_switcher_state as sw  # noqa: E402


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()

    def tearDown(self):
        cleanup(self.tmp)

    def test_led_defaults_are_valid(self):
        cfg = ledconfig.led_config()
        self.assertEqual(cfg["white_balance"], {"r": 1.0, "g": 1.0, "b": 1.0})
        self.assertEqual(cfg["gamma"], ledconfig.GAMMA)
        self.assertIn(cfg["order"], ledconfig.LED_ORDERS)
        self.assertNotIn("colours", cfg)              # one entry per group, not per selected network
        self.assertEqual([g["id"] for g in cfg["groups"]], ["g1", "g2", "g3", "g4", "g5", "g6"])

    def test_led_round_trip_and_clamping(self):
        cfg = ledconfig.led_config()
        cfg["white_balance"] = {"r": 2.0, "g": -1, "b": 0.5}
        cfg["max_brightness"] = 0.3
        cfg["order"] = "RGB"
        ledconfig.save_led_config(cfg)
        got = ledconfig.led_config()
        self.assertEqual(got["white_balance"], {"r": 1.0, "g": 0.0, "b": 0.5})
        self.assertEqual(got["max_brightness"], 0.3)
        self.assertEqual(got["order"], "RGB")

    def test_bad_led_values_fall_back(self):
        got = ledconfig.clean_led_config({"order": "XYZ", "max_brightness": "lots", "gamma": 99,
                                    "groups": [{"colour": "plaid", "effect": "disco", "speed": "warp", "messages": ["ready", "Not a key!"]}]})
        d = ledconfig.default_led_config()
        self.assertEqual(got["order"], d["order"])
        g = got["groups"][0]
        self.assertEqual((g["colour"], g["effect"], g["speed"], g["messages"]), ("orange", "solid", "slow", ["ready-dcnow", "ready-dcnet"]))
        self.assertTrue(0.5 <= got["gamma"] <= 4.0)

    def test_an_old_per_message_config_gets_the_default_groups(self):
        got = ledconfig.clean_led_config({"messages": {"ready-dcnow": {"color": "#ff0000", "effect": "blink"}}})
        self.assertEqual(got["groups"], ledconfig.default_led_config()["groups"])

    def test_led_count_and_gpio(self):
        self.assertEqual(ledconfig.led_gpio(), 18)
        ledconfig.save_led_gpio(12)
        self.assertEqual(ledconfig.led_gpio(), 12)
        ledconfig.save_led_gpio(7)               # not an LED pin: ignored
        self.assertEqual(ledconfig.led_gpio(), 12)
        self.assertEqual(ledconfig.led_count(), 1)           # on by default with one LED
        ledconfig.save_led_count(30)
        self.assertEqual(ledconfig.led_count(), 30)
        ledconfig.save_led_count(9999)                       # clamped to the 0-300 range
        self.assertEqual(ledconfig.led_count(), 300)
        ledconfig.save_led_count("many")                     # ignored
        self.assertEqual(ledconfig.led_count(), 300)
        ledconfig.save_led_count(0)                          # 0 = no LEDs
        self.assertEqual(ledconfig.led_count(), 0)

    def test_button_config_defaults_and_validation(self):
        self.assertEqual((sw.button_gpio(1), sw.button_gpio(2)), (17, 4))
        self.assertEqual((sw.button_function(1), sw.button_function(2)), ("toggle", "off"))
        self.assertEqual(wf.wifi_button(), "1")
        sw.save_button_gpio(1, 22)
        sw.save_button_function(2, "dcnet")
        wf.save_wifi_button("12")
        sw.save_button_gpio(2, 99)          # out of range: ignored
        sw.save_button_function(1, "explode")
        wf.save_wifi_button("3")
        self.assertEqual((sw.button_gpio(1), sw.button_gpio(2)), (22, 4))
        self.assertEqual((sw.button_function(1), sw.button_function(2)), ("toggle", "dcnet"))
        self.assertEqual(wf.wifi_button(), "12")

    def test_white_balance_test_flag(self):
        self.assertFalse(ledconfig.wb_test_active())
        ledconfig.touch_wb_test()
        self.assertTrue(ledconfig.wb_test_active())
        ledconfig.clear_wb_test()
        self.assertFalse(ledconfig.wb_test_active())


def layout_of(screen):
    """The screen settings without the button sound ones (tests/test_sounds.py has those)."""
    return dict((k, v) for k, v in screen.items() if not k.startswith("sound"))


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = sandbox()
        core.save_module_enabled("debuglog", True)     # off by default
        cls.srv = web.Server(("127.0.0.1", 0), web.Handler)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cleanup(cls.tmp)

    def get(self, path):
        r = urlopen(self.base + path, timeout=10)
        return r.status, r.headers, r.read()

    def post(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = Request(self.base + path, data=data or b"", method="POST",
                      headers={"X-Requested-With": "netswitch", "Content-Type": "application/json"})
        r = urlopen(req, timeout=10)
        return r.status, r.read()

    def test_ping_and_page(self):
        self.assertEqual(self.get("/ping")[0], 200)
        st, hdr, body = self.get("/")
        self.assertIn("text/html", hdr["Content-Type"])
        self.assertIn(b"<title>DreamPi</title>", body)

    def test_api_shape(self):
        d = json.loads(self.get("/api")[2].decode())
        for key in ("network", "dreampi", "modem", "internet", "pi", "hangup", "pin", "warnings", "now"):
            self.assertIn(key, d)
        self.assertIn("debug", d)               # added by the debug log module (switched on in setUpClass; off by default)
        self.assertNotIn("wifi", d)             # the Wi-Fi setup module is off by default
        self.assertIn(d["network"], ("dcnow", "dcnet"))

    def test_highlight_and_notices_are_always_in_the_api(self):
        d = json.loads(self.get("/api")[2].decode())
        self.assertIsInstance(d["highlight"], dict)        # always sent, so a box stops standing out when a module stops asking
        self.assertIsInstance(d["notices"], list)
        self.assertEqual(d["theme"], {"highlight": "rainbow"})

    def test_the_highlight_look_is_a_global_setting(self):
        r = json.loads(self.get("/highlight")[2].decode())
        self.assertEqual(r["values"], {"style": "rainbow"})
        self.assertEqual(len(r["options"]["styles"]), 1 + len(core.colour_ids()))
        st, body = self.post("/highlight", {"values": {"style": "bright-green"}})
        self.assertEqual(json.loads(body.decode())["values"], {"style": "bright-green"})
        self.assertEqual(json.loads(self.get("/api")[2].decode())["theme"]["highlight"], "bright-green")
        self.post("/highlight", {"values": {"style": "plaid"}})          # not a look: back to the rainbow
        self.assertEqual(core.highlight_style(), "rainbow")

    def test_the_time_zone_is_a_global_setting(self):
        r = json.loads(self.get("/timezone")[2].decode())
        self.assertEqual(r["values"], {"zone": ""})
        self.assertEqual(r["options"]["zones"][0]["value"], "")
        self.assertIn("Europe/Stockholm", [o["value"] for o in r["options"]["zones"]])
        st, body = self.post("/timezone", {"values": {"zone": "Europe/Stockholm"}})
        got = json.loads(body.decode())
        self.assertEqual(got["values"], {"zone": "Europe/Stockholm"})
        self.assertIn("Stockholm", got["texts"]["zone"])
        self.assertEqual(core.time_zone(), "Europe/Stockholm")
        self.post("/timezone", {"values": {"zone": "Mars/Olympus"}})     # not a zone of the list: the Pi's own
        self.assertEqual(core.time_zone(), "")

    def test_a_module_prefix_route(self):
        st, hdr, body = self.get("/api/status")              # the events module's API (on by default)
        self.assertEqual(json.loads(body.decode())["source"], "dc99")
        try:
            urlopen(self.base + "/api/events/12345", timeout=10)
            self.fail("an unknown event must be a 404")
        except HTTPError as e:
            self.assertEqual(e.code, 404)
            self.assertIn(b"no such event", e.read())

    def test_screen_layout_settings(self):
        d = json.loads(self.get("/api")[2].decode())
        self.assertEqual(layout_of(d["screen"]), {"dash_cols": 1, "set_cols": 4, "stretch": False, "scale": False, "drag": False, "fit": False, "theme": "dark"})
        self.post("/screen", {"values": {"dash_cols": 3, "set_cols": 2}})
        self.post("/screen/stretch", {"value": True})
        self.post("/screen/scale", {"value": True})
        self.post("/screen/fit", {"value": True})
        d = json.loads(self.get("/api")[2].decode())
        self.assertEqual(layout_of(d["screen"]), {"dash_cols": 3, "set_cols": 2, "stretch": True, "scale": True, "drag": False, "fit": True, "theme": "dark"})
        self.post("/screen/fit", {"value": False})
        reply = json.loads(self.get("/screen")[2].decode())
        self.assertEqual(layout_of(reply["values"]), {"dash_cols": 3, "set_cols": 2, "theme": "dark"})
        self.assertEqual([o["value"] for o in reply["options"]["cols"]], [1, 2, 3, 4, 5, 6])
        self.post("/screen", {"values": {"dash_cols": 9, "set_cols": "x"}})                       # out of range / not a number: kept
        self.assertEqual((core.screen_settings()["dash_cols"], core.screen_settings()["set_cols"]), (3, 2))
        self.post("/screen/stretch", {"value": "yes"})                                             # not true or false: kept
        self.assertTrue(core.screen_settings()["stretch"])

    def test_moving_the_tiles_of_the_main_screen_reorders_the_modules(self):
        self.post("/screen/drag", {"value": True})
        self.assertTrue(core.screen_settings()["drag"])
        before = core.module_names()
        got = json.loads(self.post("/modules/dashboard-order", {"order": ["players", "switcher"]})[1].decode())
        names = [m["name"] for m in got["modules"]]
        self.assertEqual(names.index("players") < names.index("switcher"), True)
        self.assertEqual(sorted(core.module_names()), sorted(before))                           # nothing lost
        self.assertEqual([m["group"] for m in got["modules"]], sorted(m["group"] for m in got["modules"]))
        with self.assertRaises(HTTPError):
            self.post("/modules/dashboard-order", {"order": "players"})
        self.post("/screen/drag", {"value": False})

    def test_the_theme_is_in_the_page_and_in_the_api(self):
        html = self.get("/")[2].decode()
        self.assertIn('data-pref="dark" data-theme="dark"', html)
        for theme in ("light", "auto"):
            self.post("/screen", {"values": {"theme": theme}})
            self.assertEqual(json.loads(self.get("/api")[2].decode())["screen"]["theme"], theme)
            self.assertIn('data-pref="%s" data-theme="%s"' % (theme, theme), self.get("/")[2].decode())      # built in: no flash of the other theme
        self.post("/screen", {"values": {"theme": "neon"}})                                              # not a theme: kept
        self.assertEqual(core.screen_settings()["theme"], "auto")
        self.assertIn("html[data-theme=light]", html)                                                      # the light tokens are in the page, palette included
        self.assertIn("--c-orange-l:", html.split("html[data-theme=light]", 1)[1].split("}", 1)[0])
        self.post("/screen", {"values": {"theme": "dark"}})
        reply = json.loads(self.get("/screen")[2].decode())
        self.assertEqual([o["value"] for o in reply["options"]["themes"]], ["dark", "light", "auto"])

    def test_a_bad_screen_file_gives_the_defaults(self):
        open(core.SCREEN, "w").write("[1, 2")
        self.assertEqual(core.screen_settings(), core.SCREEN_DEFAULTS)
        open(core.SCREEN, "w").write('{"dash_cols": 0, "set_cols": true, "stretch": 1}')
        self.assertEqual(core.screen_settings(), core.SCREEN_DEFAULTS)

    def test_select_network(self):
        self.post("/dcnet")
        self.assertEqual(json.loads(self.get("/api")[2].decode())["network"], "dcnet")
        self.post("/dcnow")
        self.assertEqual(json.loads(self.get("/api")[2].decode())["network"], "dcnow")

    def test_default_network_and_auto_reset_are_gone(self):
        d = json.loads(self.get("/api")[2].decode())
        for key in ("default", "autoreset"):
            self.assertNotIn(key, d)
        html = self.get("/")[2].decode()
        for word in ("default-b", "reset-b", 'class="switch', "Auto reset", "Default network"):
            self.assertNotIn(word, html, word)
        for path in ("/default", "/autoreset"):
            with self.assertRaises(HTTPError):
                self.post(path)

    def test_keep_alive_serves_many_requests_on_one_connection(self):
        import http.client
        host, port = self.base.split("//")[1].split(":")
        c = http.client.HTTPConnection(host, int(port), timeout=10)
        try:
            for _ in range(3):
                c.request("GET", "/api")
                r = c.getresponse()
                self.assertEqual(r.status, 200)
                self.assertNotEqual((r.getheader("Connection") or "").lower(), "close")
                r.read()
            # a POST that is refused without its body being read must not poison the next request on the connection
            c.request("POST", "/nothing-here", body=b'{"x": 1}', headers={"X-Requested-With": "netswitch", "Content-Type": "application/json"})
            r = c.getresponse()
            self.assertEqual(r.status, 404)
            r.read()
            c.request("GET", "/api")
            r = c.getresponse()
            self.assertEqual(r.status, 200)
            r.read()
            c.request("POST", "/dcnow", headers={"X-Requested-With": "netswitch"})       # no body at all
            r = c.getresponse()
            self.assertEqual(r.status, 204)
            r.read()
            c.request("GET", "/api")
            self.assertEqual(c.getresponse().status, 200)
        finally:
            c.close()

    def test_system_card_links_to_the_github_project(self):
        html = self.get("/")[2].decode()
        self.assertIn('"href": "https://github.com/blaskkaffe/DreamPiAutoToggle"', html)       # the System module's row (layout.json)
        self.assertIn("noopener noreferrer", html)                                              # which the link widget opens safely

    def test_hide_led_settings_is_gone(self):
        self.assertNotIn("hidden", json.loads(self.get("/ledconfig")[2].decode()))
        with self.assertRaises(HTTPError):
            self.post("/ledhide")
        html = self.get("/")[2].decode()
        for word in ("led-hide-b", "Hide these settings", "How to update by hand", "upd-guide"):
            self.assertNotIn(word, html, word)

    def test_ledconfig_round_trip(self):
        r = json.loads(self.get("/ledconfig")[2].decode())
        for key in ("config", "token_ui", "count", "installed"):
            self.assertIn(key, r)
        self.assertNotIn("groups", r["config"])              # the looks are GET/POST /ledrows
        cfg = r["config"]
        cfg["white_balance"]["g"] = 200 / 255.0
        cfg["order"] = "BGR"                                 # the wire order belongs to the GPIO form: this POST keeps the saved one
        out = json.loads(self.post("/ledconfig", cfg)[1].decode())
        self.assertAlmostEqual(out["config"]["white_balance"]["g"], 200 / 255.0)
        self.assertNotEqual(out["config"]["order"], "BGR")
        hw = json.loads(self.post("/ledhardware", {"values": {"led_count": 5, "led_gpio": 21, "led_order": "RGB"}})[1].decode())
        self.assertEqual(hw["values"], {"led_count": 5, "led_gpio": 21, "led_order": "RGB"})
        self.assertEqual([o["value"] for o in hw["options"]["orders"]], list(ledconfig.LED_ORDERS))
        self.assertEqual(json.loads(self.get("/ledconfig")[2].decode())["count"], 5)
        self.assertEqual(json.loads(self.get("/ledconfig")[2].decode())["config"]["order"], "RGB")
        self.assertTrue(json.loads(self.get("/ledconfig")[2].decode())["installed"])
        self.post("/ledconfig", dict(cfg, order="GRB"))        # a later save of the looks does not undo the hardware settings
        self.assertEqual(json.loads(self.get("/ledhardware")[2].decode())["values"]["led_order"], "RGB")

    def test_zero_leds_hides_the_led_settings(self):
        self.post("/ledhardware", {"values": {"led_count": 0}})
        self.assertFalse(json.loads(self.get("/ledconfig")[2].decode())["installed"])
        self.assertFalse(json.loads(self.get("/api")[2].decode())["led"]["installed"])      # the page hides the LED widgets by this
        self.post("/ledhardware", {"values": {"led_count": 1}})
        self.assertTrue(json.loads(self.get("/ledconfig")[2].decode())["installed"])
        self.assertTrue(json.loads(self.get("/api")[2].decode())["led"]["installed"])

    def buttons(self):
        return json.loads(self.get("/buttonconfig")[2].decode())

    def test_buttonconfig_has_the_standard_form_shape(self):
        r = self.buttons()
        self.assertEqual(sorted(r["values"]), ["button1_function", "button1_gpio", "button2_function", "button2_gpio"])
        self.assertEqual([o["value"] for o in r["options"]["gpios"]], list(sw.BUTTON_GPIO_PINS))
        functions = r["options"]["functions"]
        self.assertTrue(all(f["label"] and f["group"] for f in functions))
        self.assertNotIn("sw_wifi", [f["value"] for f in functions])         # the Wi-Fi switch functions wait for the Wi-Fi module

    def test_the_line_under_each_button_names_its_pin_and_what_it_does(self):
        self.post("/buttonconfig", {"values": {"button1_gpio": 17, "button2_gpio": 4, "button1_function": "toggle", "button2_function": "sw_dcnet"}})
        t = self.buttons()["texts"]
        self.assertEqual(t["button1"], "GPIO17 toggles DCNow! and DCNET")
        self.assertEqual(t["button2"], "GPIO4 closed: DCNET, open: DCNow!")
        self.post("/buttonconfig", {"values": {"button1_gpio": 22, "button1_function": "dcnow", "button2_gpio": 4, "button2_function": "off"}})
        t = self.buttons()["texts"]
        self.assertEqual((t["button1"], t["button2"]), ("GPIO22 selects DCNow!", "GPIO4 is not used"))
        self.assertNotIn("{pin}", " ".join(t.values()))
        for f in sw.BUTTON_FUNCTIONS:                                   # every function has a line that starts with its pin
            self.assertTrue(f[4].startswith("{pin} "), f[0])

    def test_the_led_line_counts_the_leds_with_order_and_pin(self):
        self.post("/ledhardware", {"values": {"led_count": 10, "led_order": "GRB", "led_gpio": 18}})
        self.assertEqual(json.loads(self.get("/ledhardware")[2].decode())["texts"]["led"], "10 GRB LEDs connected to GPIO18")
        self.post("/ledhardware", {"values": {"led_count": 1, "led_order": "RGB", "led_gpio": 12}})
        self.assertEqual(json.loads(self.get("/ledhardware")[2].decode())["texts"]["led"], "1 RGB LED connected to GPIO12")

    def test_buttonconfig_rejects_shared_pin(self):
        before = self.buttons()["values"]
        self.post("/buttonconfig", {"values": {"button1_gpio": 5, "button2_gpio": 5}})
        after = self.buttons()["values"]
        self.assertEqual((after["button1_gpio"], after["button2_gpio"]), (before["button1_gpio"], before["button2_gpio"]))
        out = json.loads(self.post("/buttonconfig", {"values": {"button1_gpio": 5, "button2_gpio": 6, "button1_function": "dcnet"}})[1].decode())
        self.assertEqual((out["values"]["button1_gpio"], out["values"]["button2_gpio"], out["values"]["button1_function"]), (5, 6, "dcnet"))
        after = self.buttons()["values"]
        self.assertEqual((after["button1_gpio"], after["button2_gpio"], after["button1_function"]), (5, 6, "dcnet"))

    def test_wifi_functions_are_offered_while_the_wifi_module_is_on(self):
        core.save_module_enabled("wifi", True)
        try:
            self.assertIn("sw_wifi", [f["value"] for f in self.buttons()["options"]["functions"]])
            out = json.loads(self.post("/wifibutton", {"values": {"wifi_button": "2"}})[1].decode())
            self.assertEqual(out["values"]["wifi_button"], "2")
            self.assertEqual(out["texts"]["wifi_button"], "Hold button 2 for 3 s to start Wi-Fi setup")
            self.assertEqual(wf.wifi_button(), "2")
            self.post("/wifibutton", {"values": {"wifi_button": "nope"}})
            self.assertEqual(wf.wifi_button(), "2")
        finally:
            core.save_module_enabled("wifi", False)

    def test_wbtest_flag(self):
        self.post("/wbtest")
        self.assertTrue(ledconfig.wb_test_active())
        self.post("/wbtestdone")
        self.assertFalse(ledconfig.wb_test_active())

    def test_static_whitelist(self):
        self.assertEqual(self.get("/static/favicon-dcnow.png")[0], 200)
        with self.assertRaises(HTTPError) as cm:
            self.get("/static/base_web.py")
        self.assertEqual(cm.exception.code, 404)

    def test_about_and_log(self):
        self.assertIsInstance(json.loads(self.get("/about")[2].decode()), list)
        self.assertIn("size", json.loads(self.get("/log?from=0")[2].decode()))


class PageTests(unittest.TestCase):
    """Static checks of the page the browser receives (inline scripts and any
    <script src> files)."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = sandbox()
        cls.srv = web.Server(("127.0.0.1", 0), web.Handler)
        base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.html = urlopen(base + "/", timeout=10).read().decode("utf-8")
        scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", cls.html, re.S)
        for src in re.findall(r"<script[^>]*\bsrc=\"([^\"]+)\"", cls.html):
            if src.startswith("/") and not src.startswith("/static/"):
                scripts.append(urlopen(base + src, timeout=10).read().decode("utf-8"))
        cls.js = "\n".join(scripts)
        cls.css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", cls.html, re.S))
        cls.srv_base = base

    def test_html_tags_are_balanced(self):
        """A stray '</span</span>' in a hand edit once left a span open; catch any mismatch."""
        from html.parser import HTMLParser
        void = {"br", "input", "meta", "link", "img", "hr"}
        problems, stack = [], []

        class P(HTMLParser):
            def handle_starttag(self, tag, attrs):
                if tag not in void:
                    stack.append((tag, self.getpos()[0]))

            def handle_endtag(self, tag):
                if stack and stack[-1][0] == tag:
                    stack.pop()
                else:
                    problems.append("</%s> at line %d, open: %s" % (tag, self.getpos()[0], stack[-1:]))

        P().feed(self.html)
        self.assertEqual(problems, [])
        self.assertEqual(stack, [])

    def test_finished_update_reloads_only_the_page_that_watched_it(self):
        """An 'ok' update state lasts 10 minutes; reloading on every sight of it closed Settings."""
        self.assertIn('u.state=="ok"&&updWatched', self.js)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cleanup(cls.tmp)

    def test_js_syntax(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        path = os.path.join(self.tmp, "page.js")
        with open(path, "w") as f:
            f.write(self.js)
        p = subprocess.run([node, "--check", path], stderr=subprocess.PIPE)
        self.assertEqual(p.returncode, 0, p.stderr.decode())

    def test_every_literal_id_exists(self):
        text = (self.html + self.js).replace('\\"', '"')                      # markup inside a layout's JSON strings has escaped quotes
        ids = set(re.findall(r'\bid="([^"]+)"', text)) | set(re.findall(r"\bid='([^']+)'", self.js))
        used = set(re.findall(r'\$\("([^"]+)"\)', self.js))
        self.assertEqual(sorted(used - ids), [])

    def test_no_python_escape_leftovers(self):
        self.assertNotIn("\\\\n", self.js)         # a literal backslash-backslash-n would be a Python-string mistake


if __name__ == "__main__":
    unittest.main()
