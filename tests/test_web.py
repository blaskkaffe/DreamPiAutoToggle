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

from support import web, core, sandbox, cleanup


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
        self.assertIn(b"<title>Check-in</title>", body)

    def test_api_shape(self):
        d = json.loads(self.get("/api")[2].decode())
        for key in ("pin", "warnings", "now", "enabled", "colours", "checkin"):
            self.assertIn(key, d)
        self.assertNotIn("wifi", d)             # the Wi-Fi setup module is off by default
        self.assertEqual(d["checkin"]["total"], 0)      # no contacts imported yet

    def test_highlight_and_notices_are_always_in_the_api(self):
        d = json.loads(self.get("/api")[2].decode())
        self.assertIsInstance(d["highlight"], dict)        # always sent, so a box stops standing out when a module stops asking
        self.assertIsInstance(d["notices"], list)
        self.assertEqual(d["theme"], {"highlight": "rainbow"})

    def test_the_highlight_look_is_a_global_setting(self):
        r = json.loads(self.get("/highlight")[2].decode())
        self.assertEqual(r["values"], {"style": "rainbow"})
        self.assertEqual(len(r["options"]["styles"]), 1 + len(core.PALETTE_IDS))
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

    def test_screen_layout_settings(self):
        d = json.loads(self.get("/api")[2].decode())
        self.assertEqual(d["screen"], {"dash_cols": 1, "set_cols": 4, "stretch": False, "scale": False, "drag": False})
        self.post("/screen", {"values": {"dash_cols": 3, "set_cols": 2}})
        self.post("/screen/stretch", {"value": True})
        self.post("/screen/scale", {"value": True})
        d = json.loads(self.get("/api")[2].decode())
        self.assertEqual(d["screen"], {"dash_cols": 3, "set_cols": 2, "stretch": True, "scale": True, "drag": False})
        reply = json.loads(self.get("/screen")[2].decode())
        self.assertEqual(reply["values"], {"dash_cols": 3, "set_cols": 2})
        self.assertEqual([o["value"] for o in reply["options"]["cols"]], [1, 2, 3, 4, 5, 6])
        self.post("/screen", {"values": {"dash_cols": 9, "set_cols": "x"}})                       # out of range / not a number: kept
        self.assertEqual((core.screen_settings()["dash_cols"], core.screen_settings()["set_cols"]), (3, 2))
        self.post("/screen/stretch", {"value": "yes"})                                             # not true or false: kept
        self.assertTrue(core.screen_settings()["stretch"])

    def test_moving_the_tiles_of_the_main_screen_reorders_the_modules(self):
        self.post("/screen/drag", {"value": True})
        self.assertTrue(core.screen_settings()["drag"])
        before = core.module_names()
        got = json.loads(self.post("/modules/dashboard-order", {"order": ["clock", "checkin"]})[1].decode())
        names = [m["name"] for m in got["modules"]]
        self.assertTrue(names.index("clock") < names.index("checkin"))
        self.assertEqual(sorted(core.module_names()), sorted(before))                           # nothing lost
        self.assertEqual([m["group"] for m in got["modules"]], sorted(m["group"] for m in got["modules"]))
        with self.assertRaises(HTTPError):
            self.post("/modules/dashboard-order", {"order": "clock"})
        self.post("/screen/drag", {"value": False})

    def test_a_bad_screen_file_gives_the_defaults(self):
        open(core.SCREEN, "w").write("[1, 2")
        self.assertEqual(core.screen_settings(), core.SCREEN_DEFAULTS)
        open(core.SCREEN, "w").write('{"dash_cols": 0, "set_cols": true, "stretch": 1}')
        self.assertEqual(core.screen_settings(), core.SCREEN_DEFAULTS)

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
            c.request("POST", "/checkin/all", headers={"X-Requested-With": "netswitch"})       # no body at all
            r = c.getresponse()
            self.assertEqual(r.status, 200)
            r.read()
            c.request("GET", "/api")
            self.assertEqual(c.getresponse().status, 200)
        finally:
            c.close()

    def test_system_card_links_to_the_github_project(self):
        html = self.get("/")[2].decode()
        self.assertIn('"href": "https://github.com/blaskkaffe/DreamPiAutoToggle"', html)       # the System module's row (layout.json)
        self.assertIn("noopener noreferrer", html)                                              # which the link widget opens safely

    def test_about_rows(self):
        rows = json.loads(self.get("/about")[2].decode())
        self.assertEqual(rows[0][0], "Add-on")
        self.assertNotIn("dreampi.py", [r[0] for r in rows])      # nothing of DreamPi is shown any more


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
