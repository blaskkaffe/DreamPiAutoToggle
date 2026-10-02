"""The LED module is optional: with its files the page has the LED settings, without them it doesn't,
and nothing else notices. The page follows the files while the web service runs."""
import json
import os
import re
import shutil
import subprocess
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from support import web, core, sandbox, cleanup

LED_FILES = ("led.html", "led.js", "led.css")


def inline_script(html):
    return "\n".join(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        self.page_dir = os.path.join(self.tmp, "page")
        shutil.copytree(web.PAGE_DIR, self.page_dir)
        self.saved_dir = web.PAGE_DIR
        web.PAGE_DIR = self.page_dir
        web.refresh_modules(force=True)
        self.srv = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        web.PAGE_DIR = self.saved_dir
        web.refresh_modules(force=True)
        cleanup(self.tmp)

    def get(self, path):
        return urlopen(self.base + path, timeout=10).read().decode()

    def status(self, path, method="GET"):
        req = Request(self.base + path, method=method, data=b"{}" if method == "POST" else None,
                      headers={"X-Requested-With": "x", "Content-Type": "application/json"})
        try:
            return urlopen(req, timeout=10).status
        except HTTPError as e:
            return e.code

    def remove_led(self):
        for f in LED_FILES:
            os.remove(os.path.join(self.page_dir, f))
        self.touch()

    def touch(self):
        later = time.time() + 5          # a changed mtime is what tells the service the files moved
        for f in os.listdir(self.page_dir):
            os.utime(os.path.join(self.page_dir, f), (later, later))
            later += 1


class WithModule(Base):
    def test_the_page_has_the_led_settings(self):
        html = self.get("/")
        for needle in ('id="led-section"', 'id="gpio-led-row"', 'id="fx-pop"', 'id="lvl-pop"', "function ledOpen", ".ledtab"):
            self.assertIn(needle, html)
        self.assertNotIn("@@", html)                    # every marker was filled in
        self.assertEqual(html.count('id="led-section"'), 1)

    def test_endpoints_answer(self):
        self.assertEqual(self.status("/ledconfig"), 200)
        self.assertEqual(self.status("/ledconfig", "POST"), 200)
        self.assertEqual(self.status("/wbtestdone", "POST"), 204)

    def test_the_gpio_section_keeps_its_button_text_with_the_module(self):
        html = self.get("/")
        self.assertIn("GPIO10 only works if SPI", html)
        self.assertIn("A push button's function", html)

    def test_page_script_is_valid(self):
        self.check_js(self.get("/"))

    def check_js(self, html):
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        path = os.path.join(self.tmp, "page.js")
        with open(path, "w") as f:
            f.write(inline_script(html))
        out = subprocess.run(["node", "--check", path], stderr=subprocess.PIPE)
        self.assertEqual(out.returncode, 0, out.stderr.decode())


class WithoutModule(WithModule):
    """Same checks, opposite answers (inherits the helpers, not the tests)."""
    test_the_page_has_the_led_settings = test_endpoints_answer = test_the_gpio_section_keeps_its_button_text_with_the_module = None
    test_page_script_is_valid = None

    def setUp(self):
        Base.setUp(self)
        self.remove_led()

    def test_no_led_settings_anywhere(self):
        html = self.get("/")
        for needle in ("led-section", "gpio-led-row", "fx-pop", "function ledOpen", "ledtab", "Status LED", "NeoPixel", "@@"):
            self.assertNotIn(needle, html, needle)
        self.assertIn('id="gpio-section"', html)        # the buttons' GPIO settings stay
        self.assertIn("A push button's function", html)
        self.assertNotIn("GPIO10 only works", html)
        self.check_js(html)

    def test_led_endpoints_are_404(self):
        for path in web.LED_PATHS:
            self.assertEqual(self.status(path, "POST"), 404, path)
        self.assertEqual(self.status("/ledconfig"), 404)

    def test_everything_else_still_works(self):
        d = json.loads(self.get("/api"))
        self.assertEqual(d["network"], "dcnow")
        self.assertIn("look", d["dreampi"])
        self.assertEqual(self.status("/status"), 200)
        self.assertEqual(self.status("/dcnet", "POST"), 204)

    def test_the_dreampi_dot_still_has_a_look(self):
        for state, effect in (("ok", "breathe"), ("busy", "breathe"), ("off", "blink"), ("call-dcnow", "solid")):
            look = web._dot_look(state)
            self.assertEqual(look["effect"], effect, state)
            self.assertRegex(look["color"], r"^#[0-9a-f]{6}$")
        self.assertIsNone(web._dot_look("somethingelse"))

    def test_partial_module_counts_as_absent(self):
        shutil.copy(os.path.join(self.saved_dir, "led.js"), os.path.join(self.page_dir, "led.js"))   # only one of three files
        self.touch()
        self.assertNotIn("led-section", self.get("/"))
        self.assertEqual(self.status("/ledconfig", "POST"), 404)


class FollowsTheFiles(Base):
    def test_files_can_be_removed_and_added_back_while_running(self):
        self.assertIn('id="led-section"', self.get("/"))
        self.assertEqual(self.status("/ledconfig"), 200)
        backup = os.path.join(self.tmp, "led-backup")
        os.mkdir(backup)
        for f in LED_FILES:
            shutil.move(os.path.join(self.page_dir, f), backup)
        self.touch()
        self.assertNotIn('id="led-section"', self.get("/"))
        self.assertEqual(self.status("/ledconfig"), 404)
        for f in LED_FILES:
            shutil.move(os.path.join(backup, f), self.page_dir)
        self.touch()
        self.assertIn('id="led-section"', self.get("/"))
        self.assertEqual(self.status("/ledconfig"), 200)

    def test_a_python_file_going_missing_hides_the_settings_too(self):
        saved = web.OPTIONAL_MODULES["led"]["python"]
        web.OPTIONAL_MODULES["led"]["python"] = saved + ["netswitch_not_there.py"]
        try:
            web.refresh_modules(force=True)
            self.assertNotIn('id="led-section"', self.get("/"))
        finally:
            web.OPTIONAL_MODULES["led"]["python"] = saved
            web.refresh_modules(force=True)

    def test_a_module_that_fails_to_import_does_not_break_the_page(self):
        real = web.importlib.import_module
        def boom(name, *a):
            if name == "netswitch_ledconfig":
                raise SyntaxError("broken on purpose")
            return real(name, *a)
        web.importlib.import_module = boom
        try:
            web.refresh_modules(force=True)
            html = self.get("/")
            self.assertNotIn("led-section", html)
            self.assertIn('id="gpio-section"', html)
        finally:
            web.importlib.import_module = real
            web.refresh_modules(force=True)

    def test_editing_a_page_file_shows_up_without_a_restart(self):
        path = os.path.join(self.page_dir, "led.css")
        with open(path, "a") as f:
            f.write("\n.marker-for-the-test{color:red}\n")
        self.touch()
        self.assertIn("marker-for-the-test", self.get("/"))


class InstallerTests(unittest.TestCase):
    """The part of install.sh that installs or removes the LED files, run on temp folders."""
    ALL = ["netswitch_ledconfig.py", "netswitch_led.py", "netswitch_led_drivers.py", "page/led.html", "page/led.js", "page/led.css"]

    def snippet(self):
        root = os.path.dirname(web.__file__)
        with open(os.path.join(root, "install.sh")) as f:
            text = f.read()
        start = text.index('LED_FILES="')
        end = text.index("done\n", text.index('for f in $LED_FILES; do\n    if [ "$LED_MODULE"')) + 5
        return text[start:end]

    def run_it(self, have):
        tmp = sandbox()
        try:
            src, dest = os.path.join(tmp, "src"), os.path.join(tmp, "dest")
            for d in (src, dest):
                os.makedirs(os.path.join(d, "page"))
            for f in self.ALL:                                   # an older install already has everything
                open(os.path.join(dest, f), "w").write("old")
            for f in have:
                open(os.path.join(src, f), "w").write("new")
            out = subprocess.run(["sh", "-c", 'SRC="%s"; DEST="%s"; %s\necho "LED_MODULE=$LED_MODULE"' % (src, dest, self.snippet())],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(out.returncode, 0, out.stderr.decode())
            return out.stdout.decode().strip(), dict((f, os.path.exists(os.path.join(dest, f))) for f in self.ALL), dest
        finally:
            self.cleanup = tmp

    def test_all_files_present_installs_them(self):
        said, there, dest = self.run_it(self.ALL)
        self.assertEqual(said, "LED_MODULE=yes")
        self.assertTrue(all(there.values()))
        cleanup(self.cleanup)

    def test_any_file_missing_removes_the_whole_module(self):
        for missing in self.ALL:
            said, there, dest = self.run_it([f for f in self.ALL if f != missing])
            self.assertEqual(said, "LED_MODULE=no", missing)
            self.assertFalse(any(there.values()), missing)
            cleanup(self.cleanup)

    def test_nothing_in_the_repo_removes_it_too(self):
        said, there, dest = self.run_it([])
        self.assertEqual(said, "LED_MODULE=no")
        self.assertFalse(any(there.values()))
        cleanup(self.cleanup)

    def test_the_unit_skips_quietly_when_the_files_are_gone(self):
        root = os.path.dirname(web.__file__)
        with open(os.path.join(root, "install.sh")) as f:
            text = f.read()
        for name in ("netswitch_led.py", "netswitch_led_drivers.py", "netswitch_ledconfig.py"):
            self.assertIn("ConditionPathExists=$DEST/" + name, text)


class Layering(unittest.TestCase):
    def test_nothing_outside_the_module_imports_the_led_files(self):
        """Removing the module must not break an import anywhere else (the web service loads it by name, guarded)."""
        root = os.path.dirname(web.__file__)
        mine = {"netswitch_led.py", "netswitch_led_drivers.py", "netswitch_ledconfig.py"}
        for name in sorted(os.listdir(root)):
            if not name.startswith("netswitch_") or not name.endswith(".py") or name in mine:
                continue
            with open(os.path.join(root, name)) as f:
                for line in f:
                    self.assertFalse(re.match(r"\s*(import|from)\s+netswitch_led", line), (name, line))


if __name__ == "__main__":
    unittest.main()
