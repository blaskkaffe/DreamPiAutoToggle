"""The Snow background module: its settings (web side) and what the page gets in /api."""
import json
import threading
import unittest
from urllib.request import urlopen, Request

from support import web, core, sandbox, cleanup
import netswitch_snow as snow_web


class Snow(unittest.TestCase):
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
        return json.loads(urlopen(self.base + path, timeout=10).read().decode())

    def post(self, path, body):
        req = Request(self.base + path, data=json.dumps(body).encode(), method="POST", headers={"X-Requested-With": "test", "Content-Type": "application/json"})
        return json.loads(urlopen(req, timeout=10).read().decode())

    def test_defaults_and_choices(self):
        r = self.get("/snow")
        self.assertEqual(r["values"], {"amount": "normal", "wind": "breeze", "fog": "light", "time": "follow"})
        self.assertEqual([o["value"] for o in r["options"]["times"]], ["follow", "day", "night"])
        r = self.post("/snow", {"values": {"amount": "blizzard", "time": "night", "wind": "hurricane"}})      # a wind that is not offered is ignored
        self.assertEqual((r["values"]["amount"], r["values"]["time"], r["values"]["wind"]), ("blizzard", "night", "breeze"))
        self.assertEqual(snow_web.config()["amount"], "blizzard")

    def test_api_carries_the_snow_and_the_daylight(self):
        core.save_module_enabled("snow", True)
        web.refresh_page(force=True)
        d = self.get("/api")
        self.assertIn("snow", d)
        self.assertIn("elev", d["daylight"])
        self.assertIsInstance(d["daylight"]["day"], bool)

    def test_a_bad_config_file_gives_the_defaults(self):
        with open(snow_web.SNOW_CONFIG, "w") as f:
            f.write("[1, 2")
        self.assertEqual(snow_web.config(), snow_web.DEFAULT)


if __name__ == "__main__":
    unittest.main()
