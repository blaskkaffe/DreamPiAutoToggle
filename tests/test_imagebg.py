"""The Background image module: the upload is checked by its first bytes, kept, served as an image, and removed again."""
import json
import os
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from support import web, core, sandbox, cleanup

import imagebg_web as ib

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 3000
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 3000
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 100


class ImageBg(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        core.save_module_enabled("imagebg", True)
        web.refresh_page(force=True)
        self.srv = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        cleanup(self.tmp)

    def call(self, method, path, body=None, headers=None):
        h = {"X-Requested-With": "checkin"} if method == "POST" else {}
        h.update(headers or {})
        try:
            r = urlopen(Request(self.base + path, data=body, method=method, headers=h), timeout=10)
            return r.status, r.read(), r
        except HTTPError as e:
            return e.code, e.read(), e

    def api(self):
        return json.loads(self.call("GET", "/api")[1].decode())["imagebg"]

    def test_sniffing(self):
        self.assertEqual((ib.sniff(PNG), ib.sniff(JPEG), ib.sniff(WEBP), ib.sniff(b"GIF89a....")), ("image/png", "image/jpeg", "image/webp", "image/gif"))
        for bad in (b"", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", b"<html><script>alert(1)</script>", b"RIFF....WAVE", b"MZ\x90\x00"):
            self.assertIsNone(ib.sniff(bad), bad)

    def test_no_picture_at_first(self):
        self.assertEqual(self.api(), {"has": False, "fit": "cover", "dim": 25, "version": 0})
        self.assertEqual(self.call("GET", "/imagebg/image")[0], 404)

    def test_upload_serve_and_remove(self):
        status, body, _r = self.call("POST", "/imagebg/upload", PNG, {"Content-Type": "application/octet-stream"})
        self.assertEqual(status, 200)
        v = json.loads(body.decode())
        self.assertTrue(v["has"] and v["version"] > 0)
        status, body, r = self.call("GET", "/imagebg/image?v=%d" % v["version"])
        self.assertEqual((status, body, r.headers["Content-Type"], r.headers["X-Content-Type-Options"]), (200, PNG, "image/png", "nosniff"))
        self.assertIsNone(r.headers.get("Content-Encoding"))                                   # pictures are not packed again
        self.assertEqual(self.api()["version"], v["version"])
        self.assertEqual(self.call("POST", "/imagebg/remove", b"{}")[0], 200)
        self.assertFalse(self.api()["has"])
        self.assertFalse(os.path.exists(ib.IMAGEBG_FILE))
        self.assertEqual(self.call("GET", "/imagebg/image")[0], 404)

    def test_only_pictures_are_taken(self):
        for bad in (b"hello", b"<svg onload=alert(1)>", b""):
            self.assertEqual(self.call("POST", "/imagebg/upload", bad)[0], 400, bad)
        self.assertFalse(self.api()["has"])
        self.assertFalse(os.path.exists(ib.IMAGEBG_FILE))

    def test_a_picture_that_is_too_big_is_refused(self):
        status, _b, _r = self.call("POST", "/imagebg/upload", PNG, {"Content-Length": str(ib.MAX_BYTES + 1)})
        self.assertIn(status, (413, 400))
        self.assertFalse(os.path.exists(ib.IMAGEBG_FILE))

    def test_the_type_comes_from_the_bytes_not_from_the_header(self):
        self.call("POST", "/imagebg/upload", JPEG, {"Content-Type": "text/html"})
        self.assertEqual(self.call("GET", "/imagebg/image")[2].headers["Content-Type"], "image/jpeg")

    def test_fit_and_darken(self):
        reply = json.loads(self.call("POST", "/imagebg", json.dumps({"values": {"fit": "tile", "dim": 50}}).encode())[1].decode())
        self.assertEqual(reply["values"], {"fit": "tile", "dim": 50})
        self.assertEqual((self.api()["fit"], self.api()["dim"]), ("tile", 50))
        self.call("POST", "/imagebg", json.dumps({"values": {"fit": "evil", "dim": 99}}).encode())          # not one of the choices: kept
        self.assertEqual((self.api()["fit"], self.api()["dim"]), ("tile", 50))
        form = json.loads(self.call("GET", "/imagebg")[1].decode())
        self.assertEqual([o["value"] for o in form["options"]["dims"]], [0, 25, 50, 75])

    def test_a_missing_file_means_no_picture(self):
        self.call("POST", "/imagebg/upload", PNG)
        os.remove(ib.IMAGEBG_FILE)
        self.assertFalse(self.api()["has"])

    def test_a_cross_site_upload_is_refused(self):
        self.assertEqual(self.call("POST", "/imagebg/upload", PNG, {"Origin": "http://evil.example"})[0], 403)

    def test_the_module_is_a_background_with_settings(self):
        lay = json.loads(self.call("GET", "/")[1].decode().split("window.LAYOUT=")[1].split(";\n")[0])
        self.assertEqual([b["mod"] for b in lay["backgrounds"]], ["imagebg"])
        appearance = [b for b in lay["settings"] if b["id"] == "appearance"][0]
        menu = [w for w in appearance["items"] if w["type"] == "menu" and w["id"] == "background"][0]
        self.assertTrue(any(w["mod"] == "imagebg" and w.get("name") == "imagebg-pick" for w in menu["items"]))      # its settings are in Appearance > Background


if __name__ == "__main__":
    unittest.main()
