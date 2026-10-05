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
        hook._parts.clear()

    def tearDown(self):
        hook._parts.clear()
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


class ReadyState(unittest.TestCase):
    """The state "ready" (the page's "Ready for calls", the LED's green): DreamPi writes it when it starts the dial tone, or, with
    --disable-dial-tone (it never does), when the modem is opened. It used to stay on "Starting up" for ever in that case."""
    def setUp(self):
        import sys
        self.tmp = sandbox(hook)
        self.sys = sys
        self.main = sys.modules["__main__"]
        self.had = getattr(self.main, "Modem", None)
        self.argv = list(sys.argv)
        self.watch = hook._watch_serial
        hook._watch_serial = lambda modem: None

        class Modem(object):
            def connect(self):
                pass

            def start_dial_tone(self):
                pass
        self.main.Modem = Modem

        class Netlink(object):
            def reset_serial(self):
                pass
        self.netlink = Netlink

    def tearDown(self):
        hook._watch_serial = self.watch
        self.sys.argv[:] = self.argv
        if self.had is None:
            del self.main.Modem
        else:
            self.main.Modem = self.had
        cleanup(self.tmp)

    def state(self):
        with open(hook.STATE) as f:
            return f.read().rsplit(" ", 1)[0]

    def start(self, argv):
        self.sys.argv[:] = argv
        hook._patch_ready_signals(self.netlink)
        hook._write_state("starting")

    def test_the_dial_tone_makes_it_ready(self):
        self.start(["dreampi.py"])
        modem = self.main.Modem()
        modem.connect()
        self.assertEqual(self.state(), "starting")                # the modem is open, the dial tone is not on yet
        modem.start_dial_tone()
        self.assertEqual(self.state(), "ready")

    def test_without_a_dial_tone_opening_the_modem_makes_it_ready(self):
        self.start(["dreampi.py", "--disable-dial-tone"])
        self.main.Modem().connect()
        self.assertEqual(self.state(), "ready")

    def test_without_a_dial_tone_it_is_ready_again_after_a_call(self):
        self.start(["dreampi.py", "--disable-dial-tone"])
        hook._write_state("call dcnow")
        self.main.Modem().connect()                                # DreamPi opens the modem again when the call is over
        self.assertEqual(self.state(), "ready")
