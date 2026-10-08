"""The Colour palette module: add, edit, rename, rearrange, delete and reset colours, what happens to what used a deleted colour, and the palette in /api."""
import json
import os
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from support import web, core, sandbox, cleanup



class PaletteCore(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()

    def tearDown(self):
        cleanup(self.tmp)

    def ids(self):
        return [c["id"] for c in core.colours() if not c.get("token")]            # the palette (the switcher's Selected network is not in it)

    def test_the_shipped_palette_is_what_is_used_to_begin_with(self):
        self.assertEqual(tuple(self.ids()), core.PALETTE_IDS)
        self.assertEqual(core.palette_ids(), core.PALETTE_IDS)

    def test_add_edit_and_use_a_custom_colour(self):
        ident = core.palette_add("Hot  Pink!", "#FF00AA")
        self.assertEqual(ident, "hot-pink")
        c = core.colour("hot-pink")
        self.assertEqual((c["name"], c["ui"], c["group"]), ("Hot Pink!", "#ff00aa", "custom"))
        self.assertEqual(self.ids()[-1], "hot-pink")
        self.assertEqual(core.palette_add("Hot Pink", "#112233"), "hot-pink-2")                 # the same name again: another id
        self.assertEqual(core.palette_add("1 2 3", "#112233"), "colour-1-2-3")                  # an id starts with a letter
        self.assertIsNone(core.palette_add("x", "red"))                                         # not a colour
        self.assertTrue(core.palette_edit("hot-pink", name="Hotter", ui="#aa0000"))
        self.assertEqual((core.colour("hot-pink")["name"], core.colour("hot-pink")["ui"]), ("Hotter", "#aa0000"))
        self.assertIsNotNone(core.set_module_colour("checkin", "checkin", "hot-pink"))              # a module can pick it
        self.assertEqual(core.module_colours("checkin")["checkin"], "hot-pink")
        self.assertIn("--c-hot-pink:#aa0000", core.colours_css())

    def test_edit_a_shipped_colour(self):
        self.assertTrue(core.palette_edit("red", name="Cherry", ui="#c00000"))
        c = core.colour("red")
        self.assertEqual((c["name"], c["ui"]), ("Cherry", "#c00000"))
        self.assertTrue(core.palette_edit("global", name="Main"))                               # Global main can be renamed and recoloured
        self.assertFalse(core.palette_edit("nope", name="x"))
        self.assertFalse(core.palette_edit("red", ui="not a colour"))

    def test_rearrange(self):
        self.assertTrue(core.palette_order(["blue", "green", "nope"]))
        self.assertEqual(self.ids()[:3], ["blue", "green", "global"])                           # the rest keeps its order, after them
        self.assertEqual(sorted(self.ids()), sorted(core.PALETTE_IDS))
        self.assertFalse(core.palette_order("blue"))

    def test_delete_and_what_used_it(self):
        for fixed in core.FIXED_COLOURS + ("network",):
            self.assertFalse(core.palette_delete(fixed), fixed)
        self.assertTrue(core.palette_delete("blue"))
        self.assertNotIn("blue", self.ids())
        self.assertIn(core.module_colours("checkin")["checkin"], self.ids())
        self.assertIsNone(core.set_module_colour("checkin", "checkin", "blue"))                     # and it can not be picked any more
        self.assertEqual(core.colour("blue")["id"], "orange")                                   # an old reference draws the fallback
        core.set_module_colour("checkin", "checkin", "red")
        self.assertTrue(core.palette_delete("red"))
        self.assertNotEqual(core.module_colours("checkin")["checkin"], "red")
        self.assertTrue(core.palette_delete("green"))

    def test_reset(self):
        core.palette_add("Mine", "#123456")
        core.palette_delete("cyan")
        core.palette_edit("red", name="Cherry", ui="#c00000")
        core.palette_order(["blue"])
        self.assertTrue(core.palette_reset("red"))                                              # one shipped colour
        self.assertEqual((core.colour("red")["name"], core.colour("red")["ui"]), ("Red", "#d9363e"))
        self.assertNotIn("cyan", self.ids())
        self.assertFalse(core.palette_reset("mine"))                                            # not one the add-on ships
        self.assertTrue(core.palette_reset())
        self.assertEqual(tuple(self.ids()), core.PALETTE_IDS)
        self.assertFalse(os.path.exists(core.PALETTE_CUSTOM))
        self.assertEqual(core.palette_overrides(), {})

    def test_the_version_follows_the_palette(self):
        v = core.palette_version()
        core.palette_edit("red", ui="#c00000")
        self.assertNotEqual(core.palette_version(), v)
        self.assertEqual(core.palette_version(), core.palette_version())

    def test_a_damaged_file_is_ignored(self):
        open(core.PALETTE_CUSTOM, "w").write('{"custom": [{"id": "Bad Id", "ui": "#112233"}, 5, {"id": "ok", "ui": "nope"}], "deleted": ["global", "red", 7], "order": "x", "names": []}')
        self.assertNotIn("red", self.ids())                                                      # a valid deletion still counts
        self.assertIn("global", self.ids())                                                      # a fixed one never goes
        self.assertEqual([c for c in self.ids() if c not in core.PALETTE_IDS], [])
        open(core.PALETTE_CUSTOM, "w").write("[1,")
        self.assertEqual(tuple(self.ids()), core.PALETTE_IDS)


class PaletteHttp(unittest.TestCase):
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
        req = Request(self.base + path, data=None if body is None else json.dumps(body).encode(), method=method, headers={"X-Requested-With": "checkin"} if method == "POST" else {})
        try:
            r = urlopen(req, timeout=10)
            return r.status, json.loads(r.read().decode() or "null")
        except HTTPError as e:
            return e.code, None

    def test_the_editor_end_to_end(self):
        st, got = self.call("GET", "/palette/list")
        self.assertEqual(st, 200)
        self.assertEqual([c["id"] for c in got["colours"]], list(core.PALETTE_IDS))
        self.assertTrue(all(c["fixed"] for c in got["colours"] if c["id"] in ("global", "orange")))
        self.assertTrue(all("led" not in c for c in got["colours"]))
        st, got = self.call("POST", "/palette/add", {"name": "Lime", "ui": "#99ff00"})
        self.assertEqual((st, got["id"]), (200, "lime"))
        self.assertEqual(got["colours"][-1]["custom"], True)
        self.call("POST", "/palette/edit", {"id": "lime", "name": "Lime time", "ui": "#88ff00"})
        self.call("POST", "/palette/edit", {"id": "red", "ui": "#c00000"})
        st, got = self.call("POST", "/palette/order", {"order": ["lime", "red"]})
        self.assertEqual([c["id"] for c in got["colours"]][:2], ["lime", "red"])
        red = [c for c in got["colours"] if c["id"] == "red"][0]
        self.assertTrue(red["changed"])
        self.assertEqual(self.call("POST", "/palette/delete", {"id": "orange"})[0], 400)
        self.assertEqual(self.call("POST", "/palette/delete", {"id": "lime"})[0], 200)
        self.assertEqual(self.call("POST", "/palette/edit", {"id": "red", "ui": "nope"})[0], 400)
        self.assertEqual(self.call("POST", "/palette/reset", {})[0], 200)
        st, got = self.call("GET", "/palette/list")
        self.assertEqual([c["id"] for c in got["colours"]], list(core.PALETTE_IDS))

    def test_a_cross_site_post_is_refused(self):
        req = Request(self.base + "/palette/reset", data=b"{}", method="POST", headers={"Origin": "http://evil.example", "X-Requested-With": "x"})
        with self.assertRaises(HTTPError) as e:
            urlopen(req, timeout=10)
        self.assertEqual(e.exception.code, 403)

    def test_the_page_gets_the_palette_when_it_changed(self):
        st, api = self.call("GET", "/api")
        self.assertIn("palette", api)
        self.assertIn("palette_css", api)
        v = api["palette_v"]
        self.assertEqual(len(api["palette"]), 15)
        st, again = self.call("GET", "/api?pv=" + v)
        self.assertNotIn("palette", again)                                                      # the page has this version: no list, no CSS
        self.assertEqual(again["palette_v"], v)
        self.call("POST", "/palette/add", {"name": "Lime", "ui": "#99ff00"})
        st, changed = self.call("GET", "/api?pv=" + v)
        self.assertIn("lime", [c["id"] for c in changed["palette"]])
        self.assertIn("--c-lime:#99ff00", changed["palette_css"])
        self.assertNotEqual(changed["palette_v"], v)


if __name__ == "__main__":
    unittest.main()
