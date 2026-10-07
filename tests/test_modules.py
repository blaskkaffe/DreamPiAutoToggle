"""The module system: everything the page shows is a folder in modules/. With its folder the feature is part of the
page (its layout.json is in window.LAYOUT) and the web service, without it (or switched off in the module picker) it simply isn't there."""
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

from support import ROOT, web, core, sandbox, cleanup

REAL_MODULES = os.path.join(ROOT, "modules")
NAMES = ["background", "clock", "debuglog", "events", "imagebg", "led", "numbers", "openmenu", "players", "rebootupdate", "wifi"]      # the modules the picker can switch
HIDDEN = ["switcher", "system"]                                                # always on, not in the picker
ALL = sorted(NAMES + HIDDEN)
# a path only that module answers (GET, or POST when None)
ENDPOINT = {"background": ("GET", "/background/dc-background.js"), "clock": ("GET", "/clock"), "events": ("GET", "/events/view"), "imagebg": ("GET", "/imagebg"), "numbers": ("GET", "/numbers"), "openmenu": ("GET", "/openmenu/view"), "players": ("GET", "/players"), "debuglog": ("GET", "/dtmf"),
            "led": ("GET", "/ledconfig"), "wifi": ("POST", "/wifitoggle"), "rebootupdate": ("GET", "/update")}
HIDDEN_ENDPOINT = {"switcher": ("GET", "/status"), "system": ("GET", "/about")}
BASE_IDS = ('id="dash"', 'id="set-boxes"', 'id="settings"', 'id="bg"', 'id="warnings"')


def layout_of(html):
    """The window.LAYOUT of a page, parsed."""
    m = re.search(r"window\.LAYOUT=(\{.*?\});\n", html, re.S)
    return json.loads(m.group(1))


def present(html, name):
    """Is the module in the page? (its layout is part of window.LAYOUT, and a background module is in "backgrounds" too)"""
    return name in layout_of(html)["modules"]


def widgets(html, name):
    lay = layout_of(html)
    return [w for sec in ("dashboard", "settings") for b in lay[sec] for w in b["items"] if w["mod"] == name]


def inline_script(html):
    return "\n".join(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S))


class Base(unittest.TestCase):
    """A web service on a private copy of modules/, so a test can add, remove and break modules freely."""
    ENABLE_WIFI = True

    def setUp(self):
        self.tmp = sandbox()
        self.modules = os.path.join(self.tmp, "modules")
        shutil.copytree(REAL_MODULES, self.modules, ignore=shutil.ignore_patterns("__pycache__"))
        self.saved_dir, core.MODULES_DIR = core.MODULES_DIR, self.modules
        for off_by_default in ("debuglog", "background", "imagebg"):
            core.save_module_enabled(off_by_default, True)   # the tests want to see them
        if self.ENABLE_WIFI:
            core.save_module_enabled("wifi", True)
        web.refresh_page(force=True)
        self.srv = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        core.MODULES_DIR = self.saved_dir
        web.refresh_page(force=True)
        cleanup(self.tmp)

    def page(self):
        return urlopen(self.base + "/", timeout=10).read().decode()

    def status(self, method, path, body=None):
        req = Request(self.base + path, method=method, data=(json.dumps(body).encode() if body is not None else (b"{}" if method == "POST" else None)),
                      headers={"X-Requested-With": "x", "Content-Type": "application/json"})
        try:
            return urlopen(req, timeout=10).status
        except HTTPError as e:
            return e.code

    def json(self, path):
        return json.loads(urlopen(self.base + path, timeout=10).read().decode())

    def check_js(self, html):
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        path = os.path.join(self.tmp, "page.js")
        with open(path, "w") as f:
            f.write(inline_script(html))
        out = subprocess.run(["node", "--check", path], stderr=subprocess.PIPE)
        self.assertEqual(out.returncode, 0, out.stderr.decode())

    def touch_all(self):
        later = time.time() + 5          # a changed mtime is what tells the service the files moved
        for root, _dirs, files in os.walk(self.modules):
            for f in files:
                os.utime(os.path.join(root, f), (later, later))
                later += 0.01


class RepoModules(unittest.TestCase):
    def test_no_json_file_of_a_module_repeats_a_key(self):
        """A repeated key is silently dropped by JSON (the last wins): two "settings" lists once lost a whole box after a merge."""
        def no_dupes(pairs):
            keys = [k for k, _ in pairs]
            self.assertEqual(len(keys), len(set(keys)), "repeated key in %s" % keys)
            return dict(pairs)
        for n in ALL:
            for fn in ("module.json", "layout.json"):
                path = os.path.join(REAL_MODULES, n, fn)
                if os.path.exists(path):
                    with open(path) as f:
                        json.load(f, object_pairs_hook=no_dupes)

    def test_the_modules_are_there_and_well_formed(self):
        self.assertEqual(sorted(n for n in os.listdir(REAL_MODULES) if os.path.isdir(os.path.join(REAL_MODULES, n)) and n != "__pycache__"), ALL)
        for n in ALL:
            with open(os.path.join(REAL_MODULES, n, "module.json")) as f:
                m = json.load(f)
            for key in ("name", "description", "enabled", "visible"):
                self.assertIn(key, m, (n, key))
            self.assertNotIn("title", m)                  # the older spelling of "name" and "default" of "enabled" are only read, not written
            self.assertNotIn("default", m)
            if "web" in m:
                self.assertTrue(os.path.exists(os.path.join(REAL_MODULES, n, m["web"] + ".py")), n)
            self.assertFalse(os.path.exists(os.path.join(REAL_MODULES, n, "page.html")), n)       # layout.json replaced the page fragments

    def test_defaults(self):
        on = dict((n, json.load(open(os.path.join(REAL_MODULES, n, "module.json")))["enabled"]) for n in ALL)
        self.assertEqual(on, {"background": False, "clock": True, "debuglog": False, "events": True, "imagebg": False, "led": True, "numbers": True, "openmenu": True, "players": True, "rebootupdate": True, "switcher": True, "system": True, "wifi": False})
        hidden = [n for n in ALL if json.load(open(os.path.join(REAL_MODULES, n, "module.json")))["visible"] is False]
        self.assertEqual(hidden, HIDDEN)                   # the network switcher and the system info can't be switched off


class WithEverything(Base):
    def test_page_has_every_module_and_no_leftover_markers(self):
        html = self.page()
        for n in ALL:
            self.assertTrue(present(html, n), n)
        for ident in BASE_IDS:
            self.assertIn(ident, html)
        self.assertNotIn("@@", html)
        self.assertNotIn("SLOT", html)
        self.check_js(html)

    def test_endpoints_answer(self):
        for n, (method, path) in list(ENDPOINT.items()) + list(HIDDEN_ENDPOINT.items()):
            self.assertIn(self.status(method, path), (200, 204), (n, path))

    def test_boxes_are_shared_by_name_between_modules(self):
        lay = layout_of(self.page())
        gpio = [b for b in lay["settings"] if b["id"] == "gpio"]
        self.assertEqual(len(gpio), 1)
        self.assertEqual(gpio[0]["mods"], ["switcher", "led", "wifi"])          # one GPIO box, three modules in picker order (the network buttons are the switcher's)
        self.assertEqual(gpio[0]["title"], "GPIO")
        system = [b for b in lay["settings"] if b["id"] == "system"][0]
        self.assertEqual(system["mods"], ["wifi", "rebootupdate"])
        self.assertEqual([w["type"] for w in system["items"] if w["mod"] == "rebootupdate"][-1], "row")      # the Reboot row ends the System box
        ids = [b["id"] for b in lay["settings"]]
        self.assertEqual(ids[-1], "system")                                                                # System is the very last box
        self.assertLess(ids.index("about"), ids.index("background-image"))                                  # settings-only modules come before the backgrounds
        appearance = [b for b in lay["settings"] if b["id"] == "appearance"][0]
        self.assertEqual((appearance["mods"], appearance["title"]), (["base", "switcher", "clock", "players", "events", "openmenu", "debuglog", "imagebg", "background"], "Appearance"))      # the base's own settings (base/layout.json) first, then the colours (network, clock, players, events, openMenu link, debug log) and the background's switch
        self.assertEqual([w["control"]["module"] for w in appearance["items"] if w["type"] == "row" and w["control"]["type"] == "toggle" and "module" in w["control"]], ["imagebg", "background"])
        about = [b for b in lay["settings"] if b["id"] == "about"][0]
        self.assertEqual((about["mods"], about["title"]), (["system"], "About"))               # the versions are their own box, not part of System
        self.assertEqual([b["id"] for b in lay["dashboard"]], ["network", "clock", "players", "events", "openmenu", "debug log"])

    def test_system_is_the_last_settings_box_whatever_the_picker_order(self):
        core.save_module_order(["rebootupdate", "wifi", "system", "debuglog", "background", "led", "numbers", "events", "players", "clock", "switcher"])
        lay = layout_of(self.page())
        self.assertEqual([b["id"] for b in lay["settings"]][-1], "system")
        self.assertEqual(len([b for b in lay["settings"] if b["id"] == "system"]), 1)

    def test_led_hardware_settings_are_in_the_gpio_box_and_come_from_the_led_module(self):
        lay = layout_of(self.page())
        gpio = [b for b in lay["settings"] if b["id"] == "gpio"][0]
        keys = [c["key"] for w in gpio["items"] if w["mod"] == "led" for f in w["fields"] for c in f["controls"]]
        self.assertEqual(keys, ["led_count", "led_order", "led_gpio"])
        led_box = [b for b in lay["settings"] if b["id"] == "status led"][0]
        custom = led_box["items"][0]
        self.assertEqual(custom["type"], "custom")
        self.assertNotIn("led-count-i", custom["html"])                  # the hardware rows are not in the messages widget
        self.assertIn('id="cal-pop"', custom["html"])                    # but the rest of it is (markup came from messages.html)

    def test_the_about_module_is_listed_as_about_and_moves_its_box(self):
        got = {m["name"]: m["title"] for m in self.json("/modules")["modules"]}
        self.assertEqual(got["system"], "About")                                   # the picker row says what it moves
        core.save_module_order(["system"])                                         # the rest keeps its order after it
        web.refresh_page(force=True)
        ids = [b["id"] for b in layout_of(self.page())["settings"]]
        first_settings_only = [b["id"] for b in layout_of(self.page())["settings"] if b["mods"] == ["numbers"]][0]
        self.assertLess(ids.index("about"), ids.index(first_settings_only))                      # first among the settings-only modules (the dashboard ones stay above them)

    def test_the_picker_lists_dashboard_modules_then_settings_only_then_backgrounds(self):
        core.save_module_order(["background", "wifi", "led", "debuglog", "imagebg", "clock", "system", "switcher"])    # the user's own mix
        names = core.module_names()
        groups = [core.module_group(n) for n in names]
        self.assertEqual(groups, sorted(groups))
        self.assertEqual(sorted(set(groups)), [0, 1, 2])
        self.assertEqual((core.module_group("switcher"), core.module_group("system"), core.module_group("imagebg")), (0, 1, 2))
        self.assertEqual([n for n in names if core.module_group(n) == 2], ["background", "imagebg"])        # inside a group the user's order stays
        self.assertLess(names.index("debuglog"), names.index("clock"))

    def test_moving_tiles_on_the_main_screen_reorders_those_modules_only(self):
        core.save_module_order(["switcher", "clock", "players", "events", "openmenu", "debuglog", "numbers", "led", "system", "wifi", "rebootupdate", "imagebg", "background"])
        new = core.save_dashboard_order(["debuglog", "players", "clock"])                                   # three tiles moved: they take each other's places
        self.assertEqual(new[:6], ["switcher", "debuglog", "players", "events", "openmenu", "clock"])
        self.assertEqual(new[6:], ["numbers", "led", "system", "wifi", "rebootupdate", "imagebg", "background"])
        self.assertEqual(core.save_dashboard_order(["nope", "events"])[:6], ["switcher", "debuglog", "players", "events", "openmenu", "clock"])      # unknown names are ignored
        self.assertIsNone(core.save_dashboard_order("clock"))

    def test_protected_paths_are_the_modules_own_post_routes(self):
        import base_modules as mods
        self.assertEqual(mods._state["protected"], {"/reboot", "/update/start", "/wificonnect"})
        for path in mods._state["protected"]:
            self.assertTrue(mods.route("POST", path), path)

    def test_modules_menu_lists_them_all(self):
        got = self.json("/modules")["modules"]
        self.assertEqual([m["name"] for m in got], ["switcher", "clock", "players", "events", "openmenu", "debuglog", "numbers", "led", "system", "wifi", "rebootupdate", "imagebg", "background"])   # picker order, the always-on modules included
        self.assertEqual([m["name"] for m in got if m["visible"] is False], ["switcher", "system"])                     # which the page lists without a switch
        self.assertTrue(all(m["enabled"] for m in got))
        self.assertTrue(all(m["title"] and m["description"] for m in got))


class WithNothing(Base):
    """The base alone: the website with the network box, the two buttons, buttons config, appearance, about,
    reboot and the Modules menu."""
    def setUp(self):
        Base.setUp(self)
        for n in NAMES:
            shutil.rmtree(os.path.join(self.modules, n))
        self.touch_all()

    def test_base_page(self):
        html = self.page()
        for ident in BASE_IDS:
            self.assertIn(ident, html)
        for n in NAMES:
            self.assertFalse(present(html, n), n)
        self.assertEqual(layout_of(html)["modules"], ["switcher", "system"])
        for word in ("led-section", "Status LED", "NeoPixel", "Special phone numbers", "dcbg", "Debug log", "Online players", "@@"):
            self.assertNotIn(word, html, word)
        self.check_js(html)

    def test_no_module_endpoints(self):
        for n, (method, path) in ENDPOINT.items():
            self.assertEqual(self.status(method, path), 404, (n, path))

    def test_everything_in_the_base_still_works(self):
        d = self.json("/api")
        self.assertEqual(d["network"], "dcnow")
        self.assertIn("look", d["dreampi"])
        self.assertNotIn("wifi", d)
        self.assertNotIn("debug", d)
        self.assertEqual(self.status("POST", "/dcnet"), 204)
        self.assertEqual(self.status("GET", "/status"), 200)
        self.assertEqual(self.status("GET", "/buttonconfig"), 200)
        self.assertEqual(self.status("GET", "/about"), 200)
        self.assertEqual([m["name"] for m in self.json("/modules")["modules"]], ["switcher", "system"])      # only the always-on ones are left

    def test_the_dreampi_dot_still_has_a_look(self):
        import base_modules as mods
        switcher = mods.get("switcher")
        for state, effect in (("ok", "solid"), ("busy", "blink"), ("off", "blink"), ("call-dcnow", "solid")):
            look = switcher._dot_look(state)
            self.assertEqual(look["effect"], effect, state)
            self.assertRegex(look["colour"], r"^[a-z-]+$")                        # a palette id (or dcnow / dcnet / network), never a hex value
        self.assertIsNone(switcher._dot_look("somethingelse"))

    def test_unknown_paths_are_404_not_the_page(self):
        self.assertEqual(self.status("GET", "/nothing-here"), 404)
        self.assertEqual(self.status("POST", "/nothing-here"), 404)


class OneModuleGone(Base):
    def test_each_module_can_be_deleted_alone(self):
        for gone in NAMES:
            if gone == "wifi":
                continue
            folder = os.path.join(self.modules, gone)
            backup = os.path.join(self.tmp, "backup-" + gone)
            shutil.move(folder, backup)
            self.touch_all()
            html = self.page()
            self.assertFalse(present(html, gone), gone)
            for other in ALL:
                if other != gone and os.path.isdir(os.path.join(self.modules, other)):
                    self.assertTrue(present(html, other), (gone, other))
            self.check_js(html)
            method, path = ENDPOINT[gone]
            self.assertEqual(self.status(method, path), 404, gone)
            shutil.move(backup, folder)                    # and back again while the service keeps running
            self.touch_all()
            self.assertTrue(present(self.page(), gone), gone)
            self.assertIn(self.status(*ENDPOINT[gone]), (200, 204), gone)

    def test_the_always_on_modules_can_be_deleted_alone_too(self):
        for gone in HIDDEN:
            folder = os.path.join(self.modules, gone)
            backup = os.path.join(self.tmp, "backup-" + gone)
            shutil.move(folder, backup)
            self.touch_all()
            html = self.page()
            self.assertFalse(present(html, gone), gone)
            self.check_js(html)
            self.assertEqual(self.status(*HIDDEN_ENDPOINT[gone]), 404, gone)
            self.assertIn(self.status("GET", "/api"), (200,))
            shutil.move(backup, folder)
            self.touch_all()
            self.assertTrue(present(self.page(), gone), gone)

    def test_each_module_can_be_switched_off_and_on_from_the_menu(self):
        for name in NAMES:
            self.assertEqual(self.status("POST", "/modules", {"name": name, "enabled": False}), 200, name)
            html = self.page()
            self.assertFalse(present(html, name), name)
            self.check_js(html)
            self.assertEqual(self.status(*ENDPOINT[name]), 404, name)
            self.assertFalse([m for m in self.json("/modules")["modules"] if m["name"] == name][0]["enabled"])
            self.assertEqual(self.status("POST", "/modules", {"name": name, "enabled": True}), 200, name)
            self.assertTrue(present(self.page(), name), name)
            self.assertIn(self.status(*ENDPOINT[name]), (200, 204), name)

    def test_switching_is_remembered_in_modules_json(self):
        self.status("POST", "/modules", {"name": "players", "enabled": False})
        with open(core.MODULES_STATE) as f:
            self.assertEqual(json.load(f)["players"], False)
        self.assertFalse(core.module_enabled("players"))
        self.assertTrue(core.module_enabled("numbers"))

    def test_bad_menu_requests(self):
        self.assertEqual(self.status("POST", "/modules", {"name": "nope", "enabled": True}), 404)
        self.assertEqual(self.status("POST", "/modules", {"name": "switcher", "enabled": False}), 404)       # not in the picker
        self.assertEqual(self.status("POST", "/modules", {"name": "led"}), 400)
        self.assertEqual(self.status("POST", "/modules", {"name": "led", "enabled": "yes"}), 400)
        self.assertEqual(self.status("POST", "/modules", {"name": "../x", "enabled": True}), 404)
        req = Request(self.base + "/modules", method="POST", data=b'{"name":"led","enabled":false}')
        with self.assertRaises(HTTPError) as cm:                  # from another site: no header, no origin
            urlopen(req, timeout=10)
        self.assertEqual(cm.exception.code, 403)
        self.assertTrue(core.module_enabled("led"))


class BrokenAndNewModules(Base):
    def test_a_module_that_fails_to_import_is_reported_and_the_rest_works(self):
        shutil.copy(os.path.join(self.modules, "numbers", "module.json"), os.path.join(self.modules, "numbers", "module.json.bak"))
        folder = os.path.join(self.modules, "extra")
        os.makedirs(folder)
        with open(os.path.join(folder, "module.json"), "w") as f:
            json.dump({"name": "Extra", "description": "Broken on purpose", "order": 5, "enabled": True, "visible": True, "web": "netswitch_extra_broken"}, f)
        with open(os.path.join(folder, "netswitch_extra_broken.py"), "w") as f:
            f.write("raise RuntimeError('broken on purpose')\n")
        with open(os.path.join(folder, "layout.json"), "w") as f:
            f.write('{"dashboard": [{"box": "extra", "items": [{"type": "text", "text": "extra-box"}]}]}')
        self.touch_all()
        html = self.page()
        self.assertNotIn("extra-box", html)
        self.assertTrue(present(html, "led"))
        extra = [m for m in self.json("/modules")["modules"] if m["name"] == "extra"][0]
        self.assertIn("broken on purpose", extra["error"])

    def test_a_new_module_folder_is_picked_up_while_running(self):
        folder = os.path.join(self.modules, "extra")
        os.makedirs(folder)
        with open(os.path.join(folder, "module.json"), "w") as f:
            json.dump({"name": "Extra", "description": "A new module", "order": 5, "enabled": True, "visible": True, "web": "netswitch_extra_ok"}, f)
        with open(os.path.join(folder, "netswitch_extra_ok.py"), "w") as f:
            f.write("def _hello(h):\n    h.send('hello', 'text/plain')\n\n\nGET = {'/extra': _hello}\n\n\ndef api(d, warnings):\n    d['extra'] = True\n    warnings.append('extra says hi')\n")
        with open(os.path.join(folder, "layout.json"), "w") as f:
            f.write('{"dashboard": [{"box": "extra", "items": [{"type": "text", "text": "extra-box"}]}], "settings": [{"box": "system", "items": [{"type": "text", "text": "extra-row"}]}]}')
        with open(os.path.join(folder, "page.js"), "w") as f:
            f.write("hook('api',function(d){});\n")
        with open(os.path.join(folder, "page.css"), "w") as f:
            f.write("#extra-box{color:red}\n")
        self.touch_all()
        html = self.page()
        for needle in ('extra-box', 'extra-row', "#extra-box{color:red}", "hook('api'"):
            self.assertIn(needle, html)
        lay = layout_of(html)
        self.assertEqual([b["id"] for b in lay["dashboard"]][0], "extra")         # its "order" hint (5) puts it first until the user moves it
        self.assertIn("extra", [b for b in lay["settings"] if b["id"] == "system"][0]["mods"])      # and its items joined the existing System box
        self.assertEqual(urlopen(self.base + "/extra", timeout=10).read(), b"hello")
        d = self.json("/api")
        self.assertTrue(d["extra"])
        self.assertIn("extra says hi", d["warnings"])
        self.check_js(html)

    def test_editing_a_page_file_shows_up_without_a_restart(self):
        with open(os.path.join(self.modules, "led", "page.css"), "a") as f:
            f.write("\n.marker-for-the-test{color:red}\n")
        self.touch_all()
        self.assertIn("marker-for-the-test", self.page())


class Services(unittest.TestCase):
    """The LED and buttons services follow the Modules menu."""
    def setUp(self):
        self.tmp = sandbox()

    def tearDown(self):
        cleanup(self.tmp)

    def test_led_service_drives_no_leds_while_the_module_is_off(self):
        import netswitch_led as led
        import netswitch_ledconfig as ledconfig
        ledconfig.save_led_count(5)
        self.assertEqual(led.wanted_count(), 5)
        core.save_module_enabled("led", False)
        self.assertEqual(led.wanted_count(), 0)
        core.save_module_enabled("led", True)
        self.assertEqual(led.wanted_count(), 5)

    def test_buttons_service_wifi_follows_the_module(self):
        import netswitch_switcher_buttons as buttons
        self.assertFalse(buttons.wifi_enabled())                # the Wi-Fi module is off by default
        core.save_module_enabled("wifi", True)
        self.assertTrue(buttons.wifi_enabled())
        core.save_module_enabled("wifi", False)
        self.assertFalse(buttons.wifi_enabled())

    def test_buttons_service_loads_no_module_code(self):
        """Wi-Fi is layered on top: a button hold only touches wifi_start / wifi_stop; the module has its own service."""
        code = ("import sys; sys.path[:0] = %r; import netswitch_switcher_buttons; "
                "sys.exit(1 if 'netswitch_wifi_setup' in sys.modules else 0)" % [ROOT, os.path.join(ROOT, "base"), os.path.join(ROOT, "modules", "switcher")])
        self.assertEqual(subprocess.call(["python3", "-c", code]), 0)

    def test_wifi_service_idles_while_module_is_off_and_runs_a_requested_setup(self):
        import netswitch_wifi_service as svc
        import netswitch_wifi_setup as wifi
        calls = []
        old = (wifi.wifi_iface, wifi.setup_cycle)
        wifi.wifi_iface = lambda: "wlan0"
        wifi.setup_cycle = lambda iface: calls.append(iface)
        try:
            core.save_module_enabled("wifi", True)
            open(wifi.WIFI_START, "w").close()
            svc.run_once()
            self.assertEqual(calls, ["wlan0"])
            self.assertFalse(os.path.exists(wifi.WIFI_START))       # the request was consumed
            svc.run_once()                                          # nothing asked: nothing runs
            self.assertEqual(calls, ["wlan0"])
        finally:
            wifi.wifi_iface, wifi.setup_cycle = old


class InstallerTests(unittest.TestCase):
    """The module handling of install.sh (sync_modules), run on temp folders; and the module scripts parse."""
    def snippet(self):
        with open(os.path.join(ROOT, "install.sh")) as f:
            text = f.read()
        return text[text.index("# >>> sync_modules"):text.index("# <<< sync_modules")]

    def run_sync(self, src, dest):
        script = 'SRC="%s"; DEST="%s"\n%s\nsync_modules\n' % (src, dest, self.snippet())
        out = subprocess.run(["sh", "-ec", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(out.returncode, 0, out.stderr.decode())
        return out.stdout.decode()

    def setUp(self):
        self.tmp = sandbox()
        self.src, self.dest = os.path.join(self.tmp, "src"), os.path.join(self.tmp, "dest")
        shutil.copytree(REAL_MODULES, os.path.join(self.src, "modules"), ignore=shutil.ignore_patterns("__pycache__"))
        os.makedirs(self.dest)

    def tearDown(self):
        cleanup(self.tmp)

    def test_every_module_folder_is_copied(self):
        self.run_sync(self.src, self.dest)
        for n in ALL:
            self.assertTrue(os.path.exists(os.path.join(self.dest, "modules", n, "module.json")), n)
            if os.path.exists(os.path.join(REAL_MODULES, n, "layout.json")):
                self.assertTrue(os.path.exists(os.path.join(self.dest, "modules", n, "layout.json")), n)

    def test_no_pycache_is_installed(self):
        os.makedirs(os.path.join(self.src, "modules", "led", "__pycache__"))
        open(os.path.join(self.src, "modules", "led", "__pycache__", "x.pyc"), "w").close()
        self.run_sync(self.src, self.dest)
        self.assertFalse(os.path.exists(os.path.join(self.dest, "modules", "led", "__pycache__")))

    def test_a_module_dropped_from_the_folder_is_removed_and_cleans_up_after_itself(self):
        self.run_sync(self.src, self.dest)
        marker = os.path.join(self.tmp, "removed-marker")
        with open(os.path.join(self.dest, "modules", "wifi", "remove.sh"), "w") as f:      # what its remove.sh would do
            f.write('echo gone > "%s"\n' % marker)
        shutil.rmtree(os.path.join(self.src, "modules", "wifi"))
        shutil.rmtree(os.path.join(self.src, "modules", "players"))
        out = self.run_sync(self.src, self.dest)
        self.assertFalse(os.path.exists(os.path.join(self.dest, "modules", "wifi")))
        self.assertFalse(os.path.exists(os.path.join(self.dest, "modules", "players")))
        self.assertTrue(os.path.exists(os.path.join(self.dest, "modules", "led")))
        self.assertEqual(open(marker).read().strip(), "gone")
        self.assertIn("wifi", out)

    def test_a_module_added_to_the_folder_is_installed_and_old_copies_are_replaced(self):
        self.run_sync(self.src, self.dest)
        stale = os.path.join(self.dest, "modules", "led", "old-file.py")
        open(stale, "w").write("stale")
        extra = os.path.join(self.src, "modules", "extra")
        os.makedirs(extra)
        open(os.path.join(extra, "module.json"), "w").write("{}")
        os.makedirs(os.path.join(self.src, "modules", "no-manifest"))          # not a module: no module.json
        self.run_sync(self.src, self.dest)
        self.assertTrue(os.path.exists(os.path.join(self.dest, "modules", "extra", "module.json")))
        self.assertFalse(os.path.exists(os.path.join(self.dest, "modules", "no-manifest")))
        self.assertFalse(os.path.exists(stale))                                 # a module is replaced as a whole

    def test_module_scripts_parse_and_use_the_installer_variables(self):
        for n in NAMES:
            for script in ("install.sh", "remove.sh"):
                path = os.path.join(REAL_MODULES, n, script)
                if os.path.exists(path):
                    self.assertEqual(subprocess.run(["sh", "-n", path]).returncode, 0, path)
        led = open(os.path.join(REAL_MODULES, "led", "install.sh")).read()
        for needle in ("ConditionPathExists=$DEST/modules/led/netswitch_led.py", "ConditionPathExists=$DEST/modules/led/netswitch_ledconfig.py",
                       "ExecStart=$(command -v python3) $DEST/modules/led/netswitch_led.py", 'NS_SERVICES="$NS_SERVICES dreampi-netswitch-led.service"'):
            self.assertIn(needle, led)
        self.assertIn("disable --now dreampi-netswitch-led.service", open(os.path.join(REAL_MODULES, "led", "remove.sh")).read())

    def test_the_switcher_owns_its_dreampi_integration_and_buttons_service(self):
        """The DreamPi hook (.pth) and the buttons service are installed by the module, not by install.sh."""
        main = open(os.path.join(ROOT, "install.sh")).read()
        for line in main.splitlines():
            if not line.lstrip().startswith(("rm -f", "#", '"$DEST/')):          # (the old files are still removed, and mentioned in comments)
                for gone in ("netswitch_hook", "netswitch_buttons", "dreampi_netswitch.pth", "dreampi-netswitch-buttons.service", "netswitch_dreampi"):
                    self.assertNotIn(gone, line)
        text = open(os.path.join(REAL_MODULES, "switcher", "install.sh")).read()
        self.assertIn("$DEST/modules/switcher", text)
        self.assertIn("import netswitch_dreampi", text)
        self.assertIn("ExecStart=$(command -v python3) $DEST/modules/switcher/netswitch_switcher_buttons.py", text)
        self.assertIn('NS_SERVICES="$NS_SERVICES dreampi-netswitch-buttons.service"', text)
        remove = open(os.path.join(REAL_MODULES, "switcher", "remove.sh")).read()
        self.assertIn("disable --now dreampi-netswitch-buttons.service", remove)
        self.assertIn("pth_locations", remove)

    def test_installer_copies_the_loader_and_the_base_only(self):
        text = open(os.path.join(ROOT, "install.sh")).read()
        self.assertIn("base/base_*.py", text)
        for gone in ("netswitch_ledconfig.py\" ", "netswitch_players.py\" ", "page/led.html\" "):
            self.assertNotIn('cp "$SRC/' + gone.strip(), text)


class Layering(unittest.TestCase):
    def test_the_base_never_imports_module_code(self):
        """Removing a module must not break an import anywhere in the base."""
        module_files = set()
        for n in ALL:
            for f in os.listdir(os.path.join(REAL_MODULES, n)):
                if f.endswith(".py"):
                    module_files.add(f[:-3])
        files = [(n, os.path.join(ROOT, "base", n)) for n in sorted(os.listdir(os.path.join(ROOT, "base"))) if n.endswith(".py")]
        files += [(n, os.path.join(ROOT, n)) for n in sorted(os.listdir(ROOT)) if n.endswith(".py")]
        for name, path in files:
            with open(path) as f:
                for line in f:
                    m = re.match(r"\s*(?:import|from)\s+(\w+)", line)
                    if m and m.group(1) in module_files:
                        # one place loads a module's code on purpose, guarded: the hook inside DreamPi (the debug log's part)
                        self.assertIn((name, m.group(1)), [("netswitch_dreampi.py", "netswitch_hookdebug")], (name, line))

    def test_modules_only_use_the_base_and_themselves(self):
        base = set(f[:-3] for d in (ROOT, os.path.join(ROOT, "base")) for f in os.listdir(d) if f.endswith(".py"))
        for n in ALL:
            own = set(f[:-3] for f in os.listdir(os.path.join(REAL_MODULES, n)) if f.endswith(".py"))
            for f in own:
                with open(os.path.join(REAL_MODULES, n, f + ".py")) as fh:
                    for line in fh:
                        m = re.match(r"\s*(?:import|from)\s+(netswitch_\w+)", line)
                        if m:
                            self.assertTrue(m.group(1) in own or m.group(1) in base, (n, f, line))


if __name__ == "__main__":
    unittest.main()
