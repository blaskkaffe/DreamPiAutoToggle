"""Button sounds (Appearance > Button sound): the base's own sound files, any .wav / .mp3 / .ogg copied in by hand, GET /sounds/<name>,
and the three settings in screen.json."""
import os
import shutil
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from support import ROOT, web, core, sandbox, cleanup


class ButtonSounds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = sandbox()
        os.makedirs(core.SOUNDS_DIR)
        folder = os.path.join(ROOT, "base", "sounds")
        for name in os.listdir(folder):
            shutil.copy(os.path.join(folder, name), core.SOUNDS_DIR)
        cls.srv = web.Server(("127.0.0.1", 0), web.Handler)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cleanup(cls.tmp)

    def test_the_shipped_sounds_are_listed_and_served_and_more_can_be_copied_in(self):
        self.assertEqual(core.list_sounds(), ["bubble.wav", "pop.wav", "tick.wav"])
        r = urlopen(self.base + "/sounds/pop.wav", timeout=10)
        self.assertEqual((r.status, r.headers["Content-Type"]), (200, "audio/wav"))
        self.assertEqual(r.read()[:4], b"RIFF")
        with open(os.path.join(core.SOUNDS_DIR, "my click.mp3"), "wb") as f:
            f.write(b"ID3")
        with open(os.path.join(core.SOUNDS_DIR, "notes.txt"), "w") as f:
            f.write("x")
        self.assertIn("my click.mp3", core.list_sounds())
        self.assertNotIn("notes.txt", core.list_sounds())                                    # only sound files
        self.assertEqual(urlopen(self.base + "/sounds/my%20click.mp3", timeout=10).headers["Content-Type"], "audio/mpeg")
        for bad in ("notes.txt", "..%2Fscreen.json", "nope.wav"):
            with self.assertRaises(HTTPError, msg=bad) as e:
                urlopen(self.base + "/sounds/" + bad, timeout=10)
            self.assertEqual(e.exception.code, 404)

    def test_the_sound_settings(self):
        d = core.screen_settings()
        self.assertEqual((d["sound"], d["sound_name"], d["sound_volume"]), (True, "pop.wav", 0.6))
        self.assertEqual(core.save_screen_settings({"sound": False, "sound_volume": 7, "sound_name": "tick.wav"})["sound_volume"], 1.0)
        self.assertEqual(core.save_screen_settings({"sound_name": "../x"})["sound_name"], "tick.wav")      # not a plain file name: unchanged
        self.assertEqual(core.save_screen_settings({"sound_volume": True})["sound_volume"], 1.0)           # a boolean is not a volume
        self.assertFalse(core.screen_settings()["sound"])
        core.save_screen_settings({"sound": True, "sound_volume": 0.6, "sound_name": "pop.wav"})

    def test_the_form_lists_the_sounds_and_the_toggle_has_its_route(self):
        import json
        from urllib.request import Request
        form = json.loads(urlopen(self.base + "/screen", timeout=10).read().decode())
        self.assertIn("pop.wav", [o["value"] for o in form["options"]["sounds"]])
        self.assertEqual(form["values"]["sound_volume"], 0.6)
        req = Request(self.base + "/screen/sound", data=json.dumps({"value": False}).encode(), method="POST",
                      headers={"X-Requested-With": "x", "Content-Type": "application/json"})
        self.assertEqual(urlopen(req, timeout=10).status, 200)
        self.assertFalse(core.screen_settings()["sound"])
        self.assertIn("(off)", json.loads(urlopen(self.base + "/screen", timeout=10).read().decode())["texts"]["sound_name"])
        core.save_screen_settings({"sound": True})


if __name__ == "__main__":
    unittest.main()
