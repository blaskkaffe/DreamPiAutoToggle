"""layout.json: what a module shows as data. Boxes with the same name (case-insensitive) are shared, the picker order is
the priority, a background module has a background and settings (no dashboard boxes), and a broken layout keeps its module out with the reason shown."""
import json
import os
import unittest

from support import core, sandbox, cleanup
import netswitch_modules as mods


class LayoutBase(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        self.dir = os.path.join(self.tmp, "mods")
        os.makedirs(self.dir)
        self.saved, core.MODULES_DIR = core.MODULES_DIR, self.dir

    def tearDown(self):
        core.MODULES_DIR = self.saved
        mods.refresh(force=True)
        cleanup(self.tmp)

    def module(self, name, layout=None, manifest=None, raw=None):
        os.makedirs(os.path.join(self.dir, name))
        m = {"name": name.title(), "description": "d", "enabled": True, "visible": True}
        m.update(manifest or {})
        with open(os.path.join(self.dir, name, "module.json"), "w") as f:
            json.dump(m, f)
        if layout is not None or raw is not None:
            with open(os.path.join(self.dir, name, "layout.json"), "w") as f:
                f.write(raw if raw is not None else json.dumps(layout))

    def load(self, order=None):
        if order:
            core.save_module_order(order)
        mods.refresh(force=True)
        return mods.layout()


class BoxTests(LayoutBase):
    def test_a_module_without_a_layout_is_fine(self):
        self.module("plain")
        lay = self.load()
        self.assertEqual(lay["modules"], ["plain"])
        self.assertEqual(lay["settings"], [])

    def test_two_modules_share_a_box_by_name_ignoring_case(self):
        self.module("one", {"settings": [{"box": "GPIO", "title": "GPIO", "items": [{"type": "text", "text": "a"}]}]})
        self.module("two", {"settings": [{"box": "gpio", "items": [{"type": "text", "text": "b"}]}]})
        lay = self.load(["one", "two"])
        self.assertEqual(len(lay["settings"]), 1)
        box = lay["settings"][0]
        self.assertEqual(box["id"], "gpio")
        self.assertEqual(box["title"], "GPIO")
        self.assertEqual([(w["text"], w["mod"]) for w in box["items"]], [("a", "one"), ("b", "two")])
        self.assertEqual(box["mods"], ["one", "two"])

    def test_the_picker_order_decides_item_order_and_who_titles_the_box(self):
        self.module("one", {"settings": [{"box": "x", "title": "From one", "items": [{"type": "text", "text": "a"}]}]})
        self.module("two", {"settings": [{"box": "x", "title": "From two", "items": [{"type": "text", "text": "b"}]}]})
        box = self.load(["two", "one"])["settings"][0]
        self.assertEqual(box["title"], "From two")
        self.assertEqual([w["mod"] for w in box["items"]], ["two", "one"])

    def test_a_box_without_a_title_takes_the_first_one_given(self):
        self.module("one", {"settings": [{"box": "x", "items": []}]})
        self.module("two", {"settings": [{"box": "x", "title": "Named", "items": []}]})
        self.assertEqual(self.load(["one", "two"])["settings"][0]["title"], "Named")

    def test_boxes_come_in_order_of_first_appearance_and_sections_are_separate(self):
        self.module("one", {"dashboard": [{"box": "b1", "items": []}], "settings": [{"box": "s1", "items": []}]})
        self.module("two", {"settings": [{"box": "s0", "items": []}, {"box": "s1", "items": []}]})
        lay = self.load(["one", "two"])
        self.assertEqual([b["id"] for b in lay["settings"]], ["s1", "s0"])
        self.assertEqual([b["id"] for b in lay["dashboard"]], ["b1"])

    def test_a_module_that_is_off_adds_nothing(self):
        self.module("off", {"settings": [{"box": "x", "items": [{"type": "text", "text": "no"}]}]}, {"enabled": False})
        self.assertEqual(self.load()["settings"], [])


class BackgroundTests(LayoutBase):
    def test_a_background_module_cannot_also_have_dashboard_boxes(self):
        self.module("bad", {"background": {"type": "fullscreen"}, "dashboard": [{"box": "x", "items": []}]})
        lay = self.load()
        self.assertEqual(lay["modules"], [])
        self.assertIn("no dashboard boxes", mods._state["errors"]["bad"])

    def test_a_background_module_can_have_settings_boxes(self):
        self.module("pic", {"background": {"type": "fullscreen"}, "settings": [{"box": "pic", "title": "Picture", "items": [{"type": "text", "text": "hi"}]}]})
        lay = self.load()
        self.assertEqual([b["mod"] for b in lay["backgrounds"]], ["pic"])
        self.assertEqual([b["id"] for b in lay["settings"]], ["pic"])

    def test_the_background_type_must_be_known(self):
        self.module("bad", {"background": {"type": "wallpaper"}})
        self.load()
        self.assertIn("background.type", mods._state["errors"]["bad"])

    def test_the_top_fullscreen_background_hides_the_ones_below(self):
        self.module("top", {"background": {"type": "fullscreen"}})
        self.module("low", {"background": {"type": "fullscreen"}})
        self.assertEqual([b["mod"] for b in self.load(["top", "low"])["backgrounds"]], ["top"])
        self.assertEqual([b["mod"] for b in self.load(["low", "top"])["backgrounds"]], ["low"])

    def test_a_part_background_lets_the_ones_below_draw(self):
        self.module("bar", {"background": {"type": "part", "position": "bottom"}})
        self.module("full", {"background": {"type": "fullscreen"}})
        self.module("hidden", {"background": {"type": "fullscreen"}})
        got = self.load(["bar", "full", "hidden"])["backgrounds"]
        self.assertEqual([b["mod"] for b in got], ["bar", "full"])
        self.assertEqual(got[0]["position"], "bottom")

    def test_a_part_background_alone_and_below_a_fullscreen_one(self):
        self.module("bar", {"background": {"type": "part"}})
        self.module("full", {"background": {"type": "fullscreen"}})
        self.assertEqual([b["mod"] for b in self.load(["full", "bar"])["backgrounds"]], ["full"])


class ValidationTests(LayoutBase):
    def bad(self, layout, text, raw=None):
        self.module("bad", layout, raw=raw)
        self.load()
        self.assertNotIn("bad", mods.layout()["modules"])
        self.assertIn(text, mods._state["errors"]["bad"])

    def test_not_json(self):
        self.bad(None, "not valid JSON", raw="{nope")

    def test_unknown_widget(self):
        self.bad({"settings": [{"box": "x", "items": [{"type": "sparkles"}]}]}, "unknown widget type")

    def test_unknown_widget_nested_in_a_row(self):
        self.bad({"settings": [{"box": "x", "items": [{"type": "row", "title": "t", "control": {"type": "sparkles"}}]}]}, "control")

    def test_unknown_widget_in_a_form_field(self):
        self.bad({"settings": [{"box": "x", "items": [{"type": "form", "fields": [{"controls": [{"type": "nope"}]}]}]}]}, "controls")

    def test_a_box_needs_a_name(self):
        self.bad({"settings": [{"items": []}]}, '"box" name')

    def test_unknown_section(self):
        self.bad({"sidebar": []}, "unknown key")

    def test_data_needs_a_name_and_a_url(self):
        self.bad({"data": {"Bad Name": {"url": "/x"}}}, "data")

    def test_data_url_must_start_with_a_slash(self):
        self.bad({"data": {"ok": {"url": "x"}}}, "data")

    def test_every_standard_widget_type_is_accepted(self):
        items = [{"type": t} for t in mods.WIDGETS]
        self.module("all", {"settings": [{"box": "x", "items": items}]})
        self.assertEqual(len(self.load()["settings"][0]["items"]), len(mods.WIDGETS))


class ToggleBoxTests(LayoutBase):
    def test_a_module_with_toggle_box_gets_its_switch_in_that_box_even_while_off(self):
        self.module("host", {"settings": [{"box": "appearance", "title": "Appearance", "items": [{"type": "text", "text": "hi"}]}]})
        self.module("bg", {"background": {"type": "fullscreen"}}, {"toggle_box": "appearance", "name": "Fancy background", "description": "Looks nice", "enabled": False})
        lay = self.load(["host", "bg"])
        self.assertEqual(lay["modules"], ["host"])                                  # off: not loaded, no background
        self.assertEqual(lay["backgrounds"], [])
        box = lay["settings"][0]
        self.assertEqual((box["id"], box["title"], box["mods"]), ("appearance", "Appearance", ["host", "bg"]))
        row = box["items"][-1]
        self.assertEqual((row["title"], row["sub"], row["control"]), ("Fancy background", "Looks nice", {"type": "toggle", "module": "bg", "label": "Fancy background"}))
        core.save_module_enabled("bg", True)
        lay = self.load()
        self.assertEqual(lay["backgrounds"][0]["mod"], "bg")                        # on: drawn, and the row is still there (once)
        self.assertEqual(len([w for w in lay["settings"][0]["items"] if w.get("type") == "row"]), 1)

    def test_the_box_gets_a_title_from_its_name_when_nobody_gave_one(self):
        self.module("bg", {"background": {"type": "fullscreen"}}, {"toggle_box": "appearance"})
        self.assertEqual(self.load()["settings"][0]["title"], "Appearance")

    def test_an_always_on_module_gets_no_switch_row(self):
        self.module("fixed", {"settings": []}, {"toggle_box": "appearance", "visible": False})
        self.assertEqual(self.load()["settings"], [])


class DataColourTests(LayoutBase):
    def test_data_sources_keep_their_first_owner(self):
        self.module("one", {"data": {"players": {"url": "/players", "every": 60}}})
        self.module("two", {"data": {"players": {"url": "/other"}}})
        data = self.load(["one", "two"])["data"]
        self.assertEqual(data["players"]["url"], "/players")
        self.assertEqual(data["players"]["mod"], "one")

    def test_primary_by_palette_id_or_own_colour_key(self):
        self.module("a", manifest={"primary": "bright-green"})
        self.module("b", manifest={"colours": {"main": "purple"}, "primary": "main"})
        self.module("c")
        lay = self.load(["a", "b", "c"])
        self.assertEqual(lay["primary"], {"a": "bright-green", "b": "purple"})
        self.assertEqual(lay["colours"], {"b": {"main": "purple"}})

    def test_an_unknown_primary_is_ignored(self):
        self.module("a", manifest={"primary": "chartreuse"})
        self.assertEqual(self.load()["primary"], {})


if __name__ == "__main__":
    unittest.main()
