"""The DC Bridge module's dashboard side (modules/dcbridge/netswitch_dcbridge.py): what it shows of the bridge service, and the save manager
that it passes on from /dcbridge/ to the service on 127.0.0.1."""
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from support import core, web, sandbox, cleanup
import netswitch_dcbridge as dcb

BRIDGE = {"summary": "serial 120192 baud", "firmware": {"mode": "uart", "baud": 120192, "underruns": 0},
          "links": {"w5500": {"interface": "dcnet0", "present": True, "dreamcast": "192.168.170.2"},
                    "ppp": {"interface": "ppp10", "present": False, "dreamcast": None}}}
STATUS = {"connected": True, "pending": 2, "last_session": time.time() - 120}


class Fake(BaseHTTPRequestHandler):
    """Stands in for dcbridge-saves on 127.0.0.1: records what the dashboard passed on."""
    seen = []

    def _answer(self, code=200, body=b"{}", ctype="application/json", extra=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in extra:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        n = int(self.headers.get("Content-Length") or 0)
        Fake.seen.append(("GET", self.path, self.rfile.read(n), self.headers.get("Content-Type")))
        if self.path == "/api/bridge":
            return self._answer(200, json.dumps(BRIDGE).encode())
        if self.path == "/api/status":
            return self._answer(200, json.dumps(STATUS).encode())
        if self.path.startswith("/api/export.zip"):
            return self._answer(200, b"PK\x03\x04", "application/zip", [("Content-Disposition", 'attachment; filename="x.zip"'), ("X-Secret", "no")])
        self._answer(200, b"<html>manager</html>", "text/html; charset=utf-8")

    def _change(self):
        n = int(self.headers.get("Content-Length") or 0)
        Fake.seen.append((self.command, self.path, self.rfile.read(n), self.headers.get("Content-Type")))
        self._answer(202, b'{"queued": "x"}')

    do_POST = do_PUT = do_DELETE = _change

    def log_message(self, *a):
        pass


class Bridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = sandbox()
        cls.fake = HTTPServer(("127.0.0.1", 0), Fake)
        dcb.PORT = cls.fake.server_address[1]
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        core.save_module_enabled("dcbridge", True)
        cls.srv = web.Server(("127.0.0.1", 0), web.Handler)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        web.refresh_page(force=True)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.fake.shutdown()
        cls.fake.server_close()
        cleanup(cls.tmp)

    def setUp(self):
        Fake.seen = []
        dcb.poll()

    def post(self, path, body=b"", headers=None):
        h = {"X-Requested-With": "page"}
        h.update(headers or {})
        return urlopen(Request(self.base + path, data=body, method="POST", headers=h), timeout=10)

    def test_what_the_dashboard_shows(self):
        v = dcb.view()
        self.assertTrue(v["up"])
        self.assertEqual(v["dreamcast"], {"state": "ok", "text": "serial 120192 baud"})
        self.assertEqual((v["card"]["state"], v["card"]["text"]), ("ok", "Virtual SD card online"))
        self.assertIn("2 edits queued", v["card"]["sub"])
        self.assertEqual(v["net"], {"state": "ok", "text": "W5500 192.168.170.2"})
        api = json.loads(urlopen(self.base + "/api", timeout=10).read().decode())
        self.assertEqual(api["dcbridge"]["dreamcast"]["state"], "ok")
        self.assertEqual(json.loads(urlopen(self.base + "/dcbridge-view", timeout=10).read().decode())["up"], True)

    def test_timing_underruns_and_a_missing_board_and_a_missing_service(self):
        with dcb._lock:
            dcb._seen["bridge"] = dict(BRIDGE, firmware=dict(BRIDGE["firmware"], underruns=3))
        self.assertEqual(dcb.view()["dreamcast"]["state"], "warn")
        self.assertIn("3 timing underruns", dcb.view()["dreamcast"]["text"])
        with dcb._lock:
            dcb._seen["bridge"] = dict(BRIDGE, firmware=None)
        self.assertEqual(dcb.view()["dreamcast"]["state"], "warn")
        with dcb._lock:
            dcb._seen["time"] = time.time() - 60                                  # the look is old: the service is taken as gone
        v = dcb.view()
        self.assertFalse(v["up"])
        warnings = []
        d = {}
        dcb.api(d, warnings)
        self.assertTrue(any("not running" in w for w in warnings))

    def test_the_save_manager_is_passed_on(self):
        page = urlopen(self.base + "/dcbridge/", timeout=10)
        self.assertEqual((page.status, page.read()), (200, b"<html>manager</html>"))
        r = urlopen(self.base + "/dcbridge/api/export.zip", timeout=10)
        self.assertEqual((r.headers["Content-Type"], r.headers["Content-Disposition"]), ("application/zip", 'attachment; filename="x.zip"'))
        self.assertIsNone(r.headers["X-Secret"])                                    # only the type and the file name are passed back
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        self.assertIn(("GET", "/api/export.zip", b"", None), Fake.seen)

    def test_changes_come_as_post_and_reach_the_service_as_put_and_delete(self):
        r = self.post("/dcbridge/api/saves/T-1234N/2?_method=PUT&title=Hi", b"x" * 10, {"Content-Type": "application/octet-stream"})
        self.assertEqual(r.status, 202)
        self.assertIn(("PUT", "/api/saves/T-1234N/2?title=Hi", b"x" * 10, "application/octet-stream"), Fake.seen)
        self.post("/dcbridge/api/saves/T-1234N/2?_method=DELETE")
        self.assertEqual(Fake.seen[-1][:2], ("DELETE", "/api/saves/T-1234N/2"))
        self.post("/dcbridge/api/saves/T-1234N/2/label", b'{"label": "x"}', {"Content-Type": "application/json"})
        self.assertEqual(Fake.seen[-1][:2], ("POST", "/api/saves/T-1234N/2/label"))
        self.post("/dcbridge/api/saves/T-1234N/2?_method=PATCH")                       # not one of the two: a plain POST
        self.assertEqual(Fake.seen[-1][0], "POST")

    def test_only_the_save_managers_own_paths_are_passed_on(self):
        for bad in ("/dcbridge/../x", "/dcbridge/api/../../etc/passwd", "/dcbridge/other"):
            with self.assertRaises(HTTPError, msg=bad) as e:
                urlopen(self.base + bad, timeout=10)
            self.assertIn(e.exception.code, (400, 404))
        self.assertFalse([s for s in Fake.seen if "passwd" in s[1] or s[1].endswith("/x")])

    def test_a_change_needs_the_pin_while_settings_are_locked_and_a_page_header_always(self):
        import base_security as security
        with self.assertRaises(HTTPError) as e:
            urlopen(Request(self.base + "/dcbridge/api/saves/T-1/1?_method=DELETE", data=b"", method="POST", headers={"Origin": "http://evil.example"}), timeout=10)
        self.assertEqual(e.exception.code, 403)                                        # another site's form
        security.set_pin("4821")
        core.save_settings_pin(True)
        try:
            with self.assertRaises(HTTPError) as e:
                self.post("/dcbridge/api/saves/T-1/1?_method=DELETE")
            self.assertEqual(e.exception.code, 401)
            self.assertEqual(self.post("/dcbridge/api/saves/T-1/1?_method=DELETE", headers={"X-Pin": "4821"}).status, 202)
        finally:
            core.save_settings_pin(False)
            security.clear_pin()

    def test_the_service_being_down_is_a_clear_answer(self):
        port = dcb.PORT
        dcb.PORT = 1                                                                 # nothing listens there
        try:
            with self.assertRaises(HTTPError) as e:
                urlopen(self.base + "/dcbridge/", timeout=10)
            self.assertEqual(e.exception.code, 502)
        finally:
            dcb.PORT = port


if __name__ == "__main__":
    unittest.main()


class Installer(unittest.TestCase):
    """The module's installer pieces (they only run on a Pi; here they are read and parsed)."""
    def read(self, *p):
        import os
        from support import ROOT
        with open(os.path.join(ROOT, "modules", "dcbridge", *p)) as f:
            return f.read()

    def test_the_units_name_the_module_folder_and_the_service_listens_on_localhost_only(self):
        for unit in ("dcbridge-saves", "dcbridge-dcnet", "dcbridge-ppp"):
            self.assertIn("@MODULE@", self.read("system", unit + ".service"))
        self.assertIn("--host 127.0.0.1 --port 8085", self.read("system", "dcbridge-saves.service"))   # the dashboard passes the page on
        self.assertEqual(dcb.HOST, "127.0.0.1")

    def test_install_is_only_done_on_request_and_remove_keeps_the_users_saves(self):
        inst, rem = self.read("install.sh"), self.read("remove.sh")
        self.assertIn('"$DCBRIDGE" = on ] || dcb_is_on', inst)                                         # --dcbridge, or an update while the module is on
        self.assertIn('NS_SERVICES="$NS_SERVICES dcbridge-saves.service"', inst)
        self.assertNotIn("rm -rf /var/lib/dcbridge", rem)
        self.assertNotIn("/etc/default/dcbridge", rem.replace("# The saves (/var/lib/dcbridge) and the settings file /etc/default/dcbridge are kept: they are the user's.", ""))
        main = self.read("..", "..", "install.sh")
        for needle in ("--dcbridge) DCBRIDGE=on", "--no-dcbridge) DCBRIDGE=off", "DCBRIDGE=keep"):
            self.assertIn(needle, main)

    def test_nothing_of_dreampis_is_rewritten(self):
        for name in ("install.sh", "remove.sh"):
            text = self.read(name)
            for forbidden in ("/home/pi/dreampi", "/etc/ppp/options ", "dreampi.py", "netlink.py"):
                self.assertNotIn(forbidden, text, name)
