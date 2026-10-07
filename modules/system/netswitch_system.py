# DreamPi Netswitch add-on - system module, web side: GET /about, the name / value rows under Settings > System (the versions of
# the add-on, DreamPi's own scripts, the Pi and its system, and the PIN state). Other modules add rows with an about_rows()
# function (the network switcher: the modem), collected by the base: modules.collect("about_rows").
import json
import os

import base_core as core
import base_modules as modules
import base_security as security

DREAMPI_DIR = "/home/pi/dreampi"
VERSION_FILE = os.path.join(core.BASE_DIR, "version")      # written by install.sh: date and commit of the installed checkout


def script_version(path):
    """DreamPi's own version line in a script ("#dreampi.py_version=
    202512152004", the timestamp its updater compares) as a readable date."""
    try:
        with open(path, "rb") as f:
            for raw in f:
                line = raw.decode("utf-8", "replace")
                if "_version=" in line:
                    v = line.split("version=")[1].strip()
                    if len(v) == 12 and v.isdigit():
                        return "%s-%s-%s %s:%s" % (v[:4], v[4:6], v[6:8], v[8:10], v[10:12])
                    return v or None
    except (IOError, OSError):
        return None
    return None


def about():
    model = core.read_file("/proc/device-tree/model")
    osname = None
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    osname = line.split("=", 1)[1].strip().strip('"')
    except (IOError, OSError):
        pass
    rows = [("Add-on", core.read_file(VERSION_FILE) or "unknown")]
    for name in ("dreampi.py", "netlink.py", "dcnow.py"):
        rows.append((name, script_version(os.path.join(DREAMPI_DIR, name)) or "not found"))
    rows.append(("Raspberry Pi", (model or "unknown").replace("\x00", "")))
    rows.append(("System", osname or "unknown"))
    return rows


def _about(h):
    rows = about() + [tuple(r) for r in modules.collect("about_rows")]
    rows.append(("PIN", "Asked before update, restart and Wi-Fi connect" if security.pin_required()
                 else "Off: anyone on your network can update or restart (install.sh --pin sets one)"))
    h.send(json.dumps(rows), "application/json")


GET = {"/about": _about}
