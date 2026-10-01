# -*- coding: utf-8 -*-
"""
DreamPi Netswitch add-on - routing hook.

Loaded automatically by Python (through a .pth file) but does nothing unless
the running program imports DreamPi's netlink.py from /home/pi/dreampi.
It then wraps Netlink.check_number() with these rules:

  1111111  openMenu's number. Always DCNow! If the reset toggle is on,
           it also switches the selected network back to the default
           network (DCNow! unless the file default_dcnet exists).
  numbers  Five lists of numbers set on the web page (numbers.json), matched
           against the END of what was dialed (a short ending or a full
           number; the longest match wins):
             reset         selects the default network, hangs up (busy tone)
             toggle_dcnow  selects DCNow!, hangs up
             toggle_dcnet  selects DCNET, hangs up
             call_dcnow    selects DCNow! and connects through DCNow!
             call_dcnet    selects DCNET and connects through DCNET
           Defaults: 1111111# / 5550001# / 5550002# / 5550001 / 5550002.
  others   Go to whichever network is selected (website or the numbers above).
           Only calls DreamPi would send to its normal PPP are redirected;
           Netlink/XBAND codes and the built-in *69 prefix are untouched.

The selection is the file dcnet_mode, the reset toggle is the file autoreset,
the default network for the reset is the file default_dcnet (exists = DCNET).
It also reports DreamPi's state (starting / ready / in a call) to
/tmp/dreampi-netswitch.state for the web page. If the file debug_dtmf exists,
it also logs every modem event while DreamPi listens for digits to
/tmp/dreampi-netswitch-dtmf.log, to diagnose misheard numbers.
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
AUTORESET = os.path.join(BASE_DIR, "autoreset")
DEFAULT_DCNET = os.path.join(BASE_DIR, "default_dcnet")  # exists = reset goes to DCNET
STATUS = "/tmp/dreampi-netswitch.active"
STATE = "/tmp/dreampi-netswitch.state"
DEBUG_DTMF = os.path.join(BASE_DIR, "debug_dtmf")  # exists = log modem events
DTMF_LOG = "/tmp/dreampi-netswitch-dtmf.log"
MODEM = "/tmp/dreampi-netswitch.modem"
MODEM_PORT = "/tmp/dreampi-netswitch.port"   # the serial device DreamPi opened, e.g. /dev/ttyUSB0
NETLINK_DIR = "/home/pi/dreampi"

NUMBERS = os.path.join(BASE_DIR, "numbers.json")   # the five lists below, edited on the web page

NUM_OPENMENU = "1111111"   # fixed: openMenu always dials this and it must stay on DCNow!
# Action -> numbers. Order is the tie-break when two entries are equally long.
# Keep in sync with netswitch_numbers.DEFAULTS (a test compares them).
NUMBER_ACTIONS = ("reset", "toggle_dcnow", "toggle_dcnet", "call_dcnow", "call_dcnet")
DEFAULT_NUMBERS = {"reset": ["1111111#"], "toggle_dcnow": ["5550001#"], "toggle_dcnet": ["5550002#"],
                   "call_dcnow": ["5550001"], "call_dcnet": ["5550002"]}
HANGUP_ACTIONS = ("reset", "toggle_dcnow", "toggle_dcnet")   # select, then hang up

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


def _write_status(text):
    try:
        with open(STATUS, "w") as f:
            f.write(text + "\n")
    except Exception:
        pass


def _write_state(state):
    """DreamPi's current state for the web page: starting, ready,
    call <network> or unknown, with a unix timestamp."""
    try:
        with open(STATE, "w") as f:
            f.write("%s %d\n" % (state, int(time.time())))
    except Exception:
        pass


_dtmf_last = [0.0]


def _dtmf_log(text):
    """Append a line to the debug log (only when enabled):
    time, milliseconds since the previous line, and the event."""
    if not os.path.exists(DEBUG_DTMF):
        return
    try:
        now = time.time()
        gap = "" if not _dtmf_last[0] else "+%dms" % int((now - _dtmf_last[0]) * 1000)
        _dtmf_last[0] = now
        with open(DTMF_LOG, "a") as f:
            f.write("%s.%03d %9s  %s\n" % (time.strftime("%H:%M:%S", time.localtime(now)),
                                          int(now * 1000) % 1000, gap, text))
    except Exception:
        pass


# What the modem means by <DLE><code> in voice mode (ITU V.253 / Rockwell)
_DLE_CODES = {
    "u": "dial tone ran out (transmit underrun)",
    "o": "receive overrun",
    "b": "busy tone",
    "d": "dial tone detected",
    "s": "silence",
    "q": "quiet after tone",
    "c": "fax calling tone",
    "e": "calling tone from a modem (1300 Hz)",
    "a": "answer tone (2100 Hz)",
    "R": "ring",
    "h": "line hung up",
    "l": "loop current break",
    "/": "DTMF tone starts",
    "~": "DTMF tone ends",
}
_serial_buf = [bytearray()]


def _serial_feed(data):
    """Turn raw modem bytes into readable events: <DLE><code> pairs become
    'DTMF 1' etc., other text is collected into whole lines."""
    for b in bytearray(data):
        buf = _serial_buf[0]
        if buf[:1] == bytearray(b"\x10"):
            code = chr(b)
            _serial_buf[0] = bytearray()
            if code in "0123456789*#ABCD":
                _dtmf_log("modem: DTMF " + code)
            else:
                _dtmf_log("modem: " + _DLE_CODES.get(code, "event <DLE>%r" % code))
            continue
        if b in (0x10, 0x0D, 0x0A):
            text = buf.decode("ascii", "replace").strip()
            if text:
                _dtmf_log("modem says: " + text)
            _serial_buf[0] = bytearray(b"\x10") if b == 0x10 else bytearray()
            continue
        buf.append(b)


def _watch_serial(modem):
    """Log what the modem reports while DreamPi is listening (dial tone on),
    which is when dialed digits arrive as <DLE><digit>."""
    try:
        ser = getattr(modem, "_serial", None)
        if ser is None or getattr(ser, "_netswitch", False):
            return
        original_read = ser.read

        def read(*args, **kwargs):
            data = original_read(*args, **kwargs)
            if data and getattr(modem, "_sending_tone", False) and os.path.exists(DEBUG_DTMF):
                _serial_feed(data)
            return data

        ser.read = read
        ser._netswitch = True
    except Exception:
        pass


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


def _select_dcnet(on):
    if on:
        open(FLAG, "w").close()
    elif os.path.exists(FLAG):
        os.remove(FLAG)


def _load_numbers():
    """The number lists from numbers.json; a missing, unreadable or partly
    wrong file falls back to the defaults for what it doesn't provide."""
    numbers = dict((k, list(v)) for k, v in DEFAULT_NUMBERS.items())
    try:
        with open(NUMBERS) as f:
            data = json.load(f)
        for key in NUMBER_ACTIONS:
            if isinstance(data.get(key), list):
                numbers[key] = [str(n) for n in data[key] if n]
    except Exception:
        pass
    return numbers


def _classify(raw_string, numbers):
    """(action, number) for what was dialed, or (None, None). The dialed
    string only has to END with a configured number: DreamPi often hears an
    extra leading digit (e.g. 15550002) and ISP settings add prefixes or area
    codes, so exact matching is unreliable. The longest match wins; openMenu's
    fixed number is "openmenu" and wins ties."""
    if not raw_string:
        return None, None
    best, best_len = (None, None), 0
    candidates = [("openmenu", NUM_OPENMENU)]
    for action in NUMBER_ACTIONS:
        candidates += [(action, n) for n in numbers.get(action, [])]
    for action, number in candidates:
        if number and raw_string.endswith(number) and len(number) > best_len:
            best, best_len = (action, number), len(number)
    return best


def _patch(module):
    cls = getattr(module, "Netlink", None)
    original = getattr(cls, "check_number", None) if cls is not None else None
    if original is None:
        _write_status("error: Netlink.check_number not found, add-on inactive")
        return
    if getattr(original, "_netswitch", False):
        return

    def check_number(self, raw_string):
        action, matched = _classify(raw_string, _load_numbers())
        if raw_string:
            _dtmf_log("add-on: number heard %r (%s)" % (raw_string, "matches %s %r" % (action, matched) if action else "no special number"))
        # Hang-up numbers: select a network, don't answer, busy tone (like *70)
        if action in HANGUP_ACTIONS:
            try:
                if action == "reset":
                    dcnet = os.path.exists(DEFAULT_DCNET)
                else:
                    dcnet = action == "toggle_dcnet"
                _select_dcnet(dcnet)
                net = "DCNET" if dcnet else "DCNow!"
                busy = _play_busy(getattr(self, "modem", None))
                _log(self, "%s dialed (%s): %s selected, not answering%s"
                     % (raw_string, action, net, ", busy tone sent" if busy else ""))
                _write_modem("Switched to %s by %s, call not answered" % (net, raw_string))
            except Exception as e:
                _log(self, "could not switch network: %s" % e)
            self.mode = "idle"
            return {"client": "idle", "dial_string": raw_string}
        # Call numbers: remember the choice before DreamPi routes the call
        try:
            if action == "call_dcnow":
                _select_dcnet(False)
                _log(self, "%s dialed, DCNow! selected" % raw_string)
            elif action == "call_dcnet":
                _select_dcnet(True)
                _log(self, "%s dialed, DCNET selected" % raw_string)
            elif action == "openmenu" and os.path.exists(AUTORESET):
                default_dcnet = os.path.exists(DEFAULT_DCNET)
                if os.path.exists(FLAG) != default_dcnet:
                    _select_dcnet(default_dcnet)
                    _log(self, "%s dialed with reset on, back to the default (%s)"
                         % (raw_string, "DCNET" if default_dcnet else "DCNow!"))
        except Exception as e:
            _log(self, "could not update selection: %s" % e)

        result = original(self, raw_string)

        try:
            if isinstance(result, dict) and result.get("client") == "PPP" \
                    and action not in ("openmenu", "call_dcnow") and os.path.exists(FLAG):
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


def _write_modem(text):
    try:
        with open(MODEM, "w") as f:
            f.write("%d %s\n" % (int(time.time()), text))
    except Exception:
        pass


def _write_port(port):
    try:
        with open(MODEM_PORT, "w") as f:
            f.write(port + "\n")
    except Exception:
        pass


class _ModemStatusHandler(logging.Handler):
    """Turns DreamPi's own log lines into a short modem status."""
    def emit(self, record):
        try:
            msg = record.getMessage().strip()
            if msg and not msg.startswith("Rule "):
                _dtmf_log("dreampi: " + msg)
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
