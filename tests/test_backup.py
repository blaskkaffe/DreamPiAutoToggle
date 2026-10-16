"""Backup: the settings and the people in one zip, and the way back (Settings > System > Backup). Secrets stay out; a bad file changes nothing."""
import base64
import io
import json
import os
import threading
import unittest
import zipfile
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from support import web, core, sandbox, cleanup

import system_web as sw


def put(name, text):
    path = os.path.join(core.BASE_DIR, *name.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if isinstance(text, bytes) else "w") as f:
        f.write(text)


def zipped(files, info=True):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        if info:
            z.writestr(sw.INFO, "x")
        for n, c in files.items():
            z.writestr(n, c)
    return buf.getvalue()


class Backup(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        web.refresh_page(force=True)
        self.srv = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        cleanup(self.tmp)

    def call(self, method, path, body=None):
        h = {"X-Requested-With": "page", "Content-Type": "application/json"} if method == "POST" else {}
        try:
            r = urlopen(Request(self.base + path, data=body, method=method, headers=h), timeout=10)
            return r.status, r.read(), r
        except HTTPError as e:
            return e.code, e.read(), e

    def restore(self, data):
        status, body, _r = self.call("POST", "/backup/restore", json.dumps({"backup": base64.b64encode(data).decode()}).encode())
        return status, json.loads(body.decode())

    def test_download_holds_data_and_no_secrets(self):
        put("contacts.json", '{"people": []}')
        put("photos/p0123456789.jpg", b"\xff\xd8\xff")
        put("screens/hall/screen.json", "{}")
        put("time_zone", "Europe/Stockholm")
        for secret in ("admin_pin", "settings_pin", "https.key", "https.crt", "allowed_hosts", "project.json", "layout.json", "lang_sv.json", "update_origin"):
            put(secret, "secret")
        status, body, r = self.call("GET", "/backup")
        self.assertEqual(status, 200)
        self.assertEqual(r.headers["Content-Type"], "application/zip")
        self.assertIn("attachment; filename=\"backup-", r.headers["Content-Disposition"])
        names = set(zipfile.ZipFile(io.BytesIO(body)).namelist())
        self.assertEqual(names, {sw.INFO, "contacts.json", "photos/p0123456789.jpg", "screens/hall/screen.json", "time_zone", "language"})

    def test_round_trip_replaces_the_state(self):
        put("contacts.json", '{"people": [{"id": "a"}]}')
        put("photos/p0123456789.png", b"\x89PNG")
        backup = self.call("GET", "/backup")[1]
        put("contacts.json", '{"people": []}')
        put("snow.json", "{}")
        put("photos/pffffffffff.jpg", b"\xff\xd8")
        status, r = self.restore(backup)
        self.assertEqual((status, r["ok"]), (200, True))
        self.assertEqual(json.load(open(os.path.join(core.BASE_DIR, "contacts.json"))), {"people": [{"id": "a"}]})
        self.assertFalse(os.path.exists(os.path.join(core.BASE_DIR, "snow.json")))              # the backup did not have it
        self.assertFalse(os.path.exists(os.path.join(core.BASE_DIR, "photos", "pffffffffff.jpg")))
        self.assertTrue(os.path.exists(os.path.join(core.BASE_DIR, "photos", "p0123456789.png")))

    def test_bad_files_change_nothing(self):
        put("contacts.json", '{"people": [{"id": "keep"}]}')
        before = open(os.path.join(core.BASE_DIR, "contacts.json")).read()
        bad = [b"not a zip", zipped({"contacts.json": "{}"}, info=False), zipped({"contacts.json": "{not json"}),
               zipped({"contacts.json": "{}", "../evil.json": "{}"}), zipped({"contacts.json": "{}", "base_web.py": "x"}),
               zipped({"contacts.json": "{}", "admin_pin": "x"}), zipped({"contacts.json": "{}", "photos/../../x.jpg": "x"}),
               zipped({"contacts.json": "{}", "screens/../x.json": "{}"}), zipped({"contacts.json": "{}", "/abs.json": "{}"})]
        for data in bad:
            status, r = self.restore(data)
            self.assertEqual((status, r["ok"]), (400, False), data[:30])
        self.assertEqual(open(os.path.join(core.BASE_DIR, "contacts.json")).read(), before)
        self.assertEqual(self.call("POST", "/backup/restore", b"{}")[0], 400)

    def test_settings_address_serves_the_page_and_the_cogwheel_can_be_hidden(self):
        home = self.call("GET", "/")[1]
        for path in ("/settings", "/settings/"):
            status, body, _r = self.call("GET", path)
            self.assertEqual((status, body), (200, home))                     # the page itself: it opens Settings by itself
        self.assertEqual(self.call("POST", "/screen/nocog", json.dumps({"value": True}).encode())[0], 200)
        self.assertTrue(json.loads(self.call("GET", "/api")[1].decode())["screen"]["nocog"])
        self.assertEqual(self.call("POST", "/screen/nocog", json.dumps({"value": "yes"}).encode())[0], 200)      # not a boolean: ignored
        self.assertTrue(json.loads(self.call("GET", "/api")[1].decode())["screen"]["nocog"])

    def test_restore_needs_the_pin_when_one_is_set(self):
        self.assertIn("/backup/restore", sw.PROTECTED)
        self.assertTrue(web.modules.protected("/backup/restore"))


if __name__ == "__main__":
    unittest.main()
