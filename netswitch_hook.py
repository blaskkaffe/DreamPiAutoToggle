# -*- coding: utf-8 -*-
"""
DreamPi Netswitch add-on - routing hook.

Loaded automatically by Python (through a .pth file) but does nothing unless
the running program imports DreamPi's netlink.py from /home/pi/dreampi.
It then wraps Netlink.check_number() with these rules:

  1111111  openMenu's number. Always DC Now. If the reset toggle is on,
           it also switches the selected network back to DC Now.
  2222222  Selects DC Now and connects through DC Now.
  3333333  Selects DCNet and connects through DCNet.
  others   Go to whichever network is selected (website or 2222222/3333333).
           Only calls DreamPi would send to its normal PPP are redirected;
           Netlink/XBAND codes and the built-in *69 prefix are untouched.

The selection is the file dcnet_mode, the reset toggle is the file autoreset.
It also reports DreamPi's state (starting / ready / in a call) to
/tmp/dreampi-netswitch.state for the web page. If the file debug_dtmf exists,
it also logs every modem event while DreamPi listens for digits to
/tmp/dreampi-netswitch-dtmf.log, to diagnose misheard numbers.
No DreamPi file is modified. Written for both Python 2.7 and 3.
"""
import logging
import os
import re
import sys
import time

BASE_DIR = "/opt/dreampi-netswitch"
FLAG = os.path.join(BASE_DIR, "dcnet_mode")
AUTORESET = os.path.join(BASE_DIR, "autoreset")
STATUS = "/tmp/dreampi-netswitch.active"
STATE = "/tmp/dreampi-netswitch.state"
DEBUG_DTMF = os.path.join(BASE_DIR, "debug_dtmf")  # exists = log modem events
DTMF_LOG = "/tmp/dreampi-netswitch-dtmf.log"
MODEM = "/tmp/dreampi-netswitch.modem"
NETLINK_DIR = "/home/pi/dreampi"

NUM_OPENMENU = "1111111"
NUM_DCNOW = "2222222"
NUM_DCNET = "3333333"

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


def _select_dcnet(on):
    if on:
        open(FLAG, "w").close()
    elif os.path.exists(FLAG):
        os.remove(FLAG)


def _special(raw_string):
    """Which special number was dialed, matched on the last seven digits.
    DreamPi often hears an extra leading digit (e.g. 13333333), and ISP
    settings may add a prefix or area code, so exact matching is unreliable."""
    for number in (NUM_OPENMENU, NUM_DCNOW, NUM_DCNET):
        if raw_string.endswith(number):
            return number
    return None


def _patch(module):
    cls = getattr(module, "Netlink", None)
    original = getattr(cls, "check_number", None) if cls is not None else None
    if original is None:
        _write_status("error: Netlink.check_number not found, add-on inactive")
        return
    if getattr(original, "_netswitch", False):
        return

    def check_number(self, raw_string):
        special = _special(raw_string)
        if raw_string:
            _dtmf_log("add-on: number heard %r (matches %s)" % (raw_string, special or "no special number"))
        # Special numbers: remember the choice before DreamPi routes the call
        try:
            if special == NUM_DCNOW:
                _select_dcnet(False)
                _log(self, "%s dialed, DC Now selected" % raw_string)
            elif special == NUM_DCNET:
                _select_dcnet(True)
                _log(self, "%s dialed, DCNet selected" % raw_string)
            elif special == NUM_OPENMENU and os.path.exists(AUTORESET) and os.path.exists(FLAG):
                _select_dcnet(False)
                _log(self, "%s dialed with reset on, back to DC Now" % raw_string)
        except Exception as e:
            _log(self, "could not update selection: %s" % e)

        result = original(self, raw_string)

        try:
            if isinstance(result, dict) and result.get("client") == "PPP" \
                    and special not in (NUM_OPENMENU, NUM_DCNOW) and os.path.exists(FLAG):
                if getattr(self, "dcnet", False):
                    self.mode = "dcnet"
                    self.dial_string = raw_string
                    _log(self, "routing %s to DCNet" % raw_string)
                    result = {"client": "dcnet", "dial_string": raw_string}
                else:
                    _log(self, "DCNet selected but not enabled in netlink_config.ini, using DC Now")
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
    (r"^Opening serial interface to (\S+)", "Opening modem on %s", None),
    (r"^<LISTENING>", "Dial tone on, waiting for a call", "clear"),
    (r"^Heard: (\S+)", "Number dialed: %s", None),
    (r"^(?:Response: )?CONNECT (\d+)", "Carrier up at %s bps", "speed"),
    (r"^DCNet Call answered", "Online via DCNet{speed}", None),
    (r"Call answered", "Answered, starting PPP{speed}", None),
    (r"^Connected$", "Online via DC Now{speed}", None),
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
