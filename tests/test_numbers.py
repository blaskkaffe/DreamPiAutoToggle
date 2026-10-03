"""Phone numbers: the settings (netswitch_numbers), the matching and the
check_number() wrapper in the DreamPi hook (against a fake Netlink class)."""
import json
import os
import types
import unittest
import builtins

from support import core, sandbox, cleanup
import netswitch_numbers as nums
import netswitch_hook as hook

builtins.__import__ = hook._original_import     # importing the hook may arm its import hook; undo that here


def enable_numbers_module():
    """The hook only reads numbers.json while the phone numbers module is installed (and not switched off)."""
    folder = os.path.join(hook.MODULES_DIR, "numbers")
    os.makedirs(folder)
    with open(os.path.join(folder, "module.json"), "w") as f:
        f.write("{}")


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox(hook)
        enable_numbers_module()

    def tearDown(self):
        cleanup(self.tmp)

    def test_defaults_match_the_hook(self):
        self.assertEqual(nums.default_numbers(), hook.DEFAULT_NUMBERS)
        self.assertEqual(tuple(a[0] for a in nums.ACTIONS), hook.NUMBER_ACTIONS)

    def test_missing_file_gives_defaults(self):
        self.assertEqual(nums.numbers(), nums.default_numbers())

    def test_clean_number(self):
        self.assertEqual(nums.clean_number("555-0001"), "5550001")
        self.assertEqual(nums.clean_number(" *61# "), "*61#")
        self.assertIsNone(nums.clean_number("12"))           # too short
        self.assertIsNone(nums.clean_number("1" * 25))       # too long
        self.assertIsNone(nums.clean_number("abc"))
        self.assertIsNone(nums.clean_number(None))

    def test_round_trip_dedupe_and_off(self):
        saved = nums.save_numbers({"toggle_dcnow": ["*61#", "555-0009"], "toggle_dcnet": ["*61#", "5550002#"],
                                   "call_dcnet": [], "call_dcnow": "nonsense", "reset": ["1111111#"]})
        self.assertEqual(saved["toggle_dcnow"], ["*61#", "5550009"])
        self.assertEqual(saved["toggle_dcnet"], ["5550002#"])          # *61# already used by toggle_dcnow
        self.assertNotIn("reset", saved)                               # the old Reset list is gone
        self.assertEqual(saved["call_dcnet"], [])                      # empty = action off
        self.assertEqual(saved["call_dcnow"], ["11111", "111111", "1111111"])   # not a list: default
        self.assertEqual(nums.numbers(), saved)
        self.assertEqual(hook._load_numbers()["toggle_dcnow"], ["*61#", "5550009"])

    def test_length_limits(self):
        self.assertEqual(nums.clean_number("1" * 12), "1" * 12)
        self.assertIsNone(nums.clean_number("1" * 13))         # the page says 3 - 12 digits

    def test_limit_per_action(self):
        saved = nums.save_numbers({"call_dcnow": ["%07d" % i for i in range(30)]})
        self.assertEqual(len(saved["call_dcnow"]), nums.MAX_PER_ACTION)

    def test_without_the_module_the_hook_uses_the_defaults(self):
        nums.save_numbers({"call_dcnow": ["*61#"]})
        self.assertEqual(hook._load_numbers()["call_dcnow"], ["*61#"])
        with open(hook.MODULES_STATE, "w") as f:                       # switched off in the Modules menu
            json.dump({"numbers": False}, f)
        self.assertEqual(hook._load_numbers(), hook.DEFAULT_NUMBERS)
        os.remove(hook.MODULES_STATE)
        self.assertEqual(hook._load_numbers()["call_dcnow"], ["*61#"])
        os.remove(os.path.join(hook.MODULES_DIR, "numbers", "module.json"))   # folder deleted
        self.assertEqual(hook._load_numbers(), hook.DEFAULT_NUMBERS)

    def test_broken_file_falls_back(self):
        with open(core.NUMBERS, "w") as f:
            f.write("{not json")
        self.assertEqual(nums.numbers(), nums.default_numbers())
        self.assertEqual(hook._load_numbers(), hook.DEFAULT_NUMBERS)


class ClassifyTests(unittest.TestCase):
    D = hook.DEFAULT_NUMBERS

    def c(self, dialed, numbers=None):
        return hook._classify(dialed, numbers or self.D)[0]

    def test_defaults(self):
        self.assertEqual(self.D["call_dcnow"], ["11111", "111111", "1111111"])
        self.assertEqual(self.D["call_dcnet"], [])                  # no Call DCNET number by default
        for n in ("11111", "111111", "1111111"):
            self.assertEqual(self.c(n), "call_dcnow", n)
        self.assertIsNone(self.c("5550001"))
        self.assertEqual((self.D["toggle_dcnow"], self.D["toggle_dcnet"]), ([], []))      # no toggle numbers by default
        self.assertIsNone(self.c("5550001#"))
        self.assertIsNone(self.c("1111111#"))                       # the old Reset number is no longer special
        self.assertIsNone(self.c("5551234"))
        self.assertIsNone(self.c(""))

    def test_extra_leading_digits_and_prefixes(self):
        n = dict(self.D, call_dcnet=["5550002"])
        self.assertEqual(self.c("15550002", n), "call_dcnet")       # DreamPi hears an extra leading 1
        self.assertEqual(self.c("11111111"), "call_dcnow")          # a longer run still ends with 1111111
        n = dict(self.D, toggle_dcnow=["5550001#"])
        self.assertEqual(self.c("0412345550001#", n), "toggle_dcnow")   # ISP prefix

    def test_short_ending_and_star_numbers(self):
        n = dict(self.D, call_dcnet=["0002"], toggle_dcnow=["*61#"])
        self.assertEqual(self.c("5550002", n), "call_dcnet")
        self.assertEqual(self.c("1111*61#", n), "toggle_dcnow")
        self.assertEqual(self.c("*61#", n), "toggle_dcnow")

    def test_longest_match_wins_and_openmenu_wins_ties(self):
        n = dict(self.D, call_dcnet=["0001"], call_dcnow=["5550001"])
        self.assertEqual(self.c("5550001", n), "call_dcnow")        # 7 characters beat 4
        n = dict(self.D, call_dcnet=["1111111"])
        self.assertEqual(self.c("1111111", n), "call_dcnow")        # equal length: Call DCNow! (it also selects DCNow!) ...
        n = dict(self.D, call_dcnow=[], call_dcnet=["1111111"])
        self.assertEqual(self.c("1111111", n), "openmenu")          # ... otherwise the fixed openMenu rule wins
        n = dict(self.D, call_dcnow=[], call_dcnet=["111"])
        self.assertEqual(self.c("1111111", n), "openmenu")          # a short ending can't hijack openMenu
        n = dict(self.D, call_dcnow=[])
        self.assertEqual(self.c("1111111", n), "openmenu")          # with its numbers removed, openMenu's still works

    def test_does_not_match_in_the_middle(self):
        self.assertIsNone(self.c("55500019"))


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
        enable_numbers_module()
        self.fake = FakeModule()
        hook._patch(self.fake.module)
        self.nl = self.fake.cls()
        self.nl.logger = types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)
        self._busy = hook._play_busy
        hook._play_busy = lambda modem: True

    def tearDown(self):
        hook._play_busy = self._busy
        cleanup(self.tmp)

    def dial(self, number):
        return self.nl.check_number(number)

    def selected(self):
        return "dcnet" if os.path.exists(hook.FLAG) else "dcnow"

    def test_call_dcnet_selects_and_routes_to_dcnet(self):
        nums.save_numbers({"call_dcnet": ["5550002"]})
        r = self.dial("5550002")
        self.assertEqual((r["client"], self.selected()), ("dcnet", "dcnet"))

    def test_call_dcnow_selects_and_stays_ppp(self):
        open(hook.FLAG, "w").close()
        r = self.dial("111111")
        self.assertEqual((r["client"], self.selected()), ("PPP", "dcnow"))

    def test_toggle_numbers_select_and_hang_up_without_calling_netlink(self):
        nums.save_numbers({"toggle_dcnow": ["5550001#"], "toggle_dcnet": ["5550002#"]})
        r = self.dial("5550002#")
        self.assertEqual((r["client"], self.selected(), self.nl.mode), ("idle", "dcnet", "idle"))
        r = self.dial("5550001#")
        self.assertEqual((r["client"], self.selected()), ("idle", "dcnow"))
        self.assertEqual(self.fake.calls, [])                   # DreamPi's own check_number never ran

    def test_1111111_resets_to_dcnow_by_default(self):
        open(hook.FLAG, "w").close()
        r = self.dial("1111111")
        self.assertEqual((r["client"], self.selected()), ("PPP", "dcnow"))   # in the default Call DCNow! list

    def test_openmenu_always_dcnow_and_leaves_the_selection_without_the_number(self):
        nums.save_numbers({"call_dcnow": []})
        open(hook.FLAG, "w").close()
        r = self.dial("1111111")
        self.assertEqual((r["client"], self.selected()), ("PPP", "dcnet"))   # selection untouched, call on DCNow!

    def test_other_numbers_follow_the_selection(self):
        self.assertEqual(self.dial("5551234")["client"], "PPP")
        open(hook.FLAG, "w").close()
        self.assertEqual(self.dial("5551234")["client"], "dcnet")

    def test_dcnet_not_enabled_falls_back_to_dcnow(self):
        fake = FakeModule(dcnet_enabled=False)
        hook._patch(fake.module)
        nl = fake.cls()
        nl.logger = self.nl.logger
        self.assertEqual(nl.check_number("5550002")["client"], "PPP")

    def test_custom_numbers_from_the_page(self):
        nums.save_numbers({"toggle_dcnet": ["*61#"], "call_dcnet": ["0002"]})
        self.assertEqual(self.dial("1111*61#")["client"], "idle")
        self.assertEqual(self.selected(), "dcnet")
        os.remove(hook.FLAG)
        self.assertEqual(self.dial("9990002")["client"], "dcnet")

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
            self.assertEqual(dict((g["key"], g["items"]) for g in r["groups"]), nums.default_numbers())
            self.assertEqual([g["key"] for g in r["groups"]], list(hook.NUMBER_ACTIONS))
            self.assertEqual(r["defaults"], nums.default_numbers())
            self.assertEqual((r["rules"]["min"], r["rules"]["max"], r["rules"]["allowed"], r["rules"]["unique"]), (nums.MIN_LEN, nums.MAX_LEN, "0-9*#", True))
            body = json.dumps({"call_dcnet": ["5550002", "*61#"]}).encode()
            req = Request(base + "/numbers", data=body, method="POST", headers={"Content-Type": "application/json", "X-Requested-With": "netswitch"})
            out = json.loads(urlopen(req, timeout=10).read().decode())
            self.assertEqual([g["items"] for g in out["groups"] if g["key"] == "call_dcnet"], [["5550002", "*61#"]])
            self.assertEqual(nums.numbers()["call_dcnet"], ["5550002", "*61#"])
        finally:
            srv.shutdown()
            srv.server_close()
            cleanup(tmp)


if __name__ == "__main__":
    unittest.main()
