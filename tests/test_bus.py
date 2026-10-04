"""Connections between modules (netswitch_bus.py): the boolean jacks modules declare, the cables the user makes, running them in any
process, and the rules that keep every module usable without the others."""
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
SELECT = {"from": "numbers.call_dcnow", "to": "switcher.select_dcnet", "invert": False}


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
        """A module made for a test: its inputs and outputs as [{"id", "label"}], its io file's source."""
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

    def test_every_computed_output_has_a_reader_and_none_is_unknown(self):
        for name in sorted(os.listdir(REAL_MODULES)):
            path = os.path.join(REAL_MODULES, name, "module.json")
            if not os.path.exists(path):
                continue
            with open(path) as f:
                manifest = json.load(f)
            if not manifest.get("io"):
                continue
            import importlib
            sys_path = os.path.join(REAL_MODULES, name)
            import sys
            sys.path.insert(0, sys_path)
            try:
                io = importlib.import_module(manifest["io"])
            finally:
                sys.path.remove(sys_path)
            declared_in = set(i["id"] for i in manifest.get("inputs", []))
            declared_out = set(o["id"] for o in manifest.get("outputs", []))
            self.assertLessEqual(set(getattr(io, "INPUTS", {})), declared_in, name)       # nothing undeclared
            self.assertLessEqual(set(getattr(io, "OUTPUTS", {})), declared_out, name)

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

    def test_the_modules_declare_their_jacks(self):
        self.assertIn("switcher.select_dcnet", self.ids("inputs"))
        self.assertIn("switcher.dcnet_selected", self.ids("outputs"))
        self.assertIn("numbers.call_dcnow", self.ids("outputs"))
        self.assertIn("players.game_played", self.ids("outputs"))
        self.assertIn("led.alert_a", self.ids("inputs"))
        self.assertIn("wifi.start_setup", self.ids("inputs", installed=True))

    def test_only_loaded_modules_are_offered_but_a_module_that_is_off_is_still_known(self):
        self.assertNotIn("wifi.start_setup", self.ids("inputs"))                  # the Wi-Fi module is off by default
        core.save_module_enabled("wifi", True)
        self.assertIn("wifi.start_setup", self.ids("inputs"))
        core.save_module_enabled("wifi", False)
        self.assertIn("wifi.start_setup", self.ids("inputs", installed=True))

    def test_the_base_has_a_few_common_jacks(self):
        for iid in ("app.notice_a", "app.highlight_b", "app.colour_c", "app.timer1_start", "app.timer2_start"):
            self.assertIn(iid, self.ids("inputs"))
        for oid in ("app.on", "app.started", "app.timer1_running", "app.timer2_running"):
            self.assertIn(oid, self.ids("outputs"))

    def test_the_colour_input_lists_the_colours_of_the_loaded_modules(self):
        colour = [i for i in bus.declarations()["inputs"] if i["id"] == "app.colour_a"][0]
        targets = [o[0] for o in colour["params"][0]["options"]]
        self.assertIn("switcher.dcnow", targets)
        self.assertIn("clock.clock", targets)
        shutil.rmtree(os.path.join(self.modules, "clock"))
        colour = [i for i in bus.declarations()["inputs"] if i["id"] == "app.colour_a"][0]
        self.assertNotIn("clock.clock", [o[0] for o in colour["params"][0]["options"]])

    def test_a_broken_declaration_is_ignored(self):
        self.add_module("odd", "INPUTS = {}", inputs=[{"id": "Bad Id", "label": "x"}, {"id": "ok", "label": "Fine", "params": [{"key": "Z", "type": "select"}]}])
        self.assertEqual([i for i in self.ids("inputs") if i.startswith("odd.")], ["odd.ok"])
        self.assertEqual([i for i in bus.declarations()["inputs"] if i["id"] == "odd.ok"][0]["params"], [])      # the bad knob is dropped


class CableTests(BusBase):
    def test_the_standard_cables_are_the_old_behaviour(self):
        got = bus.links()
        self.assertEqual(len(got), 4)
        self.assertIn({"from": "numbers.call_dcnow", "to": "switcher.select_dcnow", "invert": False}, got)
        self.assertIn({"from": "numbers.toggle_dcnet", "to": "switcher.select_dcnet", "invert": False}, got)

    def test_the_users_cables_replace_the_standard_ones_even_when_there_are_none(self):
        bus.save_links([SELECT])
        self.assertEqual(bus.links(), [SELECT])
        bus.save_links([])
        self.assertEqual(bus.links(), [])
        bus.reset_links()
        self.assertEqual(len(bus.links()), 4)

    def test_cables_are_made_safe(self):
        inv = dict(SELECT, invert=True)
        got = bus.clean_links([SELECT, SELECT,                                                         # a repeat
                               inv,                                                                    # the same cable inverted is another cable
                               {"from": "nowhere.x", "to": "switcher.select_dcnet"},                   # an output that does not exist
                               {"from": "numbers.call_dcnow", "to": "switcher.nothing"},               # an input that does not exist
                               {"from": "numbers.call_dcnow", "to": "switcher.select_dcnow", "invert": "yes"},      # invert is true or false
                               "junk", None])
        self.assertEqual(got, [SELECT, inv, {"from": "numbers.call_dcnow", "to": "switcher.select_dcnow", "invert": False}])

    def test_knobs_are_kept_per_input_and_made_to_fit(self):
        bus.save_links([], {"app.notice_a": {"text": "x" * 500, "seconds": 99999}, "app.colour_a": {"target": "nope", "colour": "mauve"}, "stray.x": {"a": 1}})
        kn = bus.knobs()
        self.assertEqual(kn["app.notice_a"], {"text": "x" * 120, "seconds": 3600.0})
        self.assertEqual(kn["app.colour_a"]["target"], bus.declarations()["inputs"][2]["params"][0]["default"])       # not a colour that exists: the default
        self.assertNotIn("stray.x", kn)
        self.assertNotIn("switcher.select_dcnet", kn)                                                              # an input without knobs has none

    def test_a_cable_to_a_module_that_is_off_is_kept_for_when_it_comes_back(self):
        cable = {"from": "numbers.call_dcnow", "to": "wifi.start_setup", "invert": False}
        bus.save_links([cable])
        self.assertEqual(bus.links(), [cable])                      # wifi is off, the cable stays
        bus.pulse("numbers.call_dcnow", 30)
        self.assertFalse(os.path.exists(core.WIFI_START))             # the module is off: it was not told
        core.save_module_enabled("wifi", True)
        bus.poll()                                                    # back: it hears that its input is on
        self.assertTrue(os.path.exists(core.WIFI_START))


class JackTests(BusBase):
    def test_an_input_is_off_by_default_and_a_cable_turns_it_on_while_the_output_is_on(self):
        bus.save_links([SELECT])
        self.assertFalse(bus.input_level("switcher.select_dcnet"))
        ran = bus.pulse("numbers.call_dcnow", 30, {"source": "test"})
        self.assertEqual(ran, ["switcher.select_dcnet"])
        self.assertEqual((bus.input_level("switcher.select_dcnet"), self.selected()), (True, "dcnet"))
        bus.set_output("numbers.call_dcnow", False)
        self.assertEqual((bus.input_level("switcher.select_dcnet"), self.selected()), (False, "dcnet"))      # off again; the network stays selected

    def test_an_inverted_cable_is_on_while_the_output_is_off(self):
        bus.save_links([{"from": "app.timer1_running", "to": "led.alert_a", "invert": True}])
        self.assertTrue(bus.input_level("led.alert_a"))                          # (resync at save: the timer is not running)
        bus.set_output("app.timer1_running", True)
        self.assertFalse(bus.input_level("led.alert_a"))

    def test_an_input_is_on_while_any_cable_or_caller_holds_it(self):
        bus.save_links([{"from": "numbers.call_dcnow", "to": "led.alert_a"}, {"from": "numbers.call_dcnet", "to": "led.alert_a"}])
        bus.set_output("numbers.call_dcnow", True)
        bus.set_output("numbers.call_dcnet", True)
        bus.set_input("led.alert_a", True, "somebody")
        bus.set_output("numbers.call_dcnow", False)
        bus.set_output("numbers.call_dcnet", False)
        self.assertTrue(bus.input_level("led.alert_a"))                          # the caller still holds it
        bus.set_input("led.alert_a", False, "somebody")
        self.assertFalse(bus.input_level("led.alert_a"))

    def test_a_module_can_turn_another_modules_input_on_through_the_api(self):
        self.assertEqual(bus.set_input("switcher.select_dcnet", True, "test"), ["switcher.select_dcnet"])
        self.assertEqual(self.selected(), "dcnet")
        self.assertEqual(bus.set_input("switcher.select_dcnet", True, "test"), [])        # already on: no new edge
        bus.set_input("switcher.select_dcnet", False, "test")
        os.remove(core.FLAG)
        self.assertEqual(bus.set_input("switcher.select_dcnet", True, "test"), ["switcher.select_dcnet"])       # a new edge
        self.assertEqual(self.selected(), "dcnet")

    def test_a_module_is_told_once_per_change_with_its_knobs(self):
        self.add_module("rec", "calls = []\ndef go(on, knobs, ctx):\n    calls.append((on, knobs, ctx.get('source')))\nINPUTS = {'go': go}",
                        inputs=[{"id": "go", "label": "Go", "params": [{"key": "n", "type": "number", "default": 3}]}])
        bus.set_input("rec.go", True, "a", {"source": "test"})
        bus.set_input("rec.go", True, "b")                                       # a second holder: no second call
        bus.set_input("rec.go", False, "a")
        bus.set_input("rec.go", False, "b")
        self.assertEqual(bus._io_module("rec").calls, [(True, {"n": 3}, "test"), (False, {"n": 3}, None)])

    def test_pulsing_twice_quickly_counts_twice(self):
        bus.save_links([{"from": "numbers.toggle_dcnow", "to": "switcher.toggle_network"}])
        bus.pulse("numbers.toggle_dcnow", 30)
        bus.pulse("numbers.toggle_dcnow", 30)
        self.assertEqual(self.selected(), "dcnow")                               # flipped twice

    def test_a_pulse_runs_out_when_polled(self):
        bus.save_links([SELECT])
        bus.pulse("numbers.call_dcnow", 0.05)
        self.assertTrue(bus.output_level("numbers.call_dcnow"))
        time.sleep(0.1)
        self.assertFalse(bus.output_level("numbers.call_dcnow"))                 # (a timer in the process lowers it; poll() does it for others)
        bus.poll()
        self.assertFalse(bus.input_level("switcher.select_dcnet"))

    def test_poll_lowers_a_pulse_made_by_another_process(self):
        bus.save_links([SELECT])
        bus.set_output("numbers.call_dcnow", True, until=time.time() - 1)         # as if the process that pulsed it is gone
        self.assertTrue(bus.input_level("switcher.select_dcnet"))
        bus.poll()
        self.assertFalse(bus.input_level("switcher.select_dcnet"))

    def test_a_computed_output_follows_its_fact_and_its_cables_follow_it(self):
        bus.save_links([{"from": "switcher.dcnet_selected", "to": "led.alert_a"}])
        self.assertFalse(bus.input_level("led.alert_a"))
        open(core.FLAG, "w").close()
        bus.poll()                                                              # the fact changed behind the bus's back
        self.assertTrue(bus.output_level("switcher.dcnet_selected"))
        self.assertTrue(bus.input_level("led.alert_a"))
        os.remove(core.FLAG)
        bus.refresh("switcher.dcnet_selected")
        self.assertFalse(bus.input_level("led.alert_a"))

    def test_choosing_the_network_by_the_modules_own_input_moves_its_outputs(self):
        bus.save_links([{"from": "switcher.dcnet_selected", "to": "led.alert_b"}, {"from": "numbers.call_dcnet", "to": "switcher.select_dcnet"}])
        bus.pulse("numbers.call_dcnet", 30)
        self.assertTrue(bus.input_level("led.alert_b"))                          # a cable leads from the number through the switcher to the LED

    def test_new_cables_take_hold_of_what_is_on_now(self):
        open(core.FLAG, "w").close()
        bus.refresh("switcher.dcnet_selected")
        bus.save_links([{"from": "switcher.dcnet_selected", "to": "led.alert_c"}])
        self.assertTrue(bus.input_level("led.alert_c"))
        bus.save_links([])                                                       # the cable is gone, its hold is released
        self.assertFalse(bus.input_level("led.alert_c"))

    def test_an_always_on_output_holds_its_input_on(self):
        bus.save_links([{"from": "app.on", "to": "led.alert_a"}])
        self.assertTrue(bus.input_level("led.alert_a"))

    def test_the_number_output_of_a_removed_module_is_simply_off(self):
        bus.save_links([SELECT])
        shutil.rmtree(os.path.join(self.modules, "numbers"))                       # no numbers module: nothing can pulse its outputs
        self.assertFalse(bus.input_level("switcher.select_dcnet"))
        self.assertEqual(bus.set_input("switcher.select_dcnet", True, "test"), ["switcher.select_dcnet"])      # the switcher works on its own
        self.assertEqual(self.selected(), "dcnet")

    def test_the_switcher_not_there_the_numbers_still_work_on_their_own(self):
        shutil.rmtree(os.path.join(self.modules, "switcher"))
        bus.save_links([SELECT])
        self.assertEqual(bus.links(), [])                                        # the cable to a module that is not installed is dropped
        self.assertEqual(bus.pulse("numbers.call_dcnow", 30), [])
        self.assertEqual(self.selected(), "dcnow")

    def test_a_handler_that_fails_does_not_stop_the_others(self):
        self.add_module("boom", "def fail(on, k, c):\n    raise RuntimeError('no')\nINPUTS = {'fail': fail}", inputs=[{"id": "fail", "label": "Fail"}])
        bus.save_links([{"from": "numbers.call_dcnow", "to": "boom.fail"}, SELECT])
        bus.pulse("numbers.call_dcnow", 30)
        self.assertEqual(self.selected(), "dcnet")

    def test_a_module_whose_io_file_does_not_load_is_skipped(self):
        self.add_module("bad", "this is not python", inputs=[{"id": "x", "label": "X"}])
        self.assertEqual(bus.set_input("bad.x", True, "test"), ["bad.x"])          # no handler, no crash; the level is still on
        self.assertTrue(bus.input_level("bad.x"))

    def test_an_output_that_is_wired_to_itself_stops(self):
        self.add_module("loop", "import netswitch_bus as bus\ncalls = []\n"
                                "def again(on, k, c):\n    calls.append(on)\n    bus.set_output('loop.out', False if on else True)\n"
                                "INPUTS = {'again': again}",
                        inputs=[{"id": "again", "label": "Again"}], outputs=[{"id": "out", "label": "Out"}])
        bus.save_links([{"from": "loop.out", "to": "loop.again"}])
        bus.set_output("loop.out", True)
        self.assertLessEqual(len(bus._io_module("loop").calls), bus.MAX_DEPTH + 1)         # it ends

    def test_levels_for_the_page(self):
        bus.save_links([SELECT])
        bus.pulse("numbers.call_dcnow", 30)
        lv = bus.levels()
        self.assertTrue(lv["outputs"]["numbers.call_dcnow"])
        self.assertTrue(lv["inputs"]["switcher.select_dcnet"])
        self.assertFalse(lv["inputs"]["switcher.select_dcnow"])


class AppBrickTests(BusBase):
    def test_a_notice_shows_with_its_text_and_expires_and_can_be_dismissed(self):
        bus.save_links([], {"app.notice_a": {"text": "Soon gone", "seconds": 1}, "app.notice_b": {"text": "Stays", "seconds": 60}})
        bus.set_input("app.notice_a", True, "t")
        bus.set_input("app.notice_b", True, "t")
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

    def test_a_box_stands_out_while_its_input_is_on(self):
        boxes = [o[0] for i in bus.declarations()["inputs"] if i["id"] == "app.highlight_a" for o in i["params"][0]["options"]]
        self.assertIn("network", boxes)
        self.assertIn("clock", boxes)
        bus.save_links([{"from": "numbers.call_dcnow", "to": "app.highlight_a"}], {"app.highlight_a": {"box": "clock", "why": "Look here"}})
        self.assertEqual(bus.active_highlights(), {})
        bus.set_output("numbers.call_dcnow", True)
        self.assertEqual(bus.active_highlights(), {"clock": "Look here"})
        bus.set_output("numbers.call_dcnow", False)
        self.assertEqual(bus.active_highlights(), {})

    def test_the_colour_input_changes_a_modules_colour_when_it_turns_on(self):
        bus.save_links([], {"app.colour_a": {"target": "switcher.dcnow", "colour": "green"}})
        bus.set_input("app.colour_a", True, "t")
        self.assertEqual(core.module_colours("switcher")["dcnow"], "green")

    def test_a_timer_is_an_output_that_runs_for_a_while(self):
        bus.save_links([{"from": "numbers.call_dcnow", "to": "app.timer1_start"}, {"from": "app.timer1_running", "to": "led.alert_a"}],
                       {"app.timer1_start": {"seconds": 5}})
        bus.pulse("numbers.call_dcnow", 0.05)
        time.sleep(0.1)
        bus.poll()
        self.assertTrue(bus.output_level("app.timer1_running"))
        self.assertTrue(bus.input_level("led.alert_a"))                          # a number lights the LED alert for 5 seconds, by two cables
        with open(os.path.join(core.SIGNALS, "out.app.timer1_running"), "w") as f:
            f.write("%f" % (time.time() - 1))
        bus.poll()
        self.assertFalse(bus.input_level("led.alert_a"))

    def test_an_led_alert_lights_its_message_while_the_input_is_on(self):
        import sys
        sys.path.insert(0, os.path.join(REAL_MODULES, "led"))
        import netswitch_ledconfig as ledconfig
        ledconfig.save_led_config({"groups": [{"id": "g1", "colour": "red", "effect": "blink", "speed": "fast", "messages": ["alert-b"]}]})
        ctx = lambda: ledconfig.gather()
        self.assertEqual(ledconfig.active_messages(ctx()), [])
        bus.save_links([{"from": "numbers.call_dcnow", "to": "led.alert_b"}])
        bus.set_output("numbers.call_dcnow", True)
        looks = ledconfig.active_messages(ctx())
        self.assertEqual([(m["key"], m["messages"], m["effect"]) for m in looks], [("g1", ["alert-b"], "blink")])
        bus.set_output("numbers.call_dcnow", False)
        self.assertEqual(ledconfig.active_messages(ctx()), [])

    def test_started_is_a_pulse_the_cables_can_use(self):
        bus.save_links([{"from": "app.started", "to": "app.notice_a"}], {"app.notice_a": {"text": "Hello again", "seconds": 30}})
        bus.pulse("app.started", 3)
        self.assertEqual([n["text"] for n in bus.active_notices()], ["Hello again"])


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
        self.assertIn("switcher.select_dcnet", [i["id"] for i in r["inputs"]])
        self.assertEqual(r["links"], r["defaults"])
        self.assertEqual(sorted(r["levels"]), ["inputs", "outputs"])
        self.assertIn("app.notice_a", r["knobs"])

    def test_links_are_saved_cleaned_and_reset(self):
        r = self.post("/bus/links", {"links": [SELECT, {"from": "x.y", "to": "z.w"}], "knobs": {"app.notice_a": {"text": "Hi", "seconds": 5}}})
        self.assertEqual(r["links"], [SELECT])
        self.assertEqual(self.get("/bus")["links"], [SELECT])
        self.assertEqual(self.get("/bus")["knobs"]["app.notice_a"], {"text": "Hi", "seconds": 5.0})
        self.assertEqual(self.post("/bus/reset")["links"], self.get("/bus")["defaults"])

    def test_only_the_page_itself_may_change_them(self):
        with self.assertRaises(HTTPError) as e:
            self.post("/bus/links", {"links": []}, header=False)
        self.assertEqual(e.exception.code, 403)

    def test_a_notice_reaches_the_page_and_can_be_dismissed(self):
        bus.save_links([], {"app.notice_a": {"text": "From a link", "seconds": 30}})
        bus.set_input("app.notice_a", True, "test")
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
