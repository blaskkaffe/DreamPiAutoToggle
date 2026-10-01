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
        self.assertEqual(set(cfg["colours"]), {"dcnow", "dcnet"})
        for net in cfg["colours"].values():
            self.assertEqual(sorted(net), sorted(st[0] for st in ledconfig.LED_STATES))

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
                                    "colours": {"dcnow": {"ok": {"color": "red", "effect": "disco"}}}})
        d = ledconfig.default_led_config()
        self.assertEqual(got["order"], d["order"])
        self.assertEqual(got["colours"]["dcnow"]["ok"]["color"], d["colours"]["dcnow"]["ok"]["color"])
        self.assertEqual(got["colours"]["dcnow"]["ok"]["effect"], d["colours"]["dcnow"]["ok"]["effect"])
        self.assertTrue(0.5 <= got["gamma"] <= 4.0)

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
        self.assertEqual((core.button_gpio(1), core.button_gpio(2)), (17, 4))
        self.assertEqual((core.button_function(1), core.button_function(2)), ("toggle", "off"))
        self.assertEqual(core.wifi_button(), "1")
        core.save_button_gpio(1, 22)
        core.save_button_function(2, "dcnet")
        core.save_wifi_button("12")
        core.save_button_gpio(2, 99)          # out of range: ignored
        core.save_button_function(1, "explode")
        core.save_wifi_button("3")
        self.assertEqual((core.button_gpio(1), core.button_gpio(2)), (22, 4))
        self.assertEqual((core.button_function(1), core.button_function(2)), ("toggle", "dcnet"))
        self.assertEqual(core.wifi_button(), "12")

    def test_white_balance_test_flag(self):
        self.assertFalse(ledconfig.wb_test_active())
        ledconfig.touch_wb_test()
        self.assertTrue(ledconfig.wb_test_active())
        ledconfig.clear_wb_test()
        self.assertFalse(ledconfig.wb_test_active())


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
        for key in ("network", "default", "autoreset", "dreampi", "modem", "internet", "pi", "wifi", "warnings", "now"):
            self.assertIn(key, d)
        self.assertIn(d["network"], ("dcnow", "dcnet"))

    def test_select_network(self):
        self.post("/dcnet")
        self.assertEqual(json.loads(self.get("/api")[2].decode())["network"], "dcnet")
        self.post("/dcnow")
        self.assertEqual(json.loads(self.get("/api")[2].decode())["network"], "dcnow")

    def test_settings_toggles(self):
        self.post("/autoreset")
        self.assertTrue(json.loads(self.get("/api")[2].decode())["autoreset"])
        self.post("/autoreset")
        self.assertFalse(json.loads(self.get("/api")[2].decode())["autoreset"])
        self.post("/default")
        self.assertEqual(json.loads(self.get("/api")[2].decode())["default"], "dcnet")
        self.post("/default")

    def test_ledconfig_round_trip(self):
        r = json.loads(self.get("/ledconfig")[2].decode())
        for key in ("config", "defaults", "states", "effects", "orders", "count", "gpio", "gpios", "installed", "hidden"):
            self.assertIn(key, r)
        cfg = r["config"]
        cfg["white_balance"]["g"] = 200 / 255.0
        cfg["count"], cfg["gpio"] = 5, 21
        out = json.loads(self.post("/ledconfig", cfg)[1].decode())
        self.assertAlmostEqual(out["config"]["white_balance"]["g"], 200 / 255.0)
        self.assertEqual((out["count"], out["gpio"]), (5, 21))
        self.assertEqual(json.loads(self.get("/ledconfig")[2].decode())["count"], 5)
        self.assertTrue(json.loads(self.get("/ledconfig")[2].decode())["installed"])

    def test_zero_leds_hides_the_led_settings(self):
        cfg = json.loads(self.get("/ledconfig")[2].decode())["config"]
        cfg["count"] = 0
        self.post("/ledconfig", cfg)
        self.assertFalse(json.loads(self.get("/ledconfig")[2].decode())["installed"])
        cfg["count"] = 1
        self.post("/ledconfig", cfg)
        self.assertTrue(json.loads(self.get("/ledconfig")[2].decode())["installed"])

    def test_buttonconfig_rejects_shared_pin(self):
        before = json.loads(self.get("/buttonconfig")[2].decode())["config"]
        self.post("/buttonconfig", {"button1_gpio": 5, "button2_gpio": 5})
        after = json.loads(self.get("/buttonconfig")[2].decode())["config"]
        self.assertEqual((after["button1_gpio"], after["button2_gpio"]), (before["button1_gpio"], before["button2_gpio"]))
        self.post("/buttonconfig", {"button1_gpio": 5, "button2_gpio": 6, "button1_function": "dcnet", "wifi_button": "2"})
        after = json.loads(self.get("/buttonconfig")[2].decode())["config"]
        self.assertEqual((after["button1_gpio"], after["button2_gpio"], after["button1_function"], after["wifi_button"]),
                         (5, 6, "dcnet", "2"))

    def test_wbtest_flag(self):
        self.post("/wbtest")
        self.assertTrue(ledconfig.wb_test_active())
        self.post("/wbtestdone")
        self.assertFalse(ledconfig.wb_test_active())

    def test_static_whitelist(self):
        self.assertEqual(self.get("/static/favicon-dcnow.png")[0], 200)
        with self.assertRaises(HTTPError) as cm:
            self.get("/static/netswitch_web.py")
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
        ids = set(re.findall(r'\bid="([^"]+)"', self.html + self.js)) | set(re.findall(r"\bid='([^']+)'", self.js))
        used = set(re.findall(r'\$\("([^"]+)"\)', self.js))
        self.assertEqual(sorted(used - ids), [])

    def test_no_python_escape_leftovers(self):
        self.assertNotIn("\\\\n", self.js)         # a literal backslash-backslash-n would be a Python-string mistake


if __name__ == "__main__":
    unittest.main()
