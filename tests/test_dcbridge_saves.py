"""Tests for the dcbridge module's Pi side without hardware: image creation, the save store, the disk-server request handler and the
web API of the save manager (modules/dcbridge/dcbridge_saves). Needs mtools + dosfstools (skipped without them)."""
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest

import support  # noqa: F401,E402   (puts the module folders on the path)

from dcbridge_saves import VMU_SIZE, protocol as P                     # noqa: E402
from dcbridge_saves.fatimage import create_image, FatImage, partition_offset  # noqa: E402
from dcbridge_saves.store import SaveStore, StoreError                  # noqa: E402
from dcbridge_saves.daemon import Service                               # noqa: E402
from dcbridge_saves.web import make_app                                 # noqa: E402


def vmu(seed):
    return bytes((i * 31 + seed) & 0xFF for i in range(VMU_SIZE))


def call(app, method, path, body=b"", query=""):
    env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query,
           "CONTENT_LENGTH": str(len(body)), "wsgi.input": io.BytesIO(body)}
    st = {}

    def start(status, headers):
        st["status"], st["headers"] = status, dict(headers)
    out = b"".join(app(env, start))
    return int(st["status"][:3]), st["headers"], out


@unittest.skipUnless(shutil.which("mdir") and shutil.which("mkfs.fat") or os.path.exists("/usr/sbin/mkfs.fat"), "needs mtools and dosfstools")
class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.img = os.path.join(self.tmp, "sd.img")
        self.fat = create_image(self.img, 64)
        self.store = SaveStore(os.path.join(self.tmp, "state"))
        self.svc = Service(self.img, self.store, None)
        self.fd = os.open(self.img, os.O_RDWR)

    def tearDown(self):
        os.close(self.fd)
        shutil.rmtree(self.tmp)

    def openmenu_writes(self, serial, slot, data, title=None):
        """What openMenu does on the Dreamcast (here straight into the image)."""
        self.fat.write("/OPENMENU/SAVES/%s/SLOT%d.VMU" % (serial, slot), data)
        if title:
            self.fat.write("/OPENMENU/SAVES/%s/TITLE.TXT" % serial, title.encode())
        self.fat.write("/OPENMENU/LASTDISC.TXT", ("%s-%d" % (serial, slot)).encode())

    def session(self, idle_ms):
        r = self.svc.handle(P.SESSION, struct.pack("<II", 7, idle_ms), self.fd)
        f = list(P.FrameReader().feed(r))[0]
        return struct.unpack("<III", f[1])


class ImageTests(Base):
    def test_layout(self):
        self.assertEqual(partition_offset(self.img), 2048 * 512)
        self.assertEqual(os.path.getsize(self.img), 64 << 20)
        with open(self.img, "rb") as f:
            mbr = f.read(512)
        self.assertEqual(mbr[446 + 4], 0x0C)
        self.assertTrue(self.fat.exists("/OPENMENU/SAVES"))
        # KOS CSD: C_SIZE = sectors/1024 - 1 must be exact
        self.assertEqual((os.path.getsize(self.img) // 512) % 1024, 0)


class StoreTests(Base):
    def test_scan_and_history(self):
        self.openmenu_writes("T-36802N", 1, vmu(1), "Sonic Adventure 2")
        self.assertEqual(self.store.rescan(self.fat), [("T-36802N", 1)])
        s = self.store.summary()
        g = s["games"][0]
        self.assertEqual((g["serial"], g["title"]), ("T-36802N", "Sonic Adventure 2"))
        self.assertTrue(g["slots"][0]["valid"] and g["slots"][0]["lastdisc"])
        self.assertEqual(self.store.rescan(self.fat), [])                 # unchanged: no new version
        self.openmenu_writes("T-36802N", 1, vmu(2))
        self.assertEqual(self.store.rescan(self.fat), [("T-36802N", 1)])
        self.assertEqual(len(self.store.history_list("T-36802N", 1)), 2)

    def test_queue_validation(self):
        with self.assertRaises(StoreError):
            self.store.queue_put("T-1", 1, b"short")
        with self.assertRaises(StoreError):
            self.store.queue_put("../etc", 1, vmu(0))
        with self.assertRaises(StoreError):
            self.store.queue_put("T-1", 6, vmu(0))

    def test_edits_only_on_cold_session(self):
        self.openmenu_writes("MK-51058", 2, vmu(5))
        self.store.rescan(self.fat)
        self.store.queue_put("MK-51058", 2, vmu(9))
        self.store.queue_label("MK-51058", 2, "Before final boss")

        sid, sectors, flags = self.session(200)                           # KOS re-init: hands off
        self.assertEqual(flags, 0)
        self.assertEqual(self.fat.read("/OPENMENU/SAVES/MK-51058/SLOT2.VMU"), vmu(5))
        self.assertEqual(len(self.store.pending_list()), 2)

        sid, sectors, flags = self.session(8000)                          # cold boot: apply
        self.assertEqual((sid, sectors, flags), (7, (64 << 20) // 512, P.FLAG_INVALIDATE))
        self.assertEqual(self.fat.read("/OPENMENU/SAVES/MK-51058/SLOT2.VMU"), vmu(9))
        self.assertEqual(self.fat.read("/OPENMENU/SAVES/MK-51058/SLOT2.TXT"), b"Before final boss")
        self.assertEqual(self.store.pending_list(), [])
        import hashlib
        shas = [h["sha1"] for h in self.store.history_list("MK-51058", 2)]
        self.assertIn(hashlib.sha1(vmu(5)).hexdigest()[:8], shas)        # old card copy kept
        self.assertEqual(self.store.history_list("MK-51058", 2)[0]["reason"], "upload")

    def test_new_game_and_delete(self):
        self.store.queue_put("HDR-0000", 3, vmu(3), title="Homebrew")
        self.session(9000)
        self.assertEqual(self.fat.read("/OPENMENU/SAVES/HDR-0000/TITLE.TXT"), b"Homebrew")
        self.store.queue_delete("HDR-0000", 3)
        self.session(9000)
        self.assertIsNone(self.fat.read("/OPENMENU/SAVES/HDR-0000/SLOT3.VMU"))
        hist = self.store.history_list("HDR-0000", 3)
        self.assertEqual(self.store.history_get("HDR-0000", 3, hist[0]["id"]), vmu(3))


class DiskTests(Base):
    def test_read_write_frames(self):
        r = self.svc.handle(P.READ, struct.pack("<IH", 0, 4), self.fd)
        frames = P.FrameReader().feed(r)
        self.assertEqual([f[0] for f in frames], [P.DATA] * 4)
        with open(self.img, "rb") as f:
            self.assertEqual(frames[0][1][4:], f.read(512))
        sec = bytes(range(256)) * 2
        r = self.svc.handle(P.WRITE, struct.pack("<I", 4000) + sec, self.fd)
        self.assertEqual(P.FrameReader().feed(r), [(P.WACK, struct.pack("<I", 4000))])
        self.assertEqual(os.pread(self.fd, 512, 4000 * 512), sec)

    def test_the_last_requests_are_kept_for_diagnosis(self):
        self.svc.handle(P.SESSION, struct.pack("<II", 1, 99999), self.fd)
        self.svc.handle(P.READ, struct.pack("<IH", 2048, 1), self.fd)
        self.svc.handle(P.WRITE, struct.pack("<I", 4000) + bytes(512), self.fd)
        self.assertEqual(self.svc.status["recent"][-2:], ["read 2048 x1", "write 4000 x1"])
        for i in range(40):
            self.svc.handle(P.READ, struct.pack("<IH", i, 1), self.fd)
        self.assertEqual(len(self.svc.status["recent"]), 16)

    def test_frame_resync(self):
        rd = P.FrameReader()
        junk = b"\x00\xD5\x11" + P.frame(P.HELLO, b"\x01\x00") + b"\xD5"
        self.assertEqual(rd.feed(junk), [(P.HELLO, b"\x01\x00")])
        self.assertEqual(rd.feed(b"\xC3\x83\x00\x04\x00abcd"), [(P.WACK, b"abcd")])


class WebTests(Base):
    def test_api_roundtrip(self):
        app = make_app(self.svc)
        self.openmenu_writes("T-36802N", 1, vmu(1), "Sonic Adventure 2")
        self.store.rescan(self.fat)
        code, h, body = call(app, "GET", "/api/saves")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body.decode())["games"][0]["serial"], "T-36802N")
        code, h, body = call(app, "GET", "/api/saves/T-36802N/1")
        self.assertEqual((code, body), (200, vmu(1)))
        code, h, body = call(app, "PUT", "/api/saves/T-36802N/1", vmu(4))
        j = json.loads(body.decode())
        self.assertEqual(code, 202)
        self.assertTrue(j["warning"])                                     # it's the last-played slot
        code, h, body = call(app, "PUT", "/api/saves/T-36802N/2", b"nope")
        self.assertEqual(code, 400)
        code, h, body = call(app, "GET", "/api/saves/T-36802N/1/history")
        hid = json.loads(body.decode())[0]["id"]
        code, h, body = call(app, "POST", "/api/saves/T-36802N/1/history/%s/restore" % hid)
        self.assertEqual(code, 202)
        code, h, body = call(app, "GET", "/api/pending")
        self.assertEqual(len(json.loads(body.decode())), 2)
        code, h, body = call(app, "GET", "/api/export.zip")
        self.assertEqual(code, 200)
        self.assertTrue(body.startswith(b"PK"))
        code, h, body = call(app, "GET", "/")
        self.assertIn(b"Dreamcast", body)
        code, h, body = call(app, "GET", "/api/saves/..%2Fx/1")
        self.assertEqual(code, 400)                                       # rejected serial


class BridgeTests(unittest.TestCase):
    def test_ctl_status_line(self):
        import time
        from dcbridge_saves.bridge import BridgeStatus
        m, sl = os.openpty()
        b = BridgeStatus(os.ttyname(sl), conf_path="/nonexistent")
        b.start()
        time.sleep(0.3)
        os.write(m, b'junk\r\n{"fw":"dcbridge-0.2","mode":"sense","spi":"sd","sd":{"ready":true}}\r\n')
        for _ in range(30):
            if b.firmware:
                break
            time.sleep(0.1)
        snap = b.snapshot()
        self.assertEqual(snap["summary"], "SD card")
        self.assertEqual(snap["links"]["ppp"]["interface"], "ppp10")
        b.stop()

    def test_a_client_that_hangs_up_leaves_no_traceback(self):
        import contextlib, io, socket, threading, time
        from dcbridge_saves import __main__ as m
        srv = m.ThreadingWSGIServer(("127.0.0.1", 0), m.QuietHandler)

        def app(env, start):
            time.sleep(0.4)
            start("200 OK", [])
            return [b"x"]
        srv.set_app(app)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                c = socket.create_connection(("127.0.0.1", srv.server_address[1]))
                c.sendall(b"GET / HTTP/1.0\r\n\r\n")
                c.close()
                time.sleep(1.0)
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertNotIn("Traceback", err.getvalue())

    def test_why_there_is_no_status(self):
        import tempfile, shutil
        from dcbridge_saves import bridge
        tmp = tempfile.mkdtemp()
        try:
            usb = os.path.join(tmp, "usb")
            os.makedirs(os.path.join(usb, "1-1"))
            for name, val in (("idVendor", "1209"), ("idProduct", "0001")):
                with open(os.path.join(usb, "1-1", name), "w") as f:
                    f.write(val + "\n")
            os.makedirs(os.path.join(usb, "1-2"))
            self.assertTrue(bridge.usb_seen(usb))
            os.remove(os.path.join(usb, "1-1", "idProduct"))
            self.assertFalse(bridge.usb_seen(usb))                       # another device: not the board
            self.assertIsNone(bridge.usb_seen(os.path.join(tmp, "none")))
            ctl = os.path.join(tmp, "dcbridge-ctl")
            self.assertEqual(bridge.device_nodes(ctl), {"uart": False, "ctl": False, "disk": False})
            open(ctl, "w").close()
            self.assertTrue(bridge.device_nodes(ctl)["ctl"])
            snap = bridge.BridgeStatus(ctl, conf_path="/nonexistent").snapshot()      # no status line yet: it says what it found
            self.assertIn("usb", snap)
            self.assertTrue(snap["devices"]["ctl"])
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
