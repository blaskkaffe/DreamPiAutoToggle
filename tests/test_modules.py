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
NAMES = ["checkin", "clock", "contacts", "imagebg", "rebootupdate", "wifi"]      # the modules the picker can switch
HIDDEN = ["system"]                                                # always on, not in the picker
ALL = sorted(NAMES + HIDDEN)
# a path only that module answers (GET, or POST when None)
ENDPOINT = {"checkin": ("GET", "/checkin"), "clock": ("GET", "/clock"), "contacts": ("GET", "/contacts"), "imagebg": ("GET", "/imagebg"), "wifi": ("POST", "/wifitoggle"), "rebootupdate": ("GET", "/update")}
HIDDEN_ENDPOINT = {"system": ("GET", "/about")}
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
        core.save_module_enabled("imagebg", True)        # off by default: the tests want to see it
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
        self.assertEqual(on, {"checkin": True, "clock": True, "contacts": True, "imagebg": False, "rebootupdate": True, "system": True, "wifi": False})
        hidden = [n for n in ALL if json.load(open(os.path.join(REAL_MODULES, n, "module.json")))["visible"] is False]
        self.assertEqual(hidden, HIDDEN)                   # the system info can't be switched off


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
        system = [b for b in lay["settings"] if b["id"] == "system"][0]
        self.assertEqual(system["mods"], ["wifi", "rebootupdate"])
        self.assertEqual([w["type"] for w in system["items"] if w["mod"] == "rebootupdate"][-1], "row")      # the Reboot row ends the System box
        ids = [b["id"] for b in lay["settings"]]
        self.assertEqual(ids[-1], "system")                                                                # System is the very last box
        self.assertLess(ids.index("about"), ids.index("background-image"))                                  # settings-only modules come before the backgrounds
        about = [b for b in lay["settings"] if b["id"] == "about"][0]
        self.assertEqual((about["mods"], about["title"]), (["system"], "About"))               # the versions are their own box, not part of System
        self.assertEqual([b["id"] for b in lay["dashboard"]], ["checkin", "clock"])
        self.assertEqual([b["id"] for b in lay["settings"]], ["check-in", "appearance", "clock", "contacts", "colours", "about", "background-image", "system"])

    def test_the_picker_lists_dashboard_modules_then_settings_only_then_backgrounds(self):
        core.save_module_order(["imagebg", "wifi", "contacts", "clock", "system", "checkin"])      # the user's own mix
        names = core.module_names()
        groups = [core.module_group(n) for n in names]
        self.assertEqual(groups, sorted(groups))
        self.assertEqual((core.module_group("checkin"), core.module_group("system"), core.module_group("imagebg")), (0, 1, 2))
        self.assertLess(names.index("clock"), names.index("checkin"))                       # inside a group the user's order stays: clock was before checkin

    def test_moving_tiles_on_the_main_screen_reorders_those_modules_only(self):
        core.save_module_order(["checkin", "clock", "contacts", "system", "wifi", "rebootupdate", "imagebg"])
        new = core.save_dashboard_order(["clock", "checkin"])                                # two tiles moved: they take each other's places
        self.assertEqual(new[:2], ["clock", "checkin"])
        self.assertEqual(new[2:], ["contacts", "system", "wifi", "rebootupdate", "imagebg"])
        self.assertEqual(core.save_dashboard_order(["nope", "checkin"])[:2], ["clock", "checkin"])      # unknown names are ignored
        self.assertIsNone(core.save_dashboard_order("clock"))

    def test_system_is_the_last_settings_box_whatever_the_picker_order(self):
        core.save_module_order(["rebootupdate", "wifi", "system", "contacts", "clock", "checkin"])
        lay = layout_of(self.page())
        self.assertEqual([b["id"] for b in lay["settings"]][-1], "system")
        self.assertEqual(len([b for b in lay["settings"] if b["id"] == "system"]), 1)

    def test_the_about_module_is_listed_as_about_and_moves_its_box(self):
        got = {m["name"]: m["title"] for m in self.json("/modules")["modules"]}
        self.assertEqual(got["system"], "About")                                   # the picker row says what it moves
        core.save_module_order(["system"])                                         # the rest keeps its order after it
        web.refresh_page(force=True)
        ids = [b["id"] for b in layout_of(self.page())["settings"]]
        first_settings_only = [b["id"] for b in layout_of(self.page())["settings"] if b["mods"] == ["contacts"]][0]
        self.assertLess(ids.index("about"), ids.index(first_settings_only))        # first among the settings-only modules (the dashboard ones stay above them)

    def test_protected_paths_are_the_modules_own_post_routes(self):
        import netswitch_modules as mods
        self.assertEqual(mods._state["protected"], {"/reboot", "/update/start", "/wificonnect", "/contacts/import", "/contacts/active"})
        for path in mods._state["protected"]:
            self.assertTrue(mods.route("POST", path), path)

    def test_modules_menu_lists_them_all(self):
        got = self.json("/modules")["modules"]
        self.assertEqual([m["name"] for m in got], ["checkin", "clock", "contacts", "system", "wifi", "rebootupdate", "imagebg"])   # picker order, the always-on modules included
        self.assertEqual([m["name"] for m in got if m["visible"] is False], ["system"])                     # which the page lists without a switch
        self.assertTrue(all(m["enabled"] for m in got))
        self.assertTrue(all(m["title"] and m["description"] for m in got))


class WithNothing(Base):
    """The base alone: the page frame, About and the Modules menu."""
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
        self.assertEqual(layout_of(html)["modules"], ["system"])
        for word in ("Check-in board", "contacts-import", "@@"):
            self.assertNotIn(word, html, word)
        self.check_js(html)

    def test_no_module_endpoints(self):
        for n, (method, path) in ENDPOINT.items():
            self.assertEqual(self.status(method, path), 404, (n, path))

    def test_everything_in_the_base_still_works(self):
        d = self.json("/api")
        self.assertNotIn("checkin", d)
        self.assertNotIn("wifi", d)
        self.assertEqual(self.status("GET", "/about"), 200)
        self.assertEqual([m["name"] for m in self.json("/modules")["modules"]], ["system"])      # only the always-on one is left

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
        self.status("POST", "/modules", {"name": "contacts", "enabled": False})
        with open(core.MODULES_STATE) as f:
            self.assertEqual(json.load(f)["contacts"], False)
        self.assertFalse(core.module_enabled("contacts"))
        self.assertTrue(core.module_enabled("checkin"))

    def test_bad_menu_requests(self):
        self.assertEqual(self.status("POST", "/modules", {"name": "nope", "enabled": True}), 404)
        self.assertEqual(self.status("POST", "/modules", {"name": "system", "enabled": False}), 404)       # not in the picker
        self.assertEqual(self.status("POST", "/modules", {"name": "clock"}), 400)
        self.assertEqual(self.status("POST", "/modules", {"name": "clock", "enabled": "yes"}), 400)
        self.assertEqual(self.status("POST", "/modules", {"name": "../x", "enabled": True}), 404)
        req = Request(self.base + "/modules", method="POST", data=b'{"name":"clock","enabled":false}')
        with self.assertRaises(HTTPError) as cm:                  # from another site: no header, no origin
            urlopen(req, timeout=10)
        self.assertEqual(cm.exception.code, 403)
        self.assertTrue(core.module_enabled("clock"))


class BrokenAndNewModules(Base):
    def test_a_module_that_fails_to_import_is_reported_and_the_rest_works(self):
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
        self.assertTrue(present(html, "checkin"))
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
        with open(os.path.join(self.modules, "checkin", "page.css"), "a") as f:
            f.write("\n.marker-for-the-test{color:red}\n")
        self.touch_all()
        self.assertIn("marker-for-the-test", self.page())


class Services(unittest.TestCase):
    """The Wi-Fi service follows the Modules menu."""
    def setUp(self):
        self.tmp = sandbox()

    def tearDown(self):
        cleanup(self.tmp)

    def test_wifi_service_idles_while_module_is_off_and_runs_a_requested_setup(self):
        import netswitch_wifi_service as svc
        import netswitch_wifi_setup as wifi
        calls = []
        old = (wifi.wifi_iface, wifi.setup_cycle)
        wifi.wifi_iface = lambda: "wlan0"
        wifi.setup_cycle = lambda iface: calls.append(iface)
        try:
            core.save_module_enabled("wifi", True)
            open(core.WIFI_START, "w").close()
            svc.run_once()
            self.assertEqual(calls, ["wlan0"])
            self.assertFalse(os.path.exists(core.WIFI_START))       # the request was consumed
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
        os.makedirs(os.path.join(self.src, "modules", "clock", "__pycache__"))
        open(os.path.join(self.src, "modules", "clock", "__pycache__", "x.pyc"), "w").close()
        self.run_sync(self.src, self.dest)
        self.assertFalse(os.path.exists(os.path.join(self.dest, "modules", "clock", "__pycache__")))

    def test_a_module_dropped_from_the_folder_is_removed_and_cleans_up_after_itself(self):
        self.run_sync(self.src, self.dest)
        marker = os.path.join(self.tmp, "removed-marker")
        with open(os.path.join(self.dest, "modules", "wifi", "remove.sh"), "w") as f:      # what its remove.sh would do
            f.write('echo gone > "%s"\n' % marker)
        shutil.rmtree(os.path.join(self.src, "modules", "wifi"))
        shutil.rmtree(os.path.join(self.src, "modules", "contacts"))
        out = self.run_sync(self.src, self.dest)
        self.assertFalse(os.path.exists(os.path.join(self.dest, "modules", "wifi")))
        self.assertFalse(os.path.exists(os.path.join(self.dest, "modules", "contacts")))
        self.assertTrue(os.path.exists(os.path.join(self.dest, "modules", "clock")))
        self.assertEqual(open(marker).read().strip(), "gone")
        self.assertIn("wifi", out)

    def test_a_module_added_to_the_folder_is_installed_and_old_copies_are_replaced(self):
        self.run_sync(self.src, self.dest)
        stale = os.path.join(self.dest, "modules", "clock", "old-file.py")
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
        wifi = open(os.path.join(REAL_MODULES, "wifi", "install.sh")).read()
        for needle in ('NS_SERVICES="$NS_SERVICES dreampi-netswitch-wifi.service"',):
            self.assertIn(needle, wifi)
        self.assertIn("disable --now dreampi-netswitch-wifi.service", open(os.path.join(REAL_MODULES, "wifi", "remove.sh")).read())

    def test_installer_copies_the_loader_and_the_base_only(self):
        text = open(os.path.join(ROOT, "install.sh")).read()
        self.assertIn("netswitch_modules.py", text)
        for gone in ("netswitch_contacts.py", "netswitch_checkin.py"):
            self.assertNotIn('cp "$SRC/' + gone, text)           # modules are copied as folders, never one by one


class Layering(unittest.TestCase):
    def test_the_base_never_imports_module_code(self):
        """Removing a module must not break an import anywhere in the base."""
        module_files = set()
        for n in ALL:
            for f in os.listdir(os.path.join(REAL_MODULES, n)):
                if f.endswith(".py"):
                    module_files.add(f[:-3])
        for name in sorted(os.listdir(ROOT)):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(ROOT, name)) as f:
                for line in f:
                    m = re.match(r"\s*(?:import|from)\s+(\w+)", line)
                    if m and m.group(1) in module_files:
                        self.fail("%s imports module code: %s" % (name, line))

    def test_modules_only_use_the_base_and_themselves(self):
        base = set(f[:-3] for f in os.listdir(ROOT) if f.endswith(".py"))
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
