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


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox(hook)

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
        saved = nums.save_numbers({"reset": ["*61#", "555-0009"], "toggle_dcnow": ["*61#", "5550001#"],
                                   "call_dcnet": [], "call_dcnow": "nonsense"})
        self.assertEqual(saved["reset"], ["*61#", "5550009"])
        self.assertEqual(saved["toggle_dcnow"], ["5550001#"])          # *61# already used by reset
        self.assertEqual(saved["call_dcnet"], [])                      # empty = action off
        self.assertEqual(saved["call_dcnow"], ["5550001"])             # not a list: default
        self.assertEqual(saved["toggle_dcnet"], ["5550002#"])          # absent: default
        self.assertEqual(nums.numbers(), saved)
        self.assertEqual(hook._load_numbers()["reset"], ["*61#", "5550009"])

    def test_limit_per_action(self):
        saved = nums.save_numbers({"reset": ["%07d" % i for i in range(30)]})
        self.assertEqual(len(saved["reset"]), nums.MAX_PER_ACTION)

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
        self.assertEqual(self.c("5550001"), "call_dcnow")
        self.assertEqual(self.c("5550002"), "call_dcnet")
        self.assertEqual(self.c("5550001#"), "toggle_dcnow")
        self.assertEqual(self.c("5550002#"), "toggle_dcnet")
        self.assertEqual(self.c("1111111#"), "reset")
        self.assertEqual(self.c("1111111"), "openmenu")
        self.assertIsNone(self.c("5551234"))
        self.assertIsNone(self.c(""))

    def test_extra_leading_digits_and_prefixes(self):
        self.assertEqual(self.c("15550002"), "call_dcnet")          # DreamPi hears an extra leading 1
        self.assertEqual(self.c("11111111"), "openmenu")
        self.assertEqual(self.c("0412345550001#"), "toggle_dcnow")  # ISP prefix

    def test_short_ending_and_star_numbers(self):
        n = dict(self.D, call_dcnet=["0002"], toggle_dcnow=["*61#"])
        self.assertEqual(self.c("5550002", n), "call_dcnet")
        self.assertEqual(self.c("1111*61#", n), "toggle_dcnow")
        self.assertEqual(self.c("*61#", n), "toggle_dcnow")

    def test_longest_match_wins_and_openmenu_wins_ties(self):
        n = dict(self.D, call_dcnet=["0001"], call_dcnow=["5550001"])
        self.assertEqual(self.c("5550001", n), "call_dcnow")        # 7 characters beat 4
        n = dict(self.D, call_dcnet=["1111111"])
        self.assertEqual(self.c("1111111", n), "openmenu")          # equal length: the fixed openMenu rule
        n = dict(self.D, call_dcnet=["111"])
        self.assertEqual(self.c("1111111", n), "openmenu")          # a short ending can't hijack openMenu

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
        r = self.dial("5550002")
        self.assertEqual((r["client"], self.selected()), ("dcnet", "dcnet"))

    def test_call_dcnow_selects_and_stays_ppp(self):
        open(hook.FLAG, "w").close()
        r = self.dial("5550001")
        self.assertEqual((r["client"], self.selected()), ("PPP", "dcnow"))

    def test_toggle_numbers_select_and_hang_up_without_calling_netlink(self):
        r = self.dial("5550002#")
        self.assertEqual((r["client"], self.selected(), self.nl.mode), ("idle", "dcnet", "idle"))
        r = self.dial("5550001#")
        self.assertEqual((r["client"], self.selected()), ("idle", "dcnow"))
        self.assertEqual(self.fake.calls, [])                   # DreamPi's own check_number never ran

    def test_reset_goes_to_the_default_network_and_hangs_up(self):
        open(hook.FLAG, "w").close()
        self.assertEqual(self.dial("1111111#")["client"], "idle")
        self.assertEqual(self.selected(), "dcnow")
        open(hook.DEFAULT_DCNET, "w").close()
        self.dial("1111111#")
        self.assertEqual(self.selected(), "dcnet")

    def test_openmenu_always_dcnow_and_resets_only_with_autoreset(self):
        open(hook.FLAG, "w").close()
        r = self.dial("1111111")
        self.assertEqual((r["client"], self.selected()), ("PPP", "dcnet"))   # selection untouched, call on DCNow!
        open(hook.AUTORESET, "w").close()
        self.dial("1111111")
        self.assertEqual(self.selected(), "dcnow")

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
            self.assertEqual(r["numbers"], nums.default_numbers())
            self.assertEqual([a["key"] for a in r["actions"]], list(hook.NUMBER_ACTIONS))
            body = json.dumps({"call_dcnet": ["5550002", "*61#"]}).encode()
            req = Request(base + "/numbers", data=body, method="POST", headers={"Content-Type": "application/json"})
            out = json.loads(urlopen(req, timeout=10).read().decode())
            self.assertEqual(out["numbers"]["call_dcnet"], ["5550002", "*61#"])
            self.assertEqual(nums.numbers()["call_dcnet"], ["5550002", "*61#"])
        finally:
            srv.shutdown()
            srv.server_close()
            cleanup(tmp)


if __name__ == "__main__":
    unittest.main()
