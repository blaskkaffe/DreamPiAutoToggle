"""Live status of the whole bridge for the web page and dashboards: the
RP2040's own status line (/dev/dcbridge-ctl) plus the two Dreamcast network
links set up by dcbridge-net."""
import errno
import json
import logging
import os
import subprocess
import threading
import time
import tty

log = logging.getLogger("dcbridge-saves")

DEFAULTS = {
    "DCNET_IF": "dcnet0", "DCNET_ADDR": "192.168.170.1", "PPP_UNIT": "10",
    "PPP_LOCAL": "192.168.171.1", "PPP_REMOTE": "192.168.171.2",
}


def read_config(path="/etc/default/dcbridge"):
    conf = dict(DEFAULTS)
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                conf[k.strip()] = v.strip().strip('"').strip("'")
    except IOError:
        pass
    return conf


def _ipv4(ifname):
    try:
        out = subprocess.check_output(["ip", "-o", "-4", "addr", "show", "dev", ifname],
                                      stderr=subprocess.DEVNULL).decode()
    except (subprocess.CalledProcessError, OSError):
        return None, None
    for line in out.splitlines():
        parts = line.split()
        if "inet" in parts:
            i = parts.index("inet")
            addr = parts[i + 1]
            peer = parts[parts.index("peer") + 1] if "peer" in parts else None
            return addr, peer
    return None, None


def link_status(conf, run_dir="/run/dcbridge"):
    dcnet = conf["DCNET_IF"]
    ppp = "ppp" + conf["PPP_UNIT"]
    out = {}
    for name, ifc in (("w5500", dcnet), ("ppp", ppp)):
        present = os.path.exists("/sys/class/net/%s" % ifc)
        state = None
        if present:
            try:
                with open("/sys/class/net/%s/operstate" % ifc) as f:
                    state = f.read().strip()
            except IOError:
                pass
        addr, peer = _ipv4(ifc) if present else (None, None)
        out[name] = {"interface": ifc, "present": present, "state": state, "address": addr}
        if name == "w5500":
            try:
                with open(os.path.join(run_dir, "dcnet-ip")) as f:
                    out[name]["dreamcast"] = f.read().strip()
            except IOError:
                out[name]["dreamcast"] = None
        else:
            out[name]["dreamcast"] = peer.split("/")[0] if peer else None
    return out


USB_ID = ("1209", "0001")        # firmware/dcbridge/src/config.h USB_VID / USB_PID


def usb_seen(sys_usb="/sys/bus/usb/devices"):
    """The RP2040 board is on the Pi's USB bus (looks for its vendor / product id), whatever the udev rules did with it."""
    try:
        names = os.listdir(sys_usb)
    except OSError:
        return None
    for name in names:
        try:
            with open(os.path.join(sys_usb, name, "idVendor")) as f:
                vid = f.read().strip()
            with open(os.path.join(sys_usb, name, "idProduct")) as f:
                pid = f.read().strip()
        except IOError:
            continue
        if (vid, pid) == USB_ID:
            return True
    return False


def device_nodes(ctl_path):
    """Which of the udev names the rules should have made exist: {"uart", "ctl", "disk"} -> bool."""
    d = os.path.dirname(ctl_path or "/dev/dcbridge-ctl")
    return {"uart": os.path.exists(os.path.join(d, "dcbridge-uart")), "ctl": os.path.exists(ctl_path or os.path.join(d, "dcbridge-ctl")),
            "disk": os.path.exists(os.path.join(d, "dcbridge-disk"))}


class BridgeStatus(object):
    """Follows /dev/dcbridge-ctl (one JSON object per line, about every second)."""

    def __init__(self, ctl_path, conf_path="/etc/default/dcbridge"):
        self.ctl_path = ctl_path
        self.conf_path = conf_path
        self.firmware = None
        self.firmware_at = None
        self._stop = threading.Event()

    def start(self):
        if self.ctl_path:
            threading.Thread(target=self._loop, name="ctl", daemon=True).start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                fd = os.open(self.ctl_path, os.O_RDONLY | os.O_NOCTTY)
            except OSError as e:
                if e.errno not in (errno.ENOENT, errno.ENODEV, errno.EACCES):
                    log.warning("open %s: %s", self.ctl_path, e)
                time.sleep(2)
                continue
            try:
                try:
                    tty.setraw(fd)
                except Exception:
                    pass
                buf = b""
                while not self._stop.is_set():
                    chunk = os.read(fd, 4096)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        line = line.strip()
                        if line.startswith(b"{"):
                            try:
                                self.firmware = json.loads(line.decode("utf-8", "replace"))
                                self.firmware_at = time.time()
                            except ValueError:
                                pass
                    buf = buf[-4096:]
            except OSError:
                pass
            finally:
                os.close(fd)
            time.sleep(1)

    def snapshot(self):
        conf = read_config(self.conf_path)
        fresh = self.firmware_at and time.time() - self.firmware_at < 5
        fw = self.firmware if fresh else None
        summary = "RP2040 not connected"
        if fw:
            if fw.get("mode") == "uart":
                summary = "serial %d baud" % fw.get("baud", 0)
            elif fw.get("spi") == "sd":
                summary = "SD card"
            elif fw.get("spi") == "w5500":
                summary = "W5500 network"
            else:
                summary = "idle"
        out = {"summary": summary, "firmware": fw, "links": link_status(conf)}
        if not fw:                      # why there is no status: the board is not on USB / has no udev names / says nothing
            out["usb"] = usb_seen()
            out["devices"] = device_nodes(self.ctl_path)
        return out
