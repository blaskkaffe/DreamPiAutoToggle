"""The /tag message for openMenu and the reboot button's endpoint."""
import json
import os
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen, Request

from support import core, probes, web, sandbox, cleanup


class TagTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        self._hp, self._dp = core.hook_problem, core.dcnet_problem
        core.hook_problem = lambda: None
        core.dcnet_problem = lambda: None

    def tearDown(self):
        core.hook_problem, core.dcnet_problem = self._hp, self._dp
        cleanup(self.tmp)

    def test_codes(self):
        self.assertEqual(core.tag(), "DCNOW")
        open(core.FLAG, "w").close()
        self.assertEqual(core.tag(), "DCNET")
        core.dcnet_problem = lambda: "DCNET is not enabled"
        self.assertEqual(core.tag(), "DCNET_OFF")        # selected but DreamPi will send calls to DCNow!
        os.remove(core.FLAG)
        self.assertEqual(core.tag(), "DCNOW")
        core.hook_problem = lambda: "not loaded"
        self.assertEqual(core.tag(), "INACTIVE")

    def test_every_code_has_a_text_entry(self):
        for code in ("DCNET", "DCNOW", "DCNET_OFF", "INACTIVE"):
            self.assertIn(code, dict(core.TAGS))
        self.assertEqual(dict(core.TAGS)["DCNET"], "Running DCNet!")

    def test_the_answer_is_tiny(self):
        for code, _text in core.TAGS:
            self.assertLess(len(code) + 1, 24)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = sandbox()
        cls._hp, cls._dp = core.hook_problem, core.dcnet_problem
        core.hook_problem = lambda: None
        core.dcnet_problem = lambda: None
        cls.srv = web.Server(("127.0.0.1", 0), web.Handler)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.spawned = []
        cls._spawn = probes._spawn_reboot
        probes._spawn_reboot = lambda: cls.spawned.append(1)

    @classmethod
    def tearDownClass(cls):
        probes._spawn_reboot = cls._spawn
        core.hook_problem, core.dcnet_problem = cls._hp, cls._dp
        cls.srv.shutdown()
        cls.srv.server_close()
        cleanup(cls.tmp)

    def setUp(self):
        del self.spawned[:]

    def get(self, path):
        r = urlopen(self.base + path, timeout=10)
        return r.headers, r.read().decode()

    def test_tag_endpoint(self):
        open(core.FLAG, "w").close()
        headers, body = self.get("/tag")
        self.assertEqual(body, "DCNET\n")
        self.assertIn("text/plain", headers["Content-Type"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(self.get("/tag?text")[1], "Running DCNet!\n")
        os.remove(core.FLAG)
        self.assertEqual(self.get("/tag")[1], "DCNOW\n")

    def test_status_text_has_the_tag(self):
        self.assertIn("\ntag=DCNOW\n", self.get("/status")[1])

    def test_reboot_needs_the_page_header(self):
        with self.assertRaises(HTTPError) as cm:
            urlopen(Request(self.base + "/reboot", data=b"", method="POST"), timeout=10)
        self.assertEqual(cm.exception.code, 403)
        self.assertEqual(self.spawned, [])

    def test_reboot_from_the_page(self):
        req = Request(self.base + "/reboot", data=b"", method="POST", headers={"X-Requested-With": "netswitch"})
        out = json.loads(urlopen(req, timeout=10).read().decode())
        self.assertEqual(out, {"started": True, "message": "Rebooting"})
        self.assertEqual(self.spawned, [1])

    def test_reboot_failure_is_reported(self):
        def boom():
            raise OSError("no sh")
        saved, probes._spawn_reboot = probes._spawn_reboot, boom
        try:
            req = Request(self.base + "/reboot", data=b"", method="POST", headers={"X-Requested-With": "netswitch"})
            out = json.loads(urlopen(req, timeout=10).read().decode())
        finally:
            probes._spawn_reboot = saved
        self.assertFalse(out["started"])


if __name__ == "__main__":
    unittest.main()
