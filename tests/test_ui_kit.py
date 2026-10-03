"""The page kit: modules build their rows, pop-ups, tags, sliders and consoles from the classes and helpers in the base
page (page/page.css, page/page.js) instead of their own, so one change there changes every module. These tests keep it so."""
import glob
import json
import os
import re
import unittest

from support import ROOT
import netswitch_modules as mods

CSS = os.path.join(ROOT, "page", "page.css")
JS = os.path.join(ROOT, "page", "page.js")
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
    def test_every_module_declares_the_kit_version_it_was_written_for(self):
        for path in glob.glob(os.path.join(MODULES, "*", "module.json")):
            m = json.loads(read(path))
            self.assertIsInstance(m.get("ui"), int, path)
            self.assertTrue(1 <= m["ui"] <= mods.UI_KIT, path)

    def test_the_page_and_the_loader_agree_on_the_version(self):
        self.assertEqual(int(re.search(r"var ui=\{version:(\d+)", read(JS)).group(1)), mods.UI_KIT)

    def test_the_kit_has_what_the_docs_promise(self):
        css = read(CSS)
        for cls in ("srow", "pop", "tags", "tag", "range", "console", "msg", "empty"):
            self.assertIn("." + cls, css, cls)
        js = read(JS)
        for fn in ("ui.row=", "ui.btn=", "ui.tag=", "ui.popup=", "ui.closePopups="):
            self.assertIn(fn, js, fn)

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

    def test_module_scripts_build_rows_with_the_kit(self):
        for path in glob.glob(os.path.join(MODULES, "*", "page.js")):
            self.assertNotRegex(read(path), r"""class=["']srow""", "%s writes a .srow by hand: use ui.row()" % path)
            self.assertNotIn("classList.add(\"open\")", read(path), "%s opens a pop-up by hand: use ui.popup()" % path)

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
                json.dump({"title": "Future", "ui": mods.UI_KIT + 1, "default": True}, f)
            mods.refresh(force=True)
            self.assertIn("page kit", mods._state["errors"]["future"])
            self.assertEqual(mods._state["loaded"], [])
        finally:
            core.MODULES_DIR = saved
            shutil.rmtree(tmp, ignore_errors=True)
            mods.refresh(force=True)


if __name__ == "__main__":
    unittest.main()
