"""The page kit: modules draw what they show with the standard widgets of the base page (page/widgets.js, styled in
page/page.css) instead of their own markup, so one change there changes every module. These tests keep it so."""
import glob
import json
import os
import re
import unittest

from support import ROOT
import netswitch_modules as mods

CSS = os.path.join(ROOT, "page", "page.css")
JS = os.path.join(ROOT, "page", "page.js")
WIDGETS_JS = os.path.join(ROOT, "page", "widgets.js")
MODULES = os.path.join(ROOT, "modules")
THEME_MODULES = ("background",)       # a theme restyles the base classes on purpose


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def selectors(css):
    """Every selector of every rule in a stylesheet (at-rules are looked into, declarations are not)."""
    css = strip_comments(css)
    out = []
    for m in re.finditer(r"([^{}]+)\{", css):
        head = m.group(1).strip()
        if head.startswith("@"):
            continue
        out += [s.strip() for s in re.split(r",(?![^(]*\))", head) if s.strip()]
    return out


def base_classes():
    return set(re.findall(r"\.([A-Za-z][\w-]*)", strip_comments(read(CSS))))


class KitTests(unittest.TestCase):
    def test_the_thick_borders_of_boxes_and_buttons_are_opaque(self):
        """A box's or button's border is a solid colour (the backgrounds may be see-through); a translucent one over a see-through
        background looks duller than the same border on a button."""
        css = strip_comments(read(CSS))
        for m in re.finditer(r"border(?:-color)?:[^;}]*", css):
            decl = m.group(0)
            if "var(--bw)" in decl or decl.startswith("border-color"):
                self.assertNotIn("rgba(", decl, decl)

    def test_every_module_declares_the_kit_version_it_was_written_for(self):
        for path in glob.glob(os.path.join(MODULES, "*", "module.json")):
            m = json.loads(read(path))
            self.assertIsInstance(m.get("ui"), int, path)
            self.assertTrue(1 <= m["ui"] <= mods.UI_KIT, path)
            if os.path.exists(os.path.join(os.path.dirname(path), "layout.json")):
                self.assertGreaterEqual(m["ui"], 2, "%s: layout.json needs the page kit with the layout engine (2)" % path)

    def test_the_page_and_the_loader_agree_on_the_version(self):
        self.assertEqual(int(re.search(r"var ui=\{version:(\d+)", read(JS)).group(1)), mods.UI_KIT)

    def test_every_widget_the_loader_accepts_is_drawn_by_the_page(self):
        """The loader (netswitch_modules.WIDGETS) and the page (W.<type> in widgets.js) must list the same widgets, and a
        form's controls (CONTROLS) must be built by control()."""
        js = read(WIDGETS_JS)
        for t in mods.WIDGETS:
            self.assertTrue(("W.%s=function" % t) in js, "the loader accepts a %s widget but the page can't draw it" % t)
        drawn = set(re.findall(r"\bW\.(\w+)=function", js))
        self.assertEqual(sorted(drawn - set(mods.WIDGETS)), [], "the page draws widgets the loader would refuse")
        for c in mods.CONTROLS:
            self.assertTrue(('spec.type==="%s"' % c) in js or c == "text", c)

    def test_the_kit_has_what_the_docs_promise(self):
        css = read(CSS)
        for cls in ("srow", "pop", "tags", "tag", "range", "console", "msg", "empty", "swatches", "now", "pill", "carousel", "primary"):
            self.assertTrue(cls in css, cls)
        js = read(JS)
        for fn in ("ui.popup=", "ui.closePopups="):
            self.assertTrue(fn in js, fn)
        for gone in ("ui.row=", "ui.btn=", "ui.tag=", "ui.swatches="):
            self.assertTrue(gone not in js, gone + " is replaced by the widgets")

    def test_every_colour_pick_says_whether_it_is_a_network_or_a_module_colour(self):
        def rows(node):
            if isinstance(node, dict):
                if node.get("type") == "row" and isinstance(node.get("control"), dict) and node["control"].get("type") == "swatches":
                    yield node
                for v in node.values():
                    for r in rows(v):
                        yield r
            elif isinstance(node, list):
                for v in node:
                    for r in rows(v):
                        yield r
        found = 0
        for name in os.listdir(os.path.join(ROOT, "modules")):
            path = os.path.join(ROOT, "modules", name, "layout.json")
            if os.path.exists(path):
                for row in rows(json.loads(read(path))):
                    found += 1
                    self.assertIn(row.get("sub"), ("Network", "Module"), "%s: %s" % (name, row.get("title")))
        self.assertGreaterEqual(found, 3)

    def test_module_css_does_not_redefine_a_base_class(self):
        """`.srow{...}` in a module would change every row in the app. Scoped rules (`#wifi-list .srow`) and a module's own
        classes are fine; so are themes."""
        base = base_classes()
        for path in glob.glob(os.path.join(MODULES, "*", "page.css")):
            if os.path.basename(os.path.dirname(path)) in THEME_MODULES:
                continue
            for sel in selectors(read(path)):
                first = re.split(r"[\s>+~]", sel, maxsplit=1)[0]
                if first.startswith(("#", "html", "body", ":", "[", "@")):
                    continue
                classes = re.findall(r"\.([A-Za-z][\w-]*)", first)      # `.lvl.on`: the element is a .lvl, .on is a state
                if classes:
                    self.assertNotIn(classes[0], base, "%s: `%s` styles the base class .%s everywhere" % (path, sel, classes[0]))

    def test_module_css_uses_the_colour_tokens(self):
        for path in glob.glob(os.path.join(MODULES, "*", "page.css")):
            if os.path.basename(os.path.dirname(path)) in THEME_MODULES:
                continue
            for hexcolour in re.findall(r"#[0-9a-fA-F]{3,8}\b", strip_comments(read(path))):
                self.assertIn(hexcolour.lower(), ("#fff", "#000", "#ffffff", "#000000"), "%s uses %s: add a token to page.css" % (path, hexcolour))

    def test_module_scripts_draw_with_the_widgets(self):
        for path in glob.glob(os.path.join(MODULES, "*", "page.js")):
            self.assertNotRegex(read(path), r"""class=["']srow""", "%s writes a .srow by hand: use the row widget in layout.json" % path)
            self.assertNotIn("classList.add(\"open\")", read(path), "%s opens a pop-up by hand: use ui.popup()" % path)
            self.assertNotRegex(read(path), r"getElementById\(.(dash|set-boxes).\)|\$\(.(dash|set-boxes).\)", "%s draws into the page's boxes by hand: put it in layout.json" % path)

    def test_the_base_page_has_no_module_markup_left(self):
        html = read(os.path.join(ROOT, "page", "index.html"))
        for gone in ("SLOT", "gpio-section", "mod-list", "colours-section", 'id="net"', "dcnow-b"):
            self.assertNotIn(gone, html, gone)

    def test_a_module_for_a_newer_kit_is_not_loaded(self):
        import tempfile
        import shutil
        import netswitch_core as core
        tmp = tempfile.mkdtemp()
        saved = core.MODULES_DIR
        try:
            core.MODULES_DIR = tmp
            os.makedirs(os.path.join(tmp, "future"))
            with open(os.path.join(tmp, "future", "module.json"), "w") as f:
                json.dump({"name": "Future", "ui": mods.UI_KIT + 1, "enabled": True}, f)
            mods.refresh(force=True)
            self.assertIn("page kit", mods._state["errors"]["future"])
            self.assertEqual(mods._state["loaded"], [])
        finally:
            core.MODULES_DIR = saved
            shutil.rmtree(tmp, ignore_errors=True)
            mods.refresh(force=True)


if __name__ == "__main__":
    unittest.main()
