"""Connections between modules (netswitch_bus.py): what modules declare, the links the user makes, running them in any process,
and the rules that keep every module usable without the others."""
import json
import os
import shutil
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from support import ROOT, web, core, sandbox, cleanup
import netswitch_bus as bus

REAL_MODULES = os.path.join(ROOT, "modules")
SELECT = {"from": "numbers.call_dcnow", "to": "switcher.select_network", "params": {"network": "dcnet"}}


class BusBase(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        self.modules = os.path.join(self.tmp, "modules")
        shutil.copytree(REAL_MODULES, self.modules, ignore=shutil.ignore_patterns("__pycache__"))
        self.saved, core.MODULES_DIR = core.MODULES_DIR, self.modules
        bus._io_cache.clear()

    def tearDown(self):
        core.MODULES_DIR = self.saved
        bus._io_cache.clear()
        web.refresh_page(force=True)
        cleanup(self.tmp)

    def selected(self):
        return "dcnet" if os.path.exists(core.FLAG) else "dcnow"

    def add_module(self, name, io_source, inputs=None, outputs=None):
        folder = os.path.join(self.modules, name)
        os.makedirs(folder)
        manifest = {"name": name.title(), "description": "d", "enabled": True, "visible": True, "io": "netswitch_%s_io" % name,
                    "inputs": inputs or [], "outputs": outputs or []}
        with open(os.path.join(folder, "module.json"), "w") as f:
            json.dump(manifest, f)
        with open(os.path.join(folder, "netswitch_%s_io.py" % name), "w") as f:
            f.write(io_source)


class ContractTests(unittest.TestCase):
    """Every module of the repo keeps the rules of the bus."""
    def test_every_declared_input_has_a_handler_and_every_io_file_loads_alone(self):
        import subprocess
        import sys
        for name in sorted(os.listdir(REAL_MODULES)):
            path = os.path.join(REAL_MODULES, name, "module.json")
            if not os.path.exists(path):
                continue
            with open(path) as f:
                manifest = json.load(f)
            declared = [i["id"] for i in manifest.get("inputs", [])]
            if not (declared or manifest.get("io")):
                continue
            self.assertTrue(manifest.get("io"), "%s declares inputs but has no io file" % name)
            code = ("import sys; sys.path[:0] = [%r, %r]; import %s as m; "
                    "bad = [i for i in %r if i not in m.INPUTS]; "
                    "sys.exit(1 if bad or 'netswitch_web' in sys.modules else 0)" % (ROOT, os.path.join(REAL_MODULES, name), manifest["io"], declared))
            self.assertEqual(subprocess.call([sys.executable, "-c", code]), 0, name)       # it needs no other module and not the web server

    def test_outputs_and_inputs_are_declared_properly(self):
        for name in sorted(os.listdir(REAL_MODULES)):
            path = os.path.join(REAL_MODULES, name, "module.json")
            if not os.path.exists(path):
                continue
            with open(path) as f:
                manifest = json.load(f)
            for kind in ("inputs", "outputs"):
                for d in manifest.get(kind, []):
                    self.assertTrue(bus._valid_declaration(d), (name, kind, d))
                    self.assertEqual([p["key"] for p in d.get("params", [])], [q["key"] for q in [bus._param(p) for p in d.get("params", [])] if q], (name, d))


class DeclarationTests(BusBase):
    def ids(self, kind, **kw):
        return [i["id"] for i in bus.declarations(**kw)[kind]]

    def test_the_modules_declare_what_they_do_and_tell(self):
        self.assertIn("switcher.select_network", self.ids("inputs"))
        self.assertIn("switcher.network_selected", self.ids("outputs"))
        self.assertIn("numbers.call_dcnow", self.ids("outputs"))
        self.assertIn("wifi.start_setup", self.ids("inputs", installed=True))

    def test_only_loaded_modules_are_offered_but_a_module_that_is_off_is_still_known(self):
        self.assertNotIn("wifi.start_setup", self.ids("inputs"))                  # the Wi-Fi module is off by default
        core.save_module_enabled("wifi", True)
        self.assertIn("wifi.start_setup", self.ids("inputs"))
        core.save_module_enabled("wifi", False)
        self.assertIn("wifi.start_setup", self.ids("inputs", installed=True))

    def test_the_base_has_a_few_common_inputs_and_outputs(self):
        self.assertIn("app.notice", self.ids("inputs"))
        self.assertIn("app.colour", self.ids("inputs"))
        self.assertIn("app.started", self.ids("outputs"))

    def test_the_colour_input_lists_the_colours_of_the_loaded_modules(self):
        colour = [i for i in bus.declarations()["inputs"] if i["id"] == "app.colour"][0]
        targets = [o[0] for o in colour["params"][0]["options"]]
        self.assertIn("switcher.dcnow", targets)
        self.assertIn("clock.clock", targets)
        shutil.rmtree(os.path.join(self.modules, "clock"))
        colour = [i for i in bus.declarations()["inputs"] if i["id"] == "app.colour"][0]
        self.assertNotIn("clock.clock", [o[0] for o in colour["params"][0]["options"]])

    def test_a_broken_declaration_is_ignored(self):
        self.add_module("odd", "INPUTS = {}", inputs=[{"id": "Bad Id", "label": "x"}, {"id": "ok", "label": "Fine", "params": [{"key": "Z", "type": "select"}]}])
        self.assertEqual([i for i in self.ids("inputs") if i.startswith("odd.")], ["odd.ok"])
        self.assertEqual([i for i in bus.declarations()["inputs"] if i["id"] == "odd.ok"][0]["params"], [])      # the bad parameter is dropped


class LinkTests(BusBase):
    def test_the_standard_links_are_the_old_behaviour(self):
        got = bus.links()
        self.assertEqual(len(got), 4)
        self.assertIn({"from": "numbers.call_dcnow", "to": "switcher.select_network", "params": {"network": "dcnow"}}, got)
        self.assertIn({"from": "numbers.toggle_dcnet", "to": "switcher.select_network", "params": {"network": "dcnet"}}, got)

    def test_the_users_links_replace_the_standard_ones_even_when_there_are_none(self):
        bus.save_links([SELECT])
        self.assertEqual(bus.links(), [SELECT])
        bus.save_links([])
        self.assertEqual(bus.links(), [])
        bus.reset_links()
        self.assertEqual(len(bus.links()), 4)

    def test_links_are_made_safe(self):
        got = bus.clean_links([SELECT, SELECT,                                                         # a repeat
                               {"from": "nowhere.x", "to": "switcher.select_network"},                 # an output that does not exist
                               {"from": "numbers.call_dcnow", "to": "switcher.nothing"},               # an input that does not exist
                               {"from": "numbers.call_dcnow", "to": "switcher.select_network", "params": {"network": "mars", "stray": 1}},
                               {"from": "numbers.call_dcnow", "to": "app.notice", "params": {"text": "x" * 500, "seconds": 99999}},
                               "junk", None])
        self.assertEqual(got[0], SELECT)
        self.assertEqual(got[1]["params"], {"network": "dcnow"})                                       # a value that does not fit: the default
        self.assertEqual(got[2]["params"], {"text": "x" * 120, "seconds": 3600.0})
        self.assertEqual(len(got), 3)

    def test_a_link_to_a_module_that_is_off_is_kept_for_when_it_comes_back(self):
        link = {"from": "numbers.call_dcnow", "to": "wifi.start_setup", "params": {}}
        bus.save_links([link])
        self.assertEqual(bus.links(), [link])                      # wifi is off, the link stays
        self.assertEqual(bus.emit("numbers.call_dcnow")[0]["error"], "module is off")


class RunTests(BusBase):
    def test_an_output_runs_what_it_is_linked_to(self):
        bus.save_links([SELECT])
        res = bus.emit("numbers.call_dcnow", {"number": "11111"}, {"source": "test"})
        self.assertEqual([(r["to"], r["ok"]) for r in res], [("switcher.select_network", True)])
        self.assertEqual(self.selected(), "dcnet")

    def test_one_output_can_do_several_things_and_an_unlinked_output_does_nothing(self):
        bus.save_links([SELECT, {"from": "numbers.call_dcnow", "to": "app.notice", "params": {"text": "Hi", "seconds": 30}}])
        self.assertEqual(len(bus.emit("numbers.call_dcnow")), 2)
        self.assertEqual([n["text"] for n in bus.active_notices()], ["Hi"])
        self.assertEqual(bus.emit("numbers.toggle_dcnow"), [])
        self.assertEqual(bus.emit("nothing.at_all"), [])

    def test_a_module_that_is_not_there_costs_nothing(self):
        shutil.rmtree(os.path.join(self.modules, "numbers"))          # no numbers module: its outputs are gone, the switcher still works alone
        self.assertEqual(bus.emit("numbers.call_dcnow"), [])
        self.assertTrue(bus.run_input("switcher.select_network", {"network": "dcnet"})["ok"])
        self.assertEqual(self.selected(), "dcnet")

    def test_the_switcher_not_there_the_numbers_still_work_on_their_own(self):
        shutil.rmtree(os.path.join(self.modules, "switcher"))
        bus.save_links([SELECT])
        self.assertEqual(bus.links(), [])                              # the link to a module that is not installed is dropped
        self.assertEqual(bus.emit("numbers.call_dcnow"), [])
        self.assertEqual(self.selected(), "dcnow")

    def test_what_an_output_tells_can_be_used_in_a_text(self):
        bus.save_links([{"from": "switcher.network_selected", "to": "app.notice", "params": {"text": "Now on {network_name}", "seconds": 30}}])
        bus.run_input("switcher.select_network", {"network": "dcnet"}, {"source": "test"})
        self.assertEqual([n["text"] for n in bus.active_notices()], ["Now on DCNET"])
        bus.run_input("switcher.select_network", {"network": "dcnet"})          # no change, nothing told
        self.assertEqual(len(bus.active_notices()), 1)

    def test_a_handler_that_fails_does_not_stop_the_others(self):
        self.add_module("boom", "def fail(p, c):\n    raise RuntimeError('no')\nINPUTS = {'fail': fail}", inputs=[{"id": "fail", "label": "Fail"}])
        bus.save_links([{"from": "numbers.call_dcnow", "to": "boom.fail", "params": {}}, SELECT])
        res = bus.emit("numbers.call_dcnow")
        self.assertEqual([r["ok"] for r in res], [False, True])
        self.assertEqual(self.selected(), "dcnet")

    def test_a_module_whose_io_file_does_not_load_is_skipped(self):
        self.add_module("bad", "this is not python", inputs=[{"id": "x", "label": "X"}])
        self.assertFalse(bus.run_input("bad.x")["ok"])

    def test_an_output_that_tells_itself_stops(self):
        self.add_module("loop", "import netswitch_bus as bus\ncalls = []\n"
                                "def again(p, c):\n    calls.append(1)\n    bus.emit('loop.out')\nINPUTS = {'again': again}",
                        inputs=[{"id": "again", "label": "Again"}], outputs=[{"id": "out", "label": "Out"}])
        bus.save_links([{"from": "loop.out", "to": "loop.again", "params": {}}])
        bus.emit("loop.out")
        self.assertEqual(len(bus._io_module("loop").calls), bus.MAX_DEPTH)

    def test_the_colour_input_changes_a_modules_colour(self):
        r = bus.run_input("app.colour", {"target": "switcher.dcnow", "colour": "green"})
        self.assertTrue(r["ok"])
        self.assertEqual(core.module_colours("switcher")["dcnow"], "green")
        self.assertFalse(bus.run_input("app.colour", {"target": "nope.x", "colour": "green"})["ok"])

    def test_a_box_can_be_made_to_stand_out_for_a_while(self):
        boxes = [o[0] for i in bus.declarations()["inputs"] if i["id"] == "app.highlight" for o in i["params"][0]["options"]]
        self.assertIn("network", boxes)
        self.assertIn("clock", boxes)
        self.assertTrue(bus.run_input("app.highlight", {"box": "Clock", "seconds": 30, "why": "Look here"})["ok"])
        self.assertEqual(bus.active_highlights(), {"clock": "Look here"})
        with open(core.HIGHLIGHTS) as f:
            data = json.load(f)
        data["clock"]["until"] = time.time() - 1
        with open(core.HIGHLIGHTS, "w") as f:
            json.dump(data, f)
        self.assertEqual(bus.active_highlights(), {})
        self.assertFalse(bus.run_input("app.highlight", {"box": ""})["ok"])

    def test_an_led_alert_lights_its_message_for_a_while(self):
        import sys
        sys.path.insert(0, os.path.join(REAL_MODULES, "led"))
        import netswitch_ledconfig as ledconfig
        ledconfig.save_led_config({"groups": [{"id": "g1", "colour": "red", "effect": "blink", "speed": "fast", "messages": ["alert-b"]}]})
        ctx = lambda: dict(ledconfig.gather(live=False), alerts=core.led_alerts())
        self.assertEqual(ledconfig.active_messages(ctx()), [])
        bus.save_links([{"from": "numbers.call_dcnow", "to": "led.alert", "params": {"slot": "b", "seconds": 30}}])
        bus.emit("numbers.call_dcnow")
        looks = ledconfig.active_messages(ctx())
        self.assertEqual([(m["key"], m["messages"], m["effect"]) for m in looks], [("g1", ["alert-b"], "blink")])
        with open(core.LED_ALERTS, "w") as f:
            json.dump({"b": time.time() - 1}, f)
        self.assertEqual(ledconfig.active_messages(ctx()), [])

    def test_notices_expire_and_can_be_dismissed(self):
        bus.run_input("app.notice", {"text": "Soon gone", "seconds": 1})
        bus.run_input("app.notice", {"text": "Stays", "seconds": 60})
        self.assertEqual(len(bus.active_notices()), 2)
        first = bus.active_notices()[0]["id"]
        bus.dismiss_notice(first)
        self.assertEqual([n["text"] for n in bus.active_notices()], ["Stays"])
        with open(core.NOTICES) as f:
            data = json.load(f)
        data[0]["until"] = time.time() - 1
        with open(core.NOTICES, "w") as f:
            json.dump(data, f)
        self.assertEqual(bus.active_notices(), [])


class ProfileTests(BusBase):
    def test_the_profile_can_start_a_module_on_or_off(self):
        saved = core.PROFILE
        try:
            with open(os.path.join(self.tmp, "profile.json"), "w") as f:
                json.dump({"modules": {"clock": False, "wifi": True}}, f)
            core.PROFILE = os.path.join(self.tmp, "profile.json")
            self.assertFalse(core.module_enabled("clock"))
            self.assertTrue(core.module_enabled("wifi"))
            core.save_module_enabled("clock", True)                     # the user's own choice wins
            self.assertTrue(core.module_enabled("clock"))
        finally:
            core.PROFILE = saved


class WebTests(unittest.TestCase):
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
        return json.loads(urlopen(self.base + path, timeout=10).read().decode())

    def post(self, path, body=None, header=True):
        headers = {"Content-Type": "application/json"}
        if header:
            headers["X-Requested-With"] = "netswitch"
        raw = urlopen(Request(self.base + path, data=json.dumps(body or {}).encode(), method="POST", headers=headers), timeout=10).read().decode()
        return json.loads(raw) if raw else {}

    def test_the_page_gets_everything_the_editor_needs(self):
        r = self.get("/bus")
        self.assertIn("numbers.call_dcnow", [o["id"] for o in r["outputs"]])
        self.assertIn("switcher.select_network", [i["id"] for i in r["inputs"]])
        self.assertEqual(r["links"], r["defaults"])

    def test_links_are_saved_cleaned_and_reset(self):
        r = self.post("/bus/links", {"links": [SELECT, {"from": "x.y", "to": "z.w"}]})
        self.assertEqual(r["links"], [SELECT])
        self.assertEqual(self.get("/bus")["links"], [SELECT])
        self.assertEqual(self.post("/bus/reset")["links"], self.get("/bus")["defaults"])

    def test_only_the_page_itself_may_change_them(self):
        with self.assertRaises(HTTPError) as e:
            self.post("/bus/links", {"links": []}, header=False)
        self.assertEqual(e.exception.code, 403)

    def test_a_notice_reaches_the_page_and_can_be_dismissed(self):
        bus.run_input("app.notice", {"text": "From a link", "seconds": 30})
        notices = self.get("/api")["notices"]
        self.assertEqual([n["text"] for n in notices], ["From a link"])
        self.post("/bus/dismiss", {"id": notices[0]["id"]})
        self.assertEqual(self.get("/api")["notices"], [])

    def test_the_network_buttons_of_the_page_use_the_same_input(self):
        self.post("/dcnet")
        self.assertTrue(os.path.exists(core.FLAG))
        self.post("/dcnow")
        self.assertFalse(os.path.exists(core.FLAG))


if __name__ == "__main__":
    unittest.main()
