"""The two modules the DreamPi hook uses: the debug log (its code is loaded from modules/debuglog while the module is
on) and the phone numbers (numbers.json is only read while the module is on). The hook runs inside DreamPi."""
import builtins
import json
import os
import shutil
import types
import unittest

from support import ROOT, sandbox, cleanup
import netswitch_hook as hook
import netswitch_hookdebug as hookdebug

builtins.__import__ = hook._original_import     # importing the hook may arm its import hook; undo that here


class DebugLogInTheHook(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox(hook, hookdebug)
        shutil.copytree(os.path.join(ROOT, "modules", "debuglog"), os.path.join(hook.MODULES_DIR, "debuglog"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        hook._debug_module[0] = None

    def tearDown(self):
        hook._debug_module[0] = None
        cleanup(self.tmp)

    def log(self):
        try:
            with open(hookdebug.DTMF_LOG) as f:
                return f.read()
        except IOError:
            return ""

    def test_nothing_is_logged_unless_recording(self):
        hook._dtmf_log("hello")
        self.assertEqual(self.log(), "")

    def test_a_line_is_logged_while_recording(self):
        open(hook.DEBUG_DTMF, "w").close()
        hook._dtmf_log("hello")
        hook._dtmf_log("again")
        text = self.log()
        self.assertIn("hello", text)
        self.assertIn("again", text)
        self.assertRegex(text.splitlines()[1], r"\+\d+ms\s+again")          # the gap since the previous line

    def test_without_the_module_nothing_is_logged(self):
        open(hook.DEBUG_DTMF, "w").close()
        os.remove(os.path.join(hook.MODULES_DIR, "debuglog", "module.json"))
        hook._dtmf_log("hello")
        self.assertEqual(self.log(), "")

    def test_switched_off_in_the_modules_menu_nothing_is_logged(self):
        open(hook.DEBUG_DTMF, "w").close()
        with open(hook.MODULES_STATE, "w") as f:
            json.dump({"debuglog": False}, f)
        hook._dtmf_log("hello")
        self.assertEqual(self.log(), "")
        with open(hook.MODULES_STATE, "w") as f:
            json.dump({"debuglog": True}, f)
        hook._dtmf_log("now on")
        self.assertIn("now on", self.log())

    def test_modem_bytes_become_readable_events(self):
        open(hook.DEBUG_DTMF, "w").close()
        reads = [b"\x105", b"\x10/", b"NO CARRIER\r\n"]
        serial = types.SimpleNamespace(read=lambda *a, **k: reads.pop(0) if reads else b"")
        modem = types.SimpleNamespace(_serial=serial, _sending_tone=True)
        hook._watch_serial(modem)
        for _ in range(3):
            modem._serial.read(1)
        text = self.log()
        self.assertIn("modem: DTMF 5", text)
        self.assertIn("DTMF tone starts", text)
        self.assertIn("modem says: NO CARRIER", text)


if __name__ == "__main__":
    unittest.main()
