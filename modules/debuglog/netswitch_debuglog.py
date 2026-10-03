# DreamPi Netswitch add-on - debug log module, web side.
# The log itself is /tmp/dreampi-netswitch-dtmf.log: DreamPi's hook (netswitch_hookdebug.py in this folder) and the
# web service add timed lines to it while "recording" is on (the file debug_dtmf exists). This file answers the
# page: GET /log (new text since an offset, for the live view), GET /dtmf (the log as plain text), POST /debug
# (recording on / off) and POST /clearlog, and tells /api whether recording is on. Works on Python 3 and 2.7.
import json
import os
import re

import netswitch_core as core

TEXT_TAIL = 256000    # "Newest 256 KB" shows this much unless ?all


def read_log(start):
    """New log text from byte offset start. If the log was cleared or
    restarted, everything is returned with reset=True."""
    try:
        with open(core.DTMF_LOG, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            reset = start > size or start < 0
            if reset:
                start = 0
            # Don't send megabytes to a page that just opened
            if size - start > 200000:
                start, reset = size - 200000, True
            f.seek(start)
            data = f.read()
    except IOError:
        return {"size": 0, "text": "", "reset": start != 0}
    return {"size": start + len(data), "text": data.decode("utf-8", "replace"), "reset": reset}


def log_text(full=False):
    """The log as bytes for the "open as text" links."""
    try:
        with open(core.DTMF_LOG, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            start = 0 if full or size <= TEXT_TAIL else size - TEXT_TAIL
            f.seek(start)
            body = f.read()
        if start:
            body = body[body.find(b"\n") + 1:]   # start at a whole line
        return body
    except IOError:
        return b"No debug log yet. Switch on Recording and dial.\n"


def _get_log(h):
    m = re.search(r"from=(-?\d+)", h.path)
    h.send(json.dumps(read_log(int(m.group(1)) if m else 0)), "application/json")


def _get_text(h):
    full = "?" in h.path and "all" in h.path.split("?", 1)[-1]
    h.send(log_text(full), "text/plain; charset=utf-8")


def _post_debug(h):
    if os.path.exists(core.DEBUG_DTMF):
        core.debug_log("web page: debug log stopped")
        os.remove(core.DEBUG_DTMF)
    else:
        open(core.DEBUG_DTMF, "w").close()
        if os.path.exists(core.DTMF_LOG):
            os.remove(core.DTMF_LOG)  # start a fresh log
        core.debug_log("web page: debug log started (network: %s)" %
                       ("DCNET" if os.path.exists(core.FLAG) else "DCNow!"))


def _post_clear(h):
    if os.path.exists(core.DTMF_LOG):
        os.remove(core.DTMF_LOG)
    core.debug_log("web page: log cleared")


GET = {"/log": _get_log, "/dtmf": _get_text}
POST = {"/debug": _post_debug, "/clearlog": _post_clear}


def api(d, warnings):
    on = os.path.exists(core.DEBUG_DTMF)
    d["debug"] = on
    d["debuglog"] = {"on": on, "label": "\u25cf Recording" if on else "Recording off"}
