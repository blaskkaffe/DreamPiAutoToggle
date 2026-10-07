# Check-in add-on - system module, web side: GET /about, the name / value rows under Settings > About (the version of the add-on,
# the address, the computer and its system, and the PIN state). Other modules add rows with an about_rows() function, collected by
# the base: modules.collect("about_rows").
import json
import os
import socket

import base_core as core
import base_modules as modules
import base_security as security

VERSION_FILE = os.path.join(core.BASE_DIR, "version")      # written by install.sh: date and commit of the installed checkout


def lan_ip():
    """The computer's address on the local network (the one its default route uses; no packet is sent), or None."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("192.0.2.1", 9))   # documentation address, never contacted
            ip = sock.getsockname()[0]
        finally:
            sock.close()
        return None if ip.startswith("0.") else ip
    except (socket.error, OSError):
        return None


def about():
    """[(name, value)] rows for Settings > About."""
    model = core.read_file("/proc/device-tree/model")
    osname = None
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    osname = line.split("=", 1)[1].strip().strip('"')
    except (IOError, OSError):
        pass
    return [("Add-on", core.read_file(VERSION_FILE) or "unknown"),
            ("Address", lan_ip() or "unknown"),
            ("Computer", (model or "unknown").replace("\x00", "")),
            ("System", osname or "unknown")]


def _about(h):
    rows = about() + [tuple(r) for r in modules.collect("about_rows")]
    rows.append(("PIN", "Asked before update and restart" if security.pin_required()
                 else "Off: anyone on your network can update or restart (install.sh --pin sets one)"))
    h.send(json.dumps(rows), "application/json")


GET = {"/about": _about}
