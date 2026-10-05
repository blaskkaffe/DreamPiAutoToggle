# -*- coding: utf-8 -*-
"""
DreamPi Netswitch add-on - routing hook.

Loaded automatically by Python (through a .pth file) but does nothing unless
the running program imports DreamPi's netlink.py from /home/pi/dreampi.
It then wraps Netlink.check_number() with these rules:

  numbers  Rows of numbers set on the web page (numbers.json). A row = an action that a module announces (module.json "actions",
           done by that module's "hook" file: the network switcher has toggle / DCNow! / DCNET) + the numbers that trigger it
           + "hang up" (do not answer, busy tone). A dialed string only has to END with a number; the longest match decides and
           every row holding that number runs. Default: one row, DCNow!, 11111 (openMenu dials 1111111, which ends with it).
  others   Go to whichever network is selected (website or the numbers above).
           Only calls DreamPi would send to its normal PPP are redirected;
           Netlink/XBAND codes and the built-in *69 prefix are untouched.

The selection is the file dcnet_mode (DCNow! is selected again after every reboot).
It also reports DreamPi's state (starting / ready / in a call) to
/tmp/dreampi-netswitch.state for the web page. Modules (modules/ in
the add-on folder) hook in here through the "hook" file in their module.json: "switcher" does the network actions, "numbers" - without it
numbers.json is ignored and the default row above is used - and "debuglog" - it provides the code
that, while the file debug_dtmf exists, logs every modem event while DreamPi
listens for digits to /tmp/dreampi-netswitch-dtmf.log, to diagnose misheard
numbers (modules/debuglog/netswitch_hookdebug.py; without the module nothing is logged).
No DreamPi file is modified. Written for both Python 2.7 and 3.
"""
import json
import logging
import math
import os
import re
import sys
import threading
import time

BASE_DIR = "/opt/dreampi-netswitch"
FLAG = os.path.join(BASE_DIR, "dcnet_mode")
STATUS = "/tmp/dreampi-netswitch.active"
STATE = "/tmp/dreampi-netswitch.state"
DEBUG_DTMF = os.path.join(BASE_DIR, "debug_dtmf")  # exists = log modem events (see modules/debuglog)
MODULES_DIR = os.path.join(BASE_DIR, "modules")
MODULES_STATE = os.path.join(BASE_DIR, "modules.json")   # {"numbers": true, ...} from the Modules menu
MODEM = "/tmp/dreampi-netswitch.modem"
MODEM_PORT = "/tmp/dreampi-netswitch.port"   # the serial device DreamPi opened, e.g. /dev/ttyUSB0
NETLINK_DIR = "/home/pi/dreampi"

NUMBERS = os.path.join(BASE_DIR, "numbers.json")   # the four lists below, edited on the web page (phone numbers module)

# The rows of numbers.json: {"rows": [{"action": "switcher.dcnow", "items": ["11111"], "opts": {"hangup": false}}]}. A row says which
# action (a module's, announced in its module.json "actions" and done by its "hook" file) the numbers trigger; opts.hangup = do not
# answer the call (busy tone) after the action. These are the rows used until the user has saved their own.
DEFAULT_ROWS = [{"action": "switcher.dcnow", "items": ["11111"], "opts": {}}]
# the four lists of an older numbers.json -> (action, hang up)
LEGACY_LISTS = (("toggle_dcnow", "switcher.dcnow", True), ("toggle_dcnet", "switcher.dcnet", True),
                ("call_dcnow", "switcher.dcnow", False), ("call_dcnet", "switcher.dcnet", False))

# __builtin__ first: on Python 2 the "future" package can provide a fake
# "builtins" module, and patching that would do nothing.
try:
    import __builtin__ as _builtins  # Python 2
except ImportError:
    import builtins as _builtins  # Python 3

_original_import = _builtins.__import__
_done = [False]


def _log(obj, text):
    try:
        obj.logger.info("netswitch: " + text)
    except Exception:
        pass


def _write_file(path, text):
    """Replace a small state file in one step (write a temporary file, rename it over): the web page and the LED
    service read these files many times a second and must never see one half-written or empty."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            f.write(text)
        os.rename(tmp, path)
    except Exception:
        pass


def _write_status(text):
    _write_file(STATUS, text + "\n")


def _write_state(state):
    """DreamPi's current state for the web page: starting, ready,
    call <network> or unknown, with a unix timestamp."""
    _write_file(STATE, "%s %d\n" % (state, int(time.time())))


def _module_active(name):
    """The module is installed (its folder with a module.json) and not switched off in the Modules menu.
    A module without an entry in modules.json counts as on (numbers and debuglog are on by default)."""
    if not os.path.exists(os.path.join(MODULES_DIR, name, "module.json")):
        return False
    try:
        with open(MODULES_STATE) as f:
            return json.load(f).get(name) is not False
    except Exception:
        return True


_parts = {}


def _module_part(name):
    """The module's "hook" file (module.json "hook": the file name without .py) once it has been imported, else None (module absent,
    off or without one). It runs inside DreamPi, so it is Python 2.7 and 3 compatible like this file."""
    if not _module_active(name):
        return None
    if name not in _parts:
        folder = os.path.join(MODULES_DIR, name)
        part = False
        try:
            with open(os.path.join(folder, "module.json")) as f:
                wanted = json.load(f).get("hook")
            if wanted:
                sys.path.insert(0, folder)
                try:
                    part = __import__(str(wanted))
                finally:
                    try:
                        sys.path.remove(folder)
                    except ValueError:
                        pass
        except Exception:
            part = False
        _parts[name] = part
    return _parts[name] or None


def _debug_part():
    """The debug log module's hook file (netswitch_hookdebug), or None."""
    return _module_part("debuglog")


def _dtmf_log(text):
    """Add a line to the debug log. The debug log module does the writing (and only while recording is on),
    so without the module nothing is logged."""
    if not os.path.exists(DEBUG_DTMF):
        return
    part = _debug_part()
    if part is not None:
        part.log(text)


def _watch_serial(modem):
    """Log what the modem reports while DreamPi listens for digits (debug log module)."""
    part = _debug_part()
    if part is not None:
        part.watch(modem)


# ------------------------------------------------ "switch only" numbers (#)
# A special number followed by # (e.g. 5550002#) only switches the network:
# DreamPi doesn't answer (like its own *69 / *70 codes), and the dial tone is
# replaced by a busy tone for a few seconds so the Dreamcast gives up at once
# instead of waiting for an answer.
BUSY_SECONDS = 4.0
_busy_tone = [None]
_busy_until = [0.0]


def _make_busy_tone():
    """North American busy tone (480 + 620 Hz, 0.5 s on / 0.5 s off) as
    8-bit unsigned 8 kHz PCM, the format DreamPi streams its dial tone in."""
    if _busy_tone[0] is None:
        rate, out = 8000, bytearray()
        for i in range(rate):          # one second: 0.5 s tone, 0.5 s silence
            t = float(i) / rate
            v = 0.0 if i >= rate // 2 else \
                0.5 * (math.sin(2 * math.pi * 480 * t) + math.sin(2 * math.pi * 620 * t))
            out.append(max(0, min(255, int(round(128 + 90 * v)))))
        _busy_tone[0] = bytes(out)
    return _busy_tone[0]


def _play_busy(modem):
    """Swap DreamPi's dial tone buffer for a busy tone, then swap it back.
    modem.update() keeps streaming whatever buffer is set, so nothing else
    in DreamPi changes."""
    try:
        busy = _make_busy_tone()
        current = getattr(modem, "_dial_tone_wav", None)
        if not current or not getattr(modem, "_sending_tone", False):
            return False
        if current is not busy:            # keep the real dial tone, even when
            modem._netswitch_dial = current    # two switches come in quick succession
        dial = getattr(modem, "_netswitch_dial", None)
        if not dial:
            return False
        modem._dial_tone_wav = busy
        modem._dial_tone_counter = 0
        _busy_until[0] = time.time() + BUSY_SECONDS

        def restore():
            if time.time() >= _busy_until[0] - 0.05 and getattr(modem, "_dial_tone_wav", None) is busy:
                modem._dial_tone_wav = dial
                modem._dial_tone_counter = 0
        timer = threading.Timer(BUSY_SECONDS, restore)
        timer.daemon = True
        timer.start()
        return True
    except Exception:
        return False


def rows_from_data(data):
    """The rows of what numbers.json holds (the web page's numbers module uses this too). The older form with four lists becomes
    rows; a missing, broken or empty file gives the default rows."""
    rows = []
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        for r in data["rows"]:
            if isinstance(r, dict) and r.get("action"):
                opts = r.get("opts") if isinstance(r.get("opts"), dict) else {}
                items = r.get("items") if isinstance(r.get("items"), list) else []
                rows.append({"id": str(r.get("id") or ""), "action": str(r["action"]), "items": [str(n) for n in items if n], "opts": opts})
        return rows
    if isinstance(data, dict) and any(k[0] in data for k in LEGACY_LISTS):
        for key, action, hangup in LEGACY_LISTS:
            items = data.get(key)
            if not isinstance(items, list):
                items = ["11111"] if key == "call_dcnow" else []
            rows.append({"id": "", "action": action, "items": [str(n) for n in items if n], "opts": {"hangup": True} if hangup else {}})
        return rows
    return [dict(r, id="") for r in DEFAULT_ROWS]


def _load_rows():
    """The rows from numbers.json, or the default rows without the numbers module (not installed or switched off)."""
    if not _module_active("numbers"):
        return rows_from_data(None)
    try:
        with open(NUMBERS) as f:
            return rows_from_data(json.load(f))
    except Exception:
        return rows_from_data(None)


def _matching(raw_string, rows):
    """[(row, number)] for what was dialed. The dialed string only has to END with a configured number: DreamPi often hears an
    extra leading digit (e.g. 15550002) and ISP settings add prefixes or area codes, so exact matching is unreliable. The longest
    match decides, and every row that has that number runs (a number may be in several rows), in the order of the rows."""
    if not raw_string:
        return []
    found = []
    for row in rows:
        lens = [len(n) for n in row.get("items", []) if n and raw_string.endswith(n)]
        if lens:
            found.append((row, max(lens)))
    best = max([n for _r, n in found] or [0])
    return [(row, raw_string[-best:]) for row, n in found if n == best]


class _Call(object):
    """What an action gets: the dialed string, the number it matched and the add-on's folder; log(text) writes to DreamPi's log."""
    def __init__(self, raw, number, log):
        self.raw, self.number, self.log, self.base_dir = raw, number, log, BASE_DIR


def _action(action_id):
    """The function that does an action ("switcher.dcnow" -> the switcher's hook file, ACTIONS["dcnow"]), or None."""
    name, _dot, key = str(action_id).partition(".")
    part = _module_part(name) if name else None
    fn = getattr(part, "ACTIONS", {}).get(key) if part is not None else None
    return fn if callable(fn) else None


def _patch(module):
    cls = getattr(module, "Netlink", None)
    original = getattr(cls, "check_number", None) if cls is not None else None
    if original is None:
        _write_status("error: Netlink.check_number not found, add-on inactive")
        return
    if getattr(original, "_netswitch", False):
        return

    def check_number(self, raw_string):
        matches = _matching(raw_string, _load_rows())
        if raw_string:
            _dtmf_log("add-on: number heard %r (%s)" % (raw_string, "matches %s" % ", ".join(r["action"] for r, _n in matches) if matches else "no special number"))
        # run the actions of the rows this number is in; a row with "hang up" makes the call end here (no answer, busy tone, like *70)
        done, hangup = [], False
        for row, number in matches:
            fn = _action(row["action"])
            if fn is None:                       # the module of this action is off or gone: the row waits
                continue
            try:
                done.append(fn(_Call(raw_string, number, lambda text: _log(self, text))) or row["action"])
                hangup = hangup or bool(row.get("opts", {}).get("hangup"))
            except Exception as e:
                _log(self, "action %s failed: %s" % (row["action"], e))
        if done:
            _log(self, "%s dialed: %s" % (raw_string, ", ".join(done)))
        if hangup:
            try:
                busy = _play_busy(getattr(self, "modem", None))
                _log(self, "not answering%s" % (", busy tone sent" if busy else ""))
                _write_modem("%s by %s, call not answered" % (", ".join(done), raw_string))
            except Exception as e:
                _log(self, "could not hang up: %s" % e)
            self.mode = "idle"
            return {"client": "idle", "dial_string": raw_string}

        result = original(self, raw_string)

        try:
            if isinstance(result, dict) and result.get("client") == "PPP" and os.path.exists(FLAG):
                if getattr(self, "dcnet", False):
                    self.mode = "dcnet"
                    self.dial_string = raw_string
                    _log(self, "routing %s to DCNET" % raw_string)
                    result = {"client": "dcnet", "dial_string": raw_string}
                else:
                    _log(self, "DCNET selected but not enabled in netlink_config.ini, using DCNow!")
            # Netlink, XBAND, *69 and idle results pass through unchanged
            client = result.get("client") if isinstance(result, dict) else None
            if client and client != "idle":
                _write_state("call " + {"PPP": "dcnow", "dcnet": "dcnet"}.get(client, client))
        except Exception:
            pass
        return result

    check_number._netswitch = True
    cls.check_number = check_number
    _write_status("active pid=%d" % os.getpid())
    _write_state("starting")
    _patch_ready_signals(cls)
    _install_modem_status()


# DreamPi's own log messages -> modem status shown on the web page.
# The first pattern that matches wins; "%s" is filled from the match and
# "{speed}" with the last carrier speed seen.
_MODEM_EVENTS = [
    (r"^Detecting connection and modem", "Looking for the modem", None),
    (r"^Unable to find a modem device", "No modem found, retrying", None),
    (r"^Unable to detect an internet connection", "Waiting for internet", None),
    (r"^Opening serial interface to (\S+)", "Opening modem on %s", "port"),
    (r"^<LISTENING>", "Dial tone on, waiting for a call", "clear"),
    (r"^Heard: (\S+)", "Number dialed: %s", None),
    (r"^(?:Response: )?CONNECT (\d+)", "Carrier up at %s bps", "speed"),
    (r"^DCNet Call answered", "Online via DCNET{speed}", None),
    (r"Call answered", "Answered, starting PPP{speed}", None),
    (r"^Connected$", "Online via DCNow!{speed}", None),
    (r"^Couldn't answer call", "Could not answer the call", "clear"),
    (r"^Detected modem hang up", "Call ended", "clear"),
    (r"^Connection terminated", "Call ended", "clear"),
    (r"^Xband disconnected|^Listener stopped", "Call ended", "clear"),
]
_speed = [""]


POKE_INTERNET = "/tmp/dreampi-netswitch.poke.internet"     # core.poke("internet"): the web service measures the internet again now
_poked = [0.0]


def _poke_internet():
    """DreamPi has just said it sees no internet: ask the web service to look now instead of at its next check (at most every 5 s)."""
    if time.time() - _poked[0] >= 5:
        _poked[0] = time.time()
        _write_file(POKE_INTERNET, "%f\n" % time.time())


def _write_modem(text):
    _write_file(MODEM, "%d %s\n" % (int(time.time()), text))


def _write_port(port):
    _write_file(MODEM_PORT, port + "\n")


class _ModemStatusHandler(logging.Handler):
    """Turns DreamPi's own log lines into a short modem status."""
    def emit(self, record):
        try:
            msg = record.getMessage().strip()
            if msg and not msg.startswith("Rule "):
                _dtmf_log("dreampi: " + msg)
            if msg.startswith("Unable to detect an internet connection"):
                _poke_internet()
            for pattern, text, action in _MODEM_EVENTS:
                m = re.search(pattern, msg)
                if m:
                    if action == "speed":
                        _speed[0] = m.group(1)
                    elif action == "clear":
                        _speed[0] = ""
                    elif action == "port":
                        _write_port(m.group(1))
                    text = text % m.groups() if m.groups() else text
                    _write_modem(text.replace("{speed}", " at %s bps" % _speed[0] if _speed[0] else ""))
                    return
        except Exception:
            pass


def _install_modem_status():
    try:
        logger = logging.getLogger("dreampi")
        if not any(isinstance(h, _ModemStatusHandler) for h in logger.handlers):
            handler = _ModemStatusHandler()
            handler.setLevel(logging.INFO)
            logger.addHandler(handler)
        _write_modem("DreamPi starting")
    except Exception:
        pass


def _wrap_ready(cls, name):
    """Mark DreamPi ready when cls.name has run (the dial tone starting is
    exactly when DreamPi logs <LISTENING>)."""
    original = getattr(cls, name, None)
    if original is None or getattr(original, "_netswitch", False):
        return False

    def wrapper(self, *args, **kwargs):
        value = original(self, *args, **kwargs)
        _write_state("ready")
        # A new serial object is opened after every call, so watch it again
        _watch_serial(getattr(self, "modem", self))
        return value

    wrapper._netswitch = True
    setattr(cls, name, wrapper)
    return True


def _patch_ready_signals(netlink_cls):
    # dreampi.py runs as the __main__ module and defines Modem there. It
    # imports netlink inside process(), so Modem already exists at this point.
    try:
        main = sys.modules.get("__main__")
        modem = getattr(main, "Modem", None)
        if modem is None or not _wrap_ready(modem, "start_dial_tone"):
            _write_state("unknown")
        # The USB serial path goes back to idle without a dial tone
        _wrap_ready(netlink_cls, "reset_serial")
    except Exception:
        pass


def _import_hook(name, *args, **kwargs):
    module = _original_import(name, *args, **kwargs)
    if not _done[0] and name == "netlink":
        try:
            mod = sys.modules.get("netlink")
            path = os.path.realpath(getattr(mod, "__file__", "") or "")
            if mod is not None and path.startswith(os.path.realpath(NETLINK_DIR)):
                _done[0] = True
                _patch(mod)
                _builtins.__import__ = _original_import
        except Exception as e:
            _write_status("error: %s" % e)
    return module


def _is_dreampi_process():
    # sys.argv does not exist yet when Python 2 processes .pth files, so the
    # command line is read from /proc instead. If that fails, hook anyway:
    # the hook only reacts to netlink.py from /home/pi/dreampi.
    try:
        with open("/proc/self/cmdline", "rb") as f:
            return b"dreampi" in f.read()
    except Exception:
        return True


try:
    if _is_dreampi_process():
        _builtins.__import__ = _import_hook
except Exception:
    pass
