# Check-in add-on - things the web service measures: the internet check, the Pi's address and the About rows.
# Works on Python 3.
import os
import socket

import netswitch_core as core

ADDON_VERSION = os.path.join(core.BASE_DIR, "version")   # written by install.sh


def check_internet():
    """Reach public DNS servers over TCP, then resolve a well-known host name. {"state": ok / warn / bad, "text", "ms"}."""
    import time
    best = None
    for host in ("1.1.1.1", "8.8.8.8", "208.67.222.222"):
        start = time.time()
        try:
            s = socket.create_connection((host, 53), 3)
            s.close()
            best = int((time.time() - start) * 1000)
            break
        except Exception:
            continue
    if best is None:
        return {"state": "bad", "text": "No internet connection"}
    try:
        socket.gethostbyname("github.com")
    except Exception:
        return {"state": "warn", "text": "Connected, but DNS lookups fail"}
    return {"state": "ok", "text": "Connected", "ms": best}


def lan_ip():
    """The Pi's address on the local network (the one its default route uses; no packet is sent), or None."""
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
    rows = [("Add-on", core.read_file(ADDON_VERSION) or "unknown"),
            ("Address", lan_ip() or "unknown"),
            ("Computer", (model or "unknown").replace("\x00", "")),
            ("System", osname or "unknown")]
    return rows
