"""Phone numbers: the rows (netswitch_numbers), the matching, the actions modules announce and the check_number() wrapper in the
DreamPi hook (against a fake Netlink class)."""
import json
import os
import shutil
import types
import unittest
import builtins

from support import ROOT, core, sandbox, cleanup
import netswitch_numbers as nums
import netswitch_numbers_hook as nh
import netswitch_dreampi as hook

builtins.__import__ = hook._original_import     # importing the hook may arm its import hook; undo that here


def install_modules(*names):
    """The hook only reads numbers.json while the phone numbers module is installed, and does an action through its module's hook file."""
    hook._parts.clear()
    for name in names:
        shutil.copytree(os.path.join(ROOT, "modules", name), os.path.join(hook.MODULES_DIR, name), ignore=shutil.ignore_patterns("__pycache__"))


def load_rows():
    """The rows the DreamPi integration works with: the numbers module's saved ones while it is on, else its own default row."""
    part = hook._module_part("numbers")
    return part.load_rows(hook.BASE_DIR) if part is not None else [dict(hook.DEFAULT_ROW)]


def row(action, items, hangup=False, rid=""):
    return {"id": rid, "action": action, "items": items, "opts": {"hangup": hangup}}


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox(hook)
        install_modules("numbers", "switcher")

    def tearDown(self):
        hook._parts.clear()
        cleanup(self.tmp)

    def test_the_default_is_one_dcnow_row_with_11111(self):
        self.assertEqual(nums.default_rows(), [{"id": "1", "action": "switcher.dcnow", "items": ["11111"], "opts": {"hangup": False}}])
        self.assertEqual(nums.numbers(), nums.default_rows())              # nothing saved yet
        self.assertEqual([r["items"] for r in load_rows()], [["11111"]])

    def test_clean_number(self):
        self.assertEqual(nums.clean_number("555-0001"), "5550001")
        self.assertEqual(nums.clean_number(" *61# "), "*61#")
        self.assertIsNone(nums.clean_number("12"))           # too short
        self.assertIsNone(nums.clean_number("1" * 25))       # too long
        self.assertIsNone(nums.clean_number("abc"))
        self.assertIsNone(nums.clean_number(None))
        self.assertEqual(nums.clean_number("1" * 12), "1" * 12)
        self.assertIsNone(nums.clean_number("1" * 13))       # the page says 3 - 12 characters

    def test_round_trip_ids_and_limits(self):
        saved = nums.save_numbers({"rows": [row("switcher.toggle", ["*61#", "555-0009", "*61#"], True, "7"),
                                            row("switcher.dcnet", ["%07d" % i for i in range(30)]),
                                            row("switcher.dcnow", ["*61#"], rid="7"),         # the id 7 is taken: a new one
                                            {"action": "not an action", "items": ["12345"]}]})
        self.assertEqual([r["action"] for r in saved], ["switcher.toggle", "switcher.dcnet", "switcher.dcnow"])
        self.assertEqual(saved[0]["items"], ["*61#", "5550009"])               # cleaned, no repeats in a row
        self.assertEqual(len(saved[1]["items"]), nums.MAX_PER_ROW)
        self.assertEqual(saved[2]["items"], ["*61#"])                           # the same number may be in several rows
        self.assertEqual(len(set(r["id"] for r in saved)), 3)
        self.assertEqual(saved[0]["opts"], {"hangup": True})
        self.assertEqual(nums.numbers(), saved)
        self.assertEqual(load_rows()[0]["items"], ["*61#", "5550009"])

    def test_no_rows_means_no_numbers_do_anything(self):
        self.assertEqual(nums.save_numbers({"rows": []}), [])
        self.assertEqual(load_rows(), [])

    def test_at_most_max_rows(self):
        self.assertEqual(len(nums.save_numbers({"rows": [row("switcher.dcnow", ["12345"]) for _ in range(50)]})), nums.MAX_ROWS)

    def test_the_four_lists_of_an_older_file_become_rows(self):
        with open(nums.NUMBERS, "w") as f:
            json.dump({"toggle_dcnow": ["5550001#"], "toggle_dcnet": [], "call_dcnet": ["5550002"], "call_dcnow": ["11111", "1111111"]}, f)
        rows = nums.numbers()
        self.assertEqual([(r["action"], r["opts"]["hangup"], r["items"]) for r in rows],
                         [("switcher.dcnow", True, ["5550001#"]), ("switcher.dcnet", True, []),
                          ("switcher.dcnow", False, ["11111", "1111111"]), ("switcher.dcnet", False, ["5550002"])])
        self.assertEqual([r["items"] for r in load_rows()], [r["items"] for r in rows])

    def test_without_the_module_the_hook_uses_the_default_row(self):
        nums.save_numbers({"rows": [row("switcher.dcnet", ["*61#"])]})
        self.assertEqual(load_rows()[0]["items"], ["*61#"])
        with open(hook.MODULES_STATE, "w") as f:                       # switched off in the Modules menu
            json.dump({"numbers": False}, f)
        self.assertEqual([r["items"] for r in load_rows()], [["11111"]])
        os.remove(hook.MODULES_STATE)
        self.assertEqual(load_rows()[0]["items"], ["*61#"])
        os.remove(os.path.join(hook.MODULES_DIR, "numbers", "module.json"))   # folder deleted
        self.assertEqual([r["items"] for r in load_rows()], [["11111"]])

    def test_broken_file_falls_back(self):
        with open(nums.NUMBERS, "w") as f:
            f.write("{not json")
        self.assertEqual(nums.numbers(), nums.default_rows())
        self.assertEqual([r["items"] for r in load_rows()], [["11111"]])

    def test_modules_announce_actions(self):
        """The switcher announces toggle / DCNow! / DCNET; a module that is off announces nothing."""
        got = [a["value"] for a in core.module_actions()]
        self.assertEqual([a for a in got if a.startswith("switcher.")], ["switcher.toggle", "switcher.dcnow", "switcher.dcnet"])
        self.assertTrue(all(a["label"] and a["group"] for a in core.module_actions()))

    def test_the_reply_has_ready_texts_and_warns_when_openmenu_is_not_caught(self):
        r = nums._reply()
        self.assertEqual((r["rows"][0]["title"], r["rows"][0]["off"], r["note"]), ("DCNow!", False, ""))
        self.assertIn("openMenu", r["rules"]["help"])
        nums.save_numbers({"rows": [row("switcher.dcnow", ["5550001"]), row("switcher.dcnow", ["11111"], True)]})    # the 11111 row hangs up
        self.assertIn("1111111", nums._reply()["note"])
        nums.save_numbers({"rows": [row("switcher.dcnow", ["1111111"])]})
        self.assertEqual(nums._reply()["note"], "")
        nums.save_numbers({"rows": [row("gone.thing", ["12345"])]})
        r = nums._reply()["rows"][0]
        self.assertEqual((r["off"], r["title"]), (True, "gone.thing"))                    # a row of a module that is not there stays


class WithoutTheNumbersModule(unittest.TestCase):
    """The DreamPi integration has its own one row (DCNow! on 11111) while the numbers module is not there."""
    def setUp(self):
        self.tmp = sandbox(hook)
        install_modules("switcher")

    def tearDown(self):
        hook._parts.clear()
        cleanup(self.tmp)

    def test_default_row_matches_what_openmenu_dials(self):
        self.assertEqual([(r["action"], n) for r, n in hook._matches("1111111")], [("switcher.dcnow", "11111")])
        self.assertEqual(hook._matches("5550001"), [])
        self.assertEqual(hook._matches(""), [])


class MatchTests(unittest.TestCase):
    def m(self, dialed, rows):
        return [(r["action"], n) for r, n in nh.matching(dialed, rows)]

    def test_defaults_catch_openmenu(self):
        rows = nh.rows_from_data(None)
        self.assertEqual(self.m("11111", rows), [("switcher.dcnow", "11111")])
        self.assertEqual(self.m("1111111", rows), [("switcher.dcnow", "11111")])       # openMenu's own number ends with 11111
        self.assertEqual(self.m("5550001", rows), [])
        self.assertEqual(self.m("", rows), [])

    def test_extra_leading_digits_and_prefixes(self):
        rows = [row("switcher.dcnet", ["5550002"]), row("switcher.toggle", ["5550001#"], True)]
        self.assertEqual(self.m("15550002", rows), [("switcher.dcnet", "5550002")])        # DreamPi hears an extra leading 1
        self.assertEqual(self.m("0412345550001#", rows), [("switcher.toggle", "5550001#")])   # ISP prefix
        self.assertEqual(self.m("55500019", rows), [])                                      # not in the middle

    def test_short_ending_and_star_numbers(self):
        rows = [row("switcher.dcnet", ["0002"]), row("switcher.toggle", ["*61#"])]
        self.assertEqual(self.m("5550002", rows), [("switcher.dcnet", "0002")])
        self.assertEqual(self.m("1111*61#", rows), [("switcher.toggle", "*61#")])

    def test_longest_match_decides_and_every_row_with_it_runs(self):
        rows = [row("switcher.dcnet", ["0001"]), row("switcher.dcnow", ["5550001"]), row("switcher.toggle", ["5550001", "999"])]
        self.assertEqual(self.m("5550001", rows), [("switcher.dcnow", "5550001"), ("switcher.toggle", "5550001")])   # 7 characters beat 4; both rows run
        self.assertEqual(self.m("1234999", rows), [("switcher.toggle", "999")])


class FakeModule(object):
    def __init__(self, dcnet_enabled=True):
        calls = self.calls = []

        class Netlink(object):
            dcnet = dcnet_enabled
            mode = None

            def check_number(self, raw):
                calls.append(raw)
                if raw.startswith("*70"):
                    return {"client": "idle", "dial_string": raw}
                return {"client": "PPP", "dial_string": raw}
        self.module = types.ModuleType("netlink")
        self.module.Netlink = Netlink
        self.cls = Netlink


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox(hook)
        install_modules("numbers", "switcher")
        self.fake = FakeModule()
        hook._patch(self.fake.module)
        self.nl = self.fake.cls()
        self.nl.logger = types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)
        self._busy = hook._play_busy
        hook._play_busy = lambda modem: True

    def tearDown(self):
        hook._play_busy = self._busy
        hook._parts.clear()
        cleanup(self.tmp)

    def dial(self, number):
        return self.nl.check_number(number)

    def selected(self):
        return "dcnet" if os.path.exists(hook.FLAG) else "dcnow"

    def test_a_dcnet_row_selects_and_routes_to_dcnet(self):
        nums.save_numbers({"rows": [row("switcher.dcnet", ["5550002"])]})
        r = self.dial("5550002")
        self.assertEqual((r["client"], self.selected()), ("dcnet", "dcnet"))

    def test_the_default_row_selects_dcnow_for_11111_and_for_openmenus_1111111(self):
        for number in ("11111", "1111111"):
            open(hook.FLAG, "w").close()
            r = self.dial(number)
            self.assertEqual((r["client"], self.selected()), ("PPP", "dcnow"), number)       # still PPP: DCNow!

    def test_hang_up_rows_select_and_hang_up_without_calling_netlink(self):
        nums.save_numbers({"rows": [row("switcher.dcnow", ["5550001#"], True), row("switcher.dcnet", ["5550002#"], True)]})
        r = self.dial("5550002#")
        self.assertEqual((r["client"], self.selected(), self.nl.mode), ("idle", "dcnet", "idle"))
        r = self.dial("5550001#")
        self.assertEqual((r["client"], self.selected()), ("idle", "dcnow"))
        self.assertEqual(self.fake.calls, [])                   # DreamPi's own check_number never ran

    def test_toggle_flips_the_selection_each_time(self):
        nums.save_numbers({"rows": [row("switcher.toggle", ["5550003#"], True), row("switcher.toggle", ["5550004"])]})
        self.dial("5550003#")
        self.assertEqual(self.selected(), "dcnet")
        self.dial("5550003#")
        self.assertEqual(self.selected(), "dcnow")
        self.assertEqual(self.dial("5550004")["client"], "dcnet")        # toggled to DCNET and connected through DCNet
        self.assertEqual(self.dial("5550004")["client"], "PPP")           # toggled back to DCNow!: connects through DCNow!
        self.assertEqual(self.selected(), "dcnow")

    def test_a_number_in_several_rows_runs_all_of_them_in_order(self):
        nums.save_numbers({"rows": [row("switcher.dcnet", ["5550005"]), row("switcher.dcnow", ["5550005"])]})
        self.dial("5550005")
        self.assertEqual(self.selected(), "dcnow")                          # the last row wins
        nums.save_numbers({"rows": [row("switcher.dcnow", ["5550005"]), row("switcher.dcnet", ["5550005"], True)]})
        r = self.dial("5550005")
        self.assertEqual((r["client"], self.selected()), ("idle", "dcnet"))   # one row hangs up: the call ends

    def test_a_row_of_a_module_that_is_off_does_nothing(self):
        nums.save_numbers({"rows": [row("switcher.dcnet", ["5550002#"], True)]})
        with open(hook.MODULES_STATE, "w") as f:
            json.dump({"switcher": False}, f)
        r = self.dial("5550002#")
        self.assertEqual((r["client"], self.selected(), self.fake.calls), ("PPP", "dcnow", ["5550002#"]))     # not answered differently, nothing selected
        nums.save_numbers({"rows": [row("nosuch.thing", ["5550002"], True)]})
        self.assertEqual(self.dial("5550002")["client"], "PPP")

    def test_other_numbers_follow_the_selection(self):
        self.assertEqual(self.dial("5551234")["client"], "PPP")
        open(hook.FLAG, "w").close()
        self.assertEqual(self.dial("5551234")["client"], "dcnet")

    def test_dcnet_not_enabled_falls_back_to_dcnow(self):
        fake = FakeModule(dcnet_enabled=False)
        hook._patch(fake.module)
        nl = fake.cls()
        nl.logger = self.nl.logger
        nums.save_numbers({"rows": [row("switcher.dcnet", ["5550002"])]})
        self.assertEqual(nl.check_number("5550002")["client"], "PPP")

    def test_dreampis_own_codes_pass_through(self):
        self.assertEqual(self.dial("*70")["client"], "idle")
        self.assertEqual(self.fake.calls, ["*70"])


class HttpNumbersTests(unittest.TestCase):
    def test_api_round_trip(self):
        import threading
        from urllib.request import urlopen, Request
        from support import web
        tmp = sandbox()
        srv = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        try:
            r = json.loads(urlopen(base + "/numbers", timeout=10).read().decode())
            self.assertEqual(r["rows"][0]["items"], ["11111"])
            self.assertEqual(r["defaults"]["rows"][0]["action"], "switcher.dcnow")
            self.assertEqual([a["value"] for a in r["actions"] if a["group"] == "DreamPi Network Selector"], ["switcher.toggle", "switcher.dcnow", "switcher.dcnet"])
            self.assertEqual([o["key"] for o in r["options"]], ["hangup"])
            self.assertEqual((r["rules"]["min"], r["rules"]["max"], r["rules"]["allowed"]), (nums.MIN_LEN, nums.MAX_LEN, "0-9*#"))
            body = json.dumps({"rows": [row("switcher.dcnet", ["5550002", "*61#"], True)]}).encode()
            req = Request(base + "/numbers", data=body, method="POST", headers={"Content-Type": "application/json", "X-Requested-With": "netswitch"})
            out = json.loads(urlopen(req, timeout=10).read().decode())
            self.assertEqual([(x["title"], x["items"], x["opts"]) for x in out["rows"]], [("DCNET", ["5550002", "*61#"], {"hangup": True})])
            self.assertEqual(nums.numbers()[0]["items"], ["5550002", "*61#"])
        finally:
            srv.shutdown()
            srv.server_close()
            cleanup(tmp)


if __name__ == "__main__":
    unittest.main()
