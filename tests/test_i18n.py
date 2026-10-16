"""The language of the page: the Swedish dictionaries (base/lang_sv.json and modules/*/lang_sv.json) cover every text of the layouts, their patterns are
valid, and the language setting works over HTTP (/language, the page, /api)."""
import glob
import json
import os
import re
import threading
import unittest
from urllib.request import urlopen, Request

from support import ROOT, web, core, sandbox, cleanup

# keys of a layout.json that are not texts (names, paths, switches, keys into the data)
NOT_TEXT = {"type", "box", "id", "key", "post", "get", "url", "bind", "mod", "name", "module", "source", "in", "look", "href", "html_file", "html", "show", "hide", "icon",
            "options", "values", "default", "body", "cls", "items", "control", "below", "data", "every", "when", "hook", "reload", "then", "reopen", "method", "fields",
            "step", "min", "max", "unit", "scale", "colour", "position", "sub_text", "mode", "retry_if", "toggle", "status", "order", "arm_post", "style", "disabled", "lines", "rules"}


def dictionary(paths):
    out = {"strings": {}, "patterns": []}
    for p in paths:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        out["strings"].update(d.get("strings", {}))
        out["patterns"] += d.get("patterns", [])
    return out


def texts_of(o, found):
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, str):
                if k not in NOT_TEXT and not v.startswith(("@", "/")) and re.search("[A-Za-z]{3}", v):
                    found.add(v)
            elif k not in ("rules",):
                texts_of(v, found)
    elif isinstance(o, list):
        for v in o:
            texts_of(v, found)


class Dictionaries(unittest.TestCase):
    def files(self):
        return [os.path.join(ROOT, "base", "lang_sv.json")] + sorted(glob.glob(os.path.join(ROOT, "modules", "*", "lang_sv.json")))

    def test_the_files_are_valid(self):
        for p in self.files():
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            self.assertIsInstance(d["strings"], dict, p)
            self.assertTrue(all(isinstance(k, str) and isinstance(v, str) and v for k, v in d["strings"].items()), p)
            for rx, tpl in d["patterns"]:
                n = re.compile(rx).groups
                for m in re.findall(r"\$(\d)", tpl) + re.findall(r"\{(\d)\?", tpl):
                    self.assertLessEqual(int(m), n, "%s: %s uses a part the pattern does not have" % (p, rx))

    def test_every_text_of_a_layout_is_translated(self):
        d = dictionary(self.files())
        found = set()
        for path in [os.path.join(ROOT, "base", "layout.json")] + sorted(glob.glob(os.path.join(ROOT, "modules", "*", "layout.json"))):
            with open(path, encoding="utf-8") as f:
                texts_of(json.load(f), found)
        for path in sorted(glob.glob(os.path.join(ROOT, "modules", "*", "module.json"))):
            with open(path, encoding="utf-8") as f:
                m = json.load(f)
            found.update(x for x in (m.get("name"), m.get("description"), m.get("short")) if x)
        missing = sorted(t for t in found if t not in d["strings"] and not any(re.search(rx, t) for rx, _ in d["patterns"]))
        self.assertEqual(missing, [], "texts with no Swedish translation:\n" + "\n".join(missing))

    def test_a_translation_keeps_its_numbers_and_names(self):
        d = dictionary(self.files())
        for en, sv in d["strings"].items():
            for token in re.findall(r"INNE|UTE|\.wav|\.mp3|\.ogg|/opt/checkin-board/sounds|install\.sh|CSV|GitHub|PIN|åååå-mm-dd|tt:mm", en):
                self.assertIn(token.replace("PIN", "PIN"), sv, "%r lost %s" % (en, token))


class Setting(unittest.TestCase):
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
        return urlopen(self.base + path, timeout=10).read().decode("utf-8")

    def post(self, path, body):
        req = Request(self.base + path, data=json.dumps(body).encode(), method="POST", headers={"X-Requested-With": "page", "Content-Type": "application/json"})
        return urlopen(req, timeout=10)

    def test_the_language_is_chosen_in_settings_and_reaches_the_page(self):
        self.assertEqual(json.loads(self.get("/language"))["values"]["language"], "en")          # the tests start in English
        self.assertEqual(json.loads(self.get("/api"))["lang"], "en")
        self.assertIn('<html lang="en"', self.get("/"))
        self.assertIn('"lang": "en", "strings": {}', self.get("/"))
        self.post("/language", {"values": {"language": "sv"}})
        self.assertEqual(json.loads(self.get("/api"))["lang"], "sv")
        page = self.get("/")
        self.assertIn('<html lang="sv"', page)
        self.assertIn('"Inställningar"', page)                                                   # the dictionary is in the page
        self.assertIn('"Kontakter"', page)                                                       # and a module's too
        self.post("/language", {"values": {"language": "en"}})
        self.assertEqual(json.loads(self.get("/api"))["lang"], "en")

    def test_an_unknown_language_is_refused(self):
        from urllib.error import HTTPError
        with self.assertRaises(HTTPError) as e:
            self.post("/language", {"values": {"language": "xx"}})
        self.assertEqual(e.exception.code, 400)
        self.assertEqual(json.loads(self.get("/language"))["values"]["language"], "en")

    def test_a_new_install_is_swedish_unless_chosen(self):
        os.remove(core.LANGUAGE)
        self.assertEqual(core.language(), "sv")                                                  # "language" in project.json
        core.save_language("en")


if __name__ == "__main__":
    unittest.main()
