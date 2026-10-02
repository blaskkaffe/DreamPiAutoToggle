# DreamPi Netswitch add-on - debug log module, the part that runs inside DreamPi.
# netswitch_hook.py loads this file only while the module is installed and switched on; without it the hook
# logs nothing. While recording is on (the file debug_dtmf exists) it writes every modem event DreamPi hears
# while listening for digits, and the hook's own decisions, to /tmp/dreampi-netswitch-dtmf.log with the time and
# the milliseconds since the previous line - to diagnose misheard numbers.
# Runs in DreamPi, so it must stay Python 2.7 and 3 compatible: no f-strings, no type hints.
import os
import time

BASE_DIR = "/opt/dreampi-netswitch"
DEBUG_DTMF = os.path.join(BASE_DIR, "debug_dtmf")  # exists = log modem events
DTMF_LOG = "/tmp/dreampi-netswitch-dtmf.log"

_last = [0.0]


def log(text):
    """Append a line to the debug log (only while recording): time, milliseconds since the previous line, event."""
    if not os.path.exists(DEBUG_DTMF):
        return
    try:
        now = time.time()
        gap = "" if not _last[0] else "+%dms" % int((now - _last[0]) * 1000)
        _last[0] = now
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
                log("modem: DTMF " + code)
            else:
                log("modem: " + _DLE_CODES.get(code, "event <DLE>%r" % code))
            continue
        if b in (0x10, 0x0D, 0x0A):
            text = buf.decode("ascii", "replace").strip()
            if text:
                log("modem says: " + text)
            _serial_buf[0] = bytearray(b"\x10") if b == 0x10 else bytearray()
            continue
        buf.append(b)


def watch(modem):
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
