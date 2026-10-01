#!/usr/bin/env python3
# DreamPi Netswitch add-on - web page to choose DCNow! or DCNET.
# Shows DreamPi's and the modem's live status and internet access, plus an
# optional debug timeline. It only creates/removes the files that
# netswitch_hook.py reads.
# Works on Python 3 and 2.7.
import colorsys
import gzip
import io
import json
import os
import re
import socket
import sys
import subprocess
import threading
import time
import traceback

import ssl
try:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from socketserver import ThreadingMixIn
except ImportError:
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
    from SocketServer import ThreadingMixIn

BASE_DIR = "/opt/dreampi-netswitch"
FLAG = os.path.join(BASE_DIR, "dcnet_mode")
AUTORESET = os.path.join(BASE_DIR, "autoreset")
DEFAULT_DCNET = os.path.join(BASE_DIR, "default_dcnet")
DEBUG_DTMF = os.path.join(BASE_DIR, "debug_dtmf")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
STATIC_FILES = {   # only these are served from /static/
    "three.min.js": "application/javascript; charset=utf-8",
    "dc-background.js": "application/javascript; charset=utf-8",
    "LICENSES.txt": "text/plain; charset=utf-8",
    "favicon-dcnow.png": "image/png",   # DreamPi logo (without the text)
    "favicon-dcnet.png": "image/png",   # Flycast logo while DCNET is selected
    "touch-dcnow.png": "image/png",
    "touch-dcnet.png": "image/png",
}
LED_CONFIG = os.path.join(BASE_DIR, "led.json")     # brightness, colours, wire order, white balance
LED_ENABLED = os.path.join(BASE_DIR, "led_enabled")  # written by install.sh --led
LED_COUNT = os.path.join(BASE_DIR, "led_count")      # number of LEDs, editable from the page
LED_GPIO = os.path.join(BASE_DIR, "led_gpio")        # output pin (10, 12, 18 or 21), likewise
LED_HIDDEN = os.path.join(BASE_DIR, "led_hidden")    # exists = LED settings hidden on the page
STATUS = "/tmp/dreampi-netswitch.active"
STATE = "/tmp/dreampi-netswitch.state"
MODEM = "/tmp/dreampi-netswitch.modem"
DTMF_LOG = "/tmp/dreampi-netswitch-dtmf.log"
# Wi-Fi setup (netswitch_buttons.py, install.sh --wifi); the buttons themselves are always installed
WIFI_ENABLED = os.path.join(BASE_DIR, "wifi_enabled")  # written by install.sh --wifi
WIFI_START = os.path.join(BASE_DIR, "wifi_start")   # touched to ask netswitch_buttons.py to start
WIFI_STOP = os.path.join(BASE_DIR, "wifi_stop")     # touched to ask it to stop / cancel
WIFI_CONNECT = os.path.join(BASE_DIR, "wifi_connect")   # {"ssid":..., "password":...}, an alternative
                                                         # to the setup access point's own /connect -
                                                         # lets the regular page pick a network too,
                                                         # useful when it's reachable some other way
                                                         # (e.g. Ethernet) while Wi-Fi is being set up
WIFI_STATE = "/tmp/dreampi-netswitch.wifi"          # written by netswitch_buttons.py
WIFI_STALE = 30       # ignore WIFI_STATE when older than this (the service is down)
WIFI_AP_SSID = "DreamPi WiFi Config"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 80
HTTPS_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 443   # 0 = no HTTPS
CERT = os.path.join(BASE_DIR, "https.crt")   # self-signed, made by install.sh
KEY = os.path.join(BASE_DIR, "https.key")

INTERNET_EVERY = 30   # seconds between internet checks while it works
INTERNET_RETRY = 5    # ... and while it doesn't
LINK_EVERY = 2        # seconds between checks of cables / Wi-Fi / route
NET_STATE = "/tmp/dreampi-netswitch.net"   # shared with the LED service
NET_STALE = 20        # ignore NET_STATE when older than this (web service down)

_checks = {"internet": {"state": "checking", "text": "Checking...", "time": 0},
           "pi": {"state": "checking", "text": "Checking...", "problem": False, "undervoltage": False}}
_checks_lock = threading.Lock()


# ---------------------------------------------------------------- file state

def read_file(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except IOError:
        return None


def hook_problem():
    """None when DreamPi is running with the hook loaded, else a reason."""
    status = read_file(STATUS)
    if status is None:
        return "DreamPi has not loaded the add-on yet (restart DreamPi or reboot)"
    if not status.startswith("active"):
        return status
    m = re.search(r"pid=(\d+)", status)
    if m and not os.path.exists("/proc/" + m.group(1)):
        return "DreamPi is not running"
    return None


def dcnet_problem():
    """None when DreamPi's DCNET support is switched on, else a reason."""
    if os.path.exists("/boot/noautoupdates.txt"):
        return ("/boot/noautoupdates.txt exists, so DreamPi skips netlink_config.ini "
                "and DCNET stays off")
    for path in ("/boot/netlink_config.ini", "/home/pi/dreampi/netlink_config.ini"):
        if os.path.isfile(path):
            break
    else:
        return "netlink_config.ini not found, so DCNET is off"
    text = read_file(path) or ""
    section = re.search(r"^\[DCNet\](.*?)(?=^\[|\Z)", text, re.M | re.S)
    if not section or not re.search(r"^\s*enabled\s*=\s*yes\s*$", section.group(1), re.M):
        return "DCNET is not enabled in " + path + " ([DCNet] enabled = yes)"
    return None


def dreampi_state():
    """(state, text) for what DreamPi is doing right now."""
    if hook_problem() == "DreamPi is not running":
        return "off", "Not running"
    parts = (read_file(STATE) or "").split()
    if len(parts) < 2:
        return "unknown", "State unknown"
    state = " ".join(parts[:-1])
    if state == "starting":
        return "busy", "Starting up, not answering calls yet"
    if state == "ready":
        return "ok", "Ready for calls"
    if state.startswith("call "):
        kind = state[5:]
        net = {"dcnow": "DCNow!", "dcnet": "DCNET"}.get(kind, kind)
        return ("call-" + kind if kind in ("dcnow", "dcnet") else "call"), "In a call: " + net
    return "unknown", "State unknown"


def modem_state():
    """(text, unix time) of the latest modem event DreamPi logged."""
    if hook_problem() == "DreamPi is not running":
        return "DreamPi not running", 0
    raw = read_file(MODEM)
    if not raw or " " not in raw:
        return "Unknown", 0
    since, text = raw.split(" ", 1)
    try:
        return text, int(since)
    except ValueError:
        return text, 0


def debug_log(text):
    """Add a line to the debug timeline (same format as the hook)."""
    if not os.path.exists(DEBUG_DTMF):
        return
    try:
        now = time.time()
        with open(DTMF_LOG, "a") as f:
            f.write("%s.%03d %9s  %s\n" % (time.strftime("%H:%M:%S", time.localtime(now)),
                                          int(now * 1000) % 1000, "", text))
    except IOError:
        pass


LOG_MAX = 1000000     # the debug log is trimmed to its newest LOG_KEEP bytes
LOG_KEEP = 500000     # when it grows past LOG_MAX
TEXT_TAIL = 256000    # "Open as text" shows this much unless ?all


def trim_log():
    """Keep the debug log from growing without limit while recording.
    The hook opens the file for every line, so replacing it is safe."""
    try:
        if os.path.getsize(DTMF_LOG) <= LOG_MAX:
            return
        with open(DTMF_LOG, "rb") as f:
            f.seek(-LOG_KEEP, 2)
            data = f.read()
        data = data[data.find(b"\n") + 1:]      # start at a whole line
        tmp = DTMF_LOG + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.rename(tmp, DTMF_LOG)
    except (IOError, OSError):
        pass


def read_log(start):
    """New log text from byte offset start. If the log was cleared or
    restarted, everything is returned with reset=True."""
    try:
        with open(DTMF_LOG, "rb") as f:
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


# ----------------------------------------------------------- internet check

def check_internet():
    """Same idea as DreamPi's own check: reach public DNS servers over TCP,
    then resolve the Dreamcast Live host name."""
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
        socket.gethostbyname("dreamcast.online")
    except Exception:
        return {"state": "warn", "text": "Connected, but DNS lookups fail"}
    return {"state": "ok", "text": "Connected (%d ms)" % best}


def _sys(iface, name):
    return read_file("/sys/class/net/%s/%s" % (iface, name))


def link_state():
    """Which links are up, and whether there is a default route.
    Ethernet: a wired interface (eth*/en*) with carrier. Wi-Fi: a wireless
    interface (wlan*/wl*) that is up, i.e. associated with a network."""
    ethernet = wifi = False
    try:
        ifaces = os.listdir("/sys/class/net")
    except OSError:
        ifaces = []
    for iface in ifaces:
        up = _sys(iface, "operstate") == "up"
        if os.path.isdir("/sys/class/net/%s/wireless" % iface) or iface.startswith(("wlan", "wl")):
            wifi = wifi or up
        elif iface.startswith(("eth", "en")):
            ethernet = ethernet or (up and _sys(iface, "carrier") == "1")
    route = False
    try:
        with open("/proc/net/route") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) > 3 and parts[1] == "00000000" and int(parts[3], 16) & 1 \
                        and not parts[0].startswith(("ppp", "tun", "lo")):
                    route = True
    except (IOError, OSError, ValueError):
        pass
    # "network" = the Pi has a default route (a router to send traffic to)
    return {"ethernet": ethernet, "wifi": wifi, "network": route}


def network_state():
    """Latest link + internet state written by the web service, or None."""
    try:
        with open(NET_STATE) as f:
            data = json.load(f)
        if time.time() - data.get("time", 0) > NET_STALE:
            return None
        return data
    except (IOError, OSError, ValueError):
        return None


def wifi_state():
    """Latest Wi-Fi setup state written by netswitch_buttons.py: state (idle /
    scanning / hosting / connecting / ok / failed), ssid, networks (scan
    results while hosting) and time. {"state": "idle"} when the service
    hasn't run yet, or hasn't updated the file in a while (it isn't
    running any more, or crashed mid-setup)."""
    try:
        with open(WIFI_STATE) as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        return {"state": "idle"}
    if data.get("state", "idle") != "idle" and time.time() - data.get("time", 0) > WIFI_STALE:
        return {"state": "idle"}
    return data


def _write_net_state(data):
    tmp = NET_STATE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.rename(tmp, NET_STATE)
    except (IOError, OSError):
        pass


_net = {"links": None, "internet": {"state": "checking", "text": "Checking...", "time": 0},
        "recheck": threading.Event()}


def internet_checker():
    """Internet check: every 30 s while it works, every 5 s while it doesn't,
    and straight away when a cable or Wi-Fi connection changes."""
    while True:
        links = _net["links"]
        if links is not None and not links["network"]:
            result = {"state": "bad", "text": "No network connection"}
        else:
            result = check_internet()
        result["time"] = int(time.time())
        _net["internet"] = result
        _net["recheck"].clear()
        _net["recheck"].wait(INTERNET_EVERY if result["state"] == "ok" else INTERNET_RETRY)


# ------------------------------------------------------------- Pi health

THROTTLED_SYSFS = "/sys/devices/platform/soc/soc:firmware/get_throttled"
_cpu_prev = [None]
_throttle = {"value": None, "time": 0}


def _cpu_percent():
    """CPU use since the previous call, from /proc/stat."""
    try:
        with open("/proc/stat") as f:
            vals = [int(x) for x in f.readline().split()[1:9]]
    except (IOError, OSError, ValueError):
        return None
    idle, total = vals[3] + vals[4], sum(vals)
    prev, _cpu_prev[0] = _cpu_prev[0], (idle, total)
    if not prev or total == prev[1]:
        return None
    return 100.0 * (1 - float(idle - prev[0]) / (total - prev[1]))


def _meminfo():
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0])
    except (IOError, OSError, ValueError):
        return None
    avail = info.get("MemAvailable", info.get("MemFree", 0) + info.get("Cached", 0))
    return info.get("MemTotal", 0) // 1024, (info.get("MemTotal", 0) - avail) // 1024


def _temperature():
    raw = read_file("/sys/class/thermal/thermal_zone0/temp")
    try:
        return int(raw) / 1000.0
    except (TypeError, ValueError):
        return None


def _throttled():
    """The Pi firmware's power/heat flags (vcgencmd get_throttled), read at
    most every 10 s. None when not a Raspberry Pi or not available."""
    if time.time() - _throttle["time"] < 10:
        return _throttle["value"]
    value = None
    raw = read_file(THROTTLED_SYSFS)
    if raw is None:
        for cmd in ("vcgencmd", "/usr/bin/vcgencmd", "/opt/vc/bin/vcgencmd"):
            try:
                out = subprocess.check_output([cmd, "get_throttled"], stderr=subprocess.STDOUT)
                raw = out.decode("ascii", "replace").strip().split("=")[-1]
                break
            except (OSError, subprocess.CalledProcessError):
                continue
    try:
        value = int(raw, 16) if raw else None
    except ValueError:
        value = None
    _throttle.update(value=value, time=time.time())
    return value


def _duration(seconds):
    m = int(seconds) // 60
    if m < 60:
        return "%d min" % m
    h = m // 60
    return "%d h %d min" % (h, m % 60) if h < 24 else "%d d %d h" % (h // 24, h % 24)


def lan_ip():
    """The Pi's address on the home network (the one its default route
    uses; no packet is sent), or None."""
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


def pi_health():
    """CPU, RAM, temperature, uptime and the firmware's power/heat flags.
    state: ok / warn (something happened since boot, or warm) / bad (now)."""
    cpu, mem, temp, flags = _cpu_percent(), _meminfo(), _temperature(), _throttled()
    try:
        with open("/proc/uptime") as f:
            up = float(f.read().split()[0])
    except (IOError, OSError, ValueError):
        up = None
    parts = []
    if cpu is not None:
        parts.append("CPU %d%%" % round(cpu))
    if mem:
        parts.append("RAM %d/%dMB" % (mem[1], mem[0]))
    if temp is not None:
        parts.append("%.0f\u00b0C" % temp)
    details = []
    if up is not None:
        details.append("Uptime " + _duration(up))
    ip = lan_ip()
    details.append("IP: " + (ip or "none"))
    now, since = [], []
    if flags is not None:
        if flags & 0x1: now.append("under-voltage")
        if flags & 0x4: now.append("slowed down (throttled)")
        elif flags & 0x2: now.append("CPU speed capped")
        if flags & 0x10000 and not flags & 0x1: since.append("under-voltage")
        if flags & 0x40000 and not flags & 0x4: since.append("throttling")
    hot = temp is not None and temp >= 80
    warm = temp is not None and temp >= 70
    if hot and "slowed down (throttled)" not in now:
        now.append("very hot")
    elif warm and not hot:
        now.append("warm")
    state = "bad" if (flags is not None and flags & 0x5) or hot else \
        "warn" if now or since or warm else "ok"
    line1 = ", ".join(parts) or "Unknown"
    line2 = ", ".join(details)
    warn = []
    if now:
        warn.append("Now: " + ", ".join(now))
    if since:
        warn.append("Since boot: " + ", ".join(since))
    text = line1 + ". " + line2 + ("." if not warn else ". " + ". ".join(warn))
    return {"state": state, "text": text, "line1": line1, "line2": line2, "warn": ". ".join(warn), "ip": ip, "cpu": cpu, "ram": mem, "temp": temp, "uptime": up,
            "throttled": flags, "undervoltage": bool(flags is not None and flags & 0x1),
            "problem": state == "bad"}


# ------------------------------------------------------------ force hang up

_hangup = {"busy": False, "text": ""}
_hangup_lock = threading.Lock()
HANGUP_WAIT = 30      # seconds to wait for DreamPi to be ready before restarting it


def _run(cmd):
    try:
        return subprocess.call(cmd, stdout=subprocess.DEVNULL if hasattr(subprocess, "DEVNULL") else None,
                               stderr=subprocess.STDOUT)
    except OSError:
        return -1


def force_hangup():
    """End the current call the way DreamPi itself ends one, so it hangs up
    the modem and starts the dial tone again:
    - DCNow! (PPP): DreamPi waits for pppd to exit, then sends ATH0.
    - DCNET: netlink waits for dcnet.rpi to exit, then resets the modem.
    If DreamPi isn't ready for calls within HANGUP_WAIT seconds (or wasn't
    in a call at all, e.g. stuck), restart the dreampi service.
    Runs in its own thread; progress is shown on the page."""
    def say(text):
        _hangup["text"] = text
        debug_log("web page: " + text)
        sys.stderr.write("hang up: %s\n" % text)

    try:
        state = dreampi_state()[0]
        ended = []
        if _run(["pkill", "-TERM", "-x", "pppd"]) == 0:
            ended.append("pppd")
        if _run(["pkill", "-TERM", "-f", "dcnet.rpi"]) == 0:
            ended.append("dcnet.rpi")
        if ended:
            say("hanging up (ended %s), waiting for DreamPi" % " and ".join(ended))
            end = time.time() + HANGUP_WAIT
            while time.time() < end:
                time.sleep(1)
                if dreampi_state()[0] == "ok":
                    say("hung up, DreamPi is ready for calls")
                    return
            say("DreamPi didn't get ready, restarting it")
        else:
            say("the call seems stuck (no call process found), restarting DreamPi")
        rc = _run(["systemctl", "restart", "dreampi.service"])
        say("DreamPi restarted, it takes a few seconds to be ready" if rc == 0
            else "could not restart DreamPi (systemctl returned %s)" % rc)
    finally:
        time.sleep(5)
        _hangup["busy"] = False


def start_hangup():
    """Only while DreamPi is in a call (the button is hidden otherwise)."""
    if not dreampi_state()[0].startswith("call"):
        return False
    with _hangup_lock:
        if _hangup["busy"]:
            return False
        _hangup.update(busy=True, text="hanging up...")
    t = threading.Thread(target=force_hangup)
    t.daemon = True
    t.start()
    return True


# --------------------------------------------------------------- versions

DREAMPI_DIR = "/home/pi/dreampi"
ADDON_VERSION = os.path.join(BASE_DIR, "version")   # written by install.sh


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
    model = read_file("/proc/device-tree/model")
    osname = None
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    osname = line.split("=", 1)[1].strip().strip('"')
    except (IOError, OSError):
        pass
    rows = [("Add-on", read_file(ADDON_VERSION) or "unknown")]
    for name in ("dreampi.py", "netlink.py", "dcnow.py"):
        rows.append((name, script_version(os.path.join(DREAMPI_DIR, name)) or "not found"))
    rows.append(("Raspberry Pi", (model or "unknown").replace("\x00", "")))
    rows.append(("System", osname or "unknown"))
    usb = _usb_info(modem_port())
    compat, label = modem_compat(usb)
    if usb:
        text = label
        if compat is False:
            text += " — not known to work with DreamPi"
        elif compat is None:
            text += " — not a modem DreamPi is confirmed to work with yet"
        rows.append(("Modem", text))
    elif modem_plugged() is False:
        rows.append(("Modem", "Not detected (check the USB connection)"))
    return rows


# ----------------------------------------------------- modem identification
# Passive only: no AT commands, nothing is ever sent to the modem, and
# DreamPi is never stopped. An earlier version also actively probed the
# modem (ATI/AT+GM*) to show its firmware/revision, stopping and restarting
# DreamPi.service around it; on at least one real modem that got DreamPi
# stuck re-opening the serial port ("Opening modem on ..." never clearing)
# instead of completing, so it was removed. If that's revisited, it needs
# testing against real hardware first, not just the simulated port this
# was developed against.
MODEM_PORT = "/tmp/dreampi-netswitch.port"   # written by the hook

# Modems the DreamPi community has reported working, matched (case-
# insensitive) against the USB descriptor's manufacturer + product strings
# containing the known name (not the other way round - a short bad entry
# like "conceptronic c56u" must not match the good "conceptronic c56u-v2"
# as a prefix of it). Most share a Conexant CX93010 hardmodem chip, which
# the USB descriptor alone won't show. Source and more reports:
# https://www.segacity.de/viewtopic.php?t=7649 (a softmodem, which needs
# the host's own drivers to do part of the modem's job, is never a
# substitute: DreamPi needs the modem to handle the call by itself).
KNOWN_MODEMS = (
    "usrobotics 5637", "usr5637",
    "dell rd02-d400", "lenovo rd02-d400", "rd02-d400",
    "longshine lcs-8156c1",
    "trendnet tfm-561u",
    "zoom 3095",
    "startech usb56kemh",
    "conceptronic bvrp se", "conceptronic c56u-v2", "c56u-v2",
    "v.top um02", "vtop um02",
)
# Reported NOT to work: same case as the good ones above, but an older/
# different chip inside.
UNKNOWN_MODEMS = (
    "conceptronic c56u",   # the original, without "-v2"/"se"
)


def modem_port():
    return read_file(MODEM_PORT)


def _usb_info(port):
    """USB descriptor info for the serial port DreamPi opened (vendor,
    product, manufacturer and product strings, serial number), or None if
    it isn't known yet or isn't a USB device. Pure sysfs reads: never
    touches the modem itself."""
    if not port:
        return None
    try:
        iface = os.path.realpath("/sys/class/tty/%s/device" % os.path.basename(port))
        d = iface
        for _ in range(4):
            if os.path.isfile(os.path.join(d, "idVendor")):
                break
            d = os.path.dirname(d)
        else:
            return None
        vendor, product = read_file(os.path.join(d, "idVendor")), read_file(os.path.join(d, "idProduct"))
        if not vendor or not product:
            return None
        return {"vendor": vendor, "product": product,
                "manufacturer": read_file(os.path.join(d, "manufacturer")) or "",
                "product_name": read_file(os.path.join(d, "product")) or "",
                "serial": read_file(os.path.join(d, "serial")) or ""}
    except OSError:
        return None


def modem_plugged():
    """Whether the serial port DreamPi opened for the modem is present
    right now, or None while the port isn't known yet (DreamPi hasn't
    logged it, e.g. it hasn't started since the last reboot)."""
    port = modem_port()
    if not port:
        return None
    return os.path.exists(port)


def modem_compat(usb):
    """(compat, label). compat is True (known good), False (known not to
    work) or None (can't tell, or nothing plugged in). label is what to
    show for the modem's make/model."""
    if not usb:
        return None, None
    name = (usb.get("manufacturer", "") + " " + usb.get("product_name", "")).strip()
    label = name or "Unknown USB modem"
    low = name.lower()
    if low:
        # Only "descriptor contains the known name", not the other way round:
        # a bad entry like "conceptronic c56u" must not match the good
        # "conceptronic c56u-v2" just because it's a prefix of it.
        if any(good in low for good in KNOWN_MODEMS):
            return True, label
        if any(bad in low for bad in UNKNOWN_MODEMS):
            return False, label
    return None, label


def checker():
    """Cables / Wi-Fi / route every 2 s (cheap, so errors show quickly), and
    the shared state file for the LED service."""
    t = threading.Thread(target=internet_checker)
    t.daemon = True
    t.start()
    while True:
        links = link_state()
        if links != _net["links"]:           # plugged/unplugged, Wi-Fi joined/lost
            _net["links"] = links
            _net["recheck"].set()
        internet = _net["internet"]
        if not links["network"]:
            internet = {"state": "bad", "text": "No network connection", "time": int(time.time())}
        shown = dict(internet)
        if internet["state"] == "ok" and (links["ethernet"] or links["wifi"]):
            via = " and ".join(n for n, on in (("Ethernet", links["ethernet"]), ("Wi-Fi", links["wifi"])) if on)
            shown["text"] = internet["text"].replace("Connected", "Connected via " + via, 1)
        pi = pi_health()
        with _checks_lock:
            _checks["internet"] = shown
            _checks["pi"] = pi
        _write_net_state({"ethernet": links["ethernet"], "wifi": links["wifi"],
                          "network": links["network"], "pi_problem": pi["problem"],
                          "internet": None if internet["state"] == "checking" else internet["state"] == "ok",
                          "time": time.time()})
        trim_log()
        time.sleep(LINK_EVERY)


# -------------------------------------------------------------------- page

# DreamPi states (as returned by dreampi_state) in the order the settings show them
# LED messages, highest priority first, with category and default look.
# Errors always have higher priority than information. The DreamPi ones come from
# dreampi_state(); the network ones from the checker (NET_STATE).
LED_STATES = [
    # key, label, category, colour, effect, speed, enabled
    # Wi-Fi setup (netswitch_buttons.py) always outranks everything else: while
    # it's in progress "no network"/"no internet" are usually also true, and
    # would otherwise hide it. default_led_config() switches wifi-setup's
    # default effect to "scanner" when a strip is installed (breathe on a
    # single LED, see the user request); connecting keeps the same look.
    ("wifi-setup", "Wi-Fi setup: choose a network", "wifi", "#0046ff", "breathe", "slow", True),
    ("wifi-ok", "Wi-Fi setup: connected", "wifi", "#00ff00", "solid", "slow", True),
    ("wifi-failed", "Wi-Fi setup: couldn't connect", "wifi", "#ff0000", "blink", "slow", True),
    ("no-network", "No network", "error", "#ff0000", "solid", "slow", True),
    ("no-internet", "No internet", "error", "#ff7a00", "blink", "slow", True),
    ("pi", "Power or heat problem", "error", "#ff00aa", "breathe", "slow", True),
    ("off", "DreamPi not running", "error", "#ff0000", "blink", "slow", True),
    ("unknown", "State unknown", "error", "#3c3c3c", "solid", "slow", True),
    ("busy", "Starting up", "info", "#ffaa00", "blink", "slow", True),
    ("call-dcnow", "In a call on DCNow!", "info", "#ff5000", "solid", "slow", True),
    ("call-dcnet", "In a call on DCNET", "info", "#0046ff", "solid", "slow", True),
    ("call", "In another call (Netlink)", "info", "#aa00ff", "solid", "slow", True),
    ("ok", "Ready for calls", "info", "#00ff00", "solid", "slow", True),
    ("ethernet", "Ethernet connected", "info", "#ffffff", "solid", "slow", False),
    ("wifi", "Wi-Fi connected", "info", "#00c8ff", "solid", "slow", False),
]
PRIORITY = dict((s[0], len(LED_STATES) - i) for i, s in enumerate(LED_STATES))   # higher = more important
CATEGORY = dict((s[0], s[2]) for s in LED_STATES)
_DEFAULT_COLOURS = dict((s[0], s[3:7]) for s in LED_STATES)
# LED effects. The first four work on a single LED; the rest need a strip.
# "rgb" ignores the colour and cycles through all colours (20 s slow, 10 s fast).
EFFECTS = [
    ("solid", "Solid", False),
    ("blink", "Blink", False),
    ("breathe", "Breathe", False),
    ("rgb", "RGB", False),
    ("rainbow", "Rainbow", True),
    ("scanner", "Scanner", True),
    ("comet", "Comet", True),
    ("chase", "Chase", True),
    ("twinkle", "Twinkle", True),
]
EFFECT_NAMES = set(e[0] for e in EFFECTS)
SPEEDS = ("slow", "fast")


def led_count():
    """LEDs installed: 0 = no LED service, 1 = single LED, more = strip.
    Set at install time (install.sh --led=N) and editable from the page."""
    if not os.path.exists(LED_ENABLED):
        return 0
    try:
        return max(1, min(300, int((read_file(LED_COUNT) or "1").strip())))
    except ValueError:
        return 1


def save_led_count(n):
    try:
        n = max(1, min(300, int(n)))
    except (TypeError, ValueError):
        return
    tmp = LED_COUNT + ".tmp"
    with open(tmp, "w") as f:
        f.write(str(n))
    os.rename(tmp, LED_COUNT)


GPIO_PINS = (10, 12, 18, 21)   # allowed LED output pins; see netswitch_led.py for what each needs
DEFAULT_GPIO = 18


def led_gpio():
    try:
        n = int((read_file(LED_GPIO) or "").strip())
        return n if n in GPIO_PINS else DEFAULT_GPIO
    except ValueError:
        return DEFAULT_GPIO


def save_led_gpio(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return
    if n not in GPIO_PINS:
        return
    tmp = LED_GPIO + ".tmp"
    with open(tmp, "w") as f:
        f.write(str(n))
    os.rename(tmp, LED_GPIO)


def led_hidden():
    return os.path.exists(LED_HIDDEN)


# ------------------------------------------------------------------ buttons
# Up to two physical GPIO buttons (netswitch_buttons.py, always installed),
# each independently wired to a pin and a short-press function; which one
# (or both held together) triggers Wi-Fi setup on a 3-second hold is also
# configurable. Unlike the LED output pins, a button needs no special
# peripheral, so any header GPIO is allowed.
BUTTON1_GPIO = os.path.join(BASE_DIR, "button1_gpio")
BUTTON2_GPIO = os.path.join(BASE_DIR, "button2_gpio")
BUTTON1_FUNCTION = os.path.join(BASE_DIR, "button1_function")
BUTTON2_FUNCTION = os.path.join(BASE_DIR, "button2_function")
WIFI_BUTTON_FILE = os.path.join(BASE_DIR, "wifi_button")   # "1", "2" or "12": which button(s) hold-to-start Wi-Fi setup

BUTTON_GPIO_PINS = tuple(range(2, 28))   # BCM GPIO2-27 (0/1 are reserved for the ID EEPROM)
BUTTON_DEFAULT_GPIO1 = 17
BUTTON_DEFAULT_GPIO2 = 4
BUTTON_FUNCTIONS = (("off", "Off"), ("toggle", "Toggle network"),
                    ("dcnow", "Select DCNow!"), ("dcnet", "Select DCNET"))
_BUTTON_FUNCTION_NAMES = tuple(f[0] for f in BUTTON_FUNCTIONS)
BUTTON_DEFAULT_FUNCTION1 = "toggle"
BUTTON_DEFAULT_FUNCTION2 = "off"
WIFI_BUTTON_CHOICES = (("1", "Button 1"), ("2", "Button 2"), ("12", "Button 1 + 2"))
_WIFI_BUTTON_NAMES = tuple(c[0] for c in WIFI_BUTTON_CHOICES)
WIFI_BUTTON_DEFAULT = "1"


def button_gpio(which):
    """which: 1 or 2."""
    path = BUTTON1_GPIO if which == 1 else BUTTON2_GPIO
    default = BUTTON_DEFAULT_GPIO1 if which == 1 else BUTTON_DEFAULT_GPIO2
    try:
        n = int((read_file(path) or "").strip())
        return n if n in BUTTON_GPIO_PINS else default
    except ValueError:
        return default


def save_button_gpio(which, n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return
    if n not in BUTTON_GPIO_PINS:
        return
    path = BUTTON1_GPIO if which == 1 else BUTTON2_GPIO
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(str(n))
    os.rename(tmp, path)


def button_function(which):
    path = BUTTON1_FUNCTION if which == 1 else BUTTON2_FUNCTION
    default = BUTTON_DEFAULT_FUNCTION1 if which == 1 else BUTTON_DEFAULT_FUNCTION2
    v = (read_file(path) or "").strip()
    return v if v in _BUTTON_FUNCTION_NAMES else default


def save_button_function(which, v):
    if v not in _BUTTON_FUNCTION_NAMES:
        return
    path = BUTTON1_FUNCTION if which == 1 else BUTTON2_FUNCTION
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(v)
    os.rename(tmp, path)


def wifi_button():
    v = (read_file(WIFI_BUTTON_FILE) or "").strip()
    return v if v in _WIFI_BUTTON_NAMES else WIFI_BUTTON_DEFAULT


def save_wifi_button(v):
    if v not in _WIFI_BUTTON_NAMES:
        return
    tmp = WIFI_BUTTON_FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write(v)
    os.rename(tmp, WIFI_BUTTON_FILE)


NETWORKS = ("dcnow", "dcnet")
_COLOUR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
try:
    _TEXT = basestring  # noqa: F821  (Python 2: json gives unicode)
except NameError:
    _TEXT = str


LED_ORDERS = ("RGB", "RBG", "GRB", "GBR", "BRG", "BGR")   # wire order of the WS2812 strip; most are GRB

# Colour calibration: a simple NeoPixel-style white-balance pipeline, not a
# per-colour grid. netswitch_led.py applies, per channel and in this order:
# gamma correction (fixed, see GAMMA below) -> the white_balance multiplier
# -> max_brightness. White balance is found once, by eye, with the LED
# showing solid white (see WB_TEST below) and the R/G/B sliders nudging
# down whichever channel looks too strong; max_brightness is the familiar
# global brightness slider, renamed to make clear it's a ceiling applied
# after calibration, independent of the requested colour. GAMMA is stored
# for forward compatibility (a hand-edited led.json can tune it) but has no
# page control - 2.2 is a standard enough approximation of perceived
# brightness that it shouldn't need per-installation tuning.
GAMMA = 2.2


def default_led_config():
    cfg = {"max_brightness": 0.08, "order": "GRB", "gamma": GAMMA,
           "white_balance": {"r": 1.0, "g": 1.0, "b": 1.0},
           "colours": dict((net, dict((st, {"color": c, "effect": e, "speed": sp, "brightness": None,
                                            "enabled": on, "leds": None})
                                      for st, (c, e, sp, on) in _DEFAULT_COLOURS.items()))
                           for net in NETWORKS)}
    if led_count() > 1:   # a strip: scanning animation instead of a breathing single LED
        for net in NETWORKS:
            cfg["colours"][net]["wifi-setup"]["effect"] = "scanner"
    return cfg


def clean_led_config(data):
    """Defaults for anything missing or invalid in data."""
    cfg = default_led_config()
    if not isinstance(data, dict):
        return cfg
    try:
        cfg["max_brightness"] = min(1.0, max(0.0, float(data.get("max_brightness", cfg["max_brightness"]))))
    except (TypeError, ValueError):
        pass
    try:
        cfg["gamma"] = min(4.0, max(0.5, float(data.get("gamma", cfg["gamma"]))))
    except (TypeError, ValueError):
        pass
    if data.get("order") in LED_ORDERS:
        cfg["order"] = data["order"]
    wb = data.get("white_balance")
    if isinstance(wb, dict):
        for ch in ("r", "g", "b"):
            try:
                cfg["white_balance"][ch] = min(1.0, max(0.0, float(wb[ch])))
            except (TypeError, ValueError, KeyError):
                pass
    colours = data.get("colours")
    if isinstance(colours, dict):
        for net in NETWORKS:
            per_net = colours.get(net)
            if not isinstance(per_net, dict):
                continue
            for st in _DEFAULT_COLOURS:
                entry = per_net.get(st)
                if not isinstance(entry, dict):
                    continue
                if isinstance(entry.get("color"), _TEXT) and _COLOUR_RE.match(entry["color"]):
                    cfg["colours"][net][st]["color"] = entry["color"].lower()
                if entry.get("blink") is True and "effect" not in entry:   # older led.json
                    cfg["colours"][net][st]["effect"] = "blink"
                elif entry.get("blink") is False and "effect" not in entry:
                    cfg["colours"][net][st]["effect"] = "solid"
                if entry.get("effect") in EFFECT_NAMES:
                    cfg["colours"][net][st]["effect"] = str(entry["effect"])
                if entry.get("speed") in SPEEDS:
                    cfg["colours"][net][st]["speed"] = str(entry["speed"])
                if isinstance(entry.get("enabled"), bool):
                    cfg["colours"][net][st]["enabled"] = entry["enabled"]
                leds = entry.get("leds")   # None = all LEDs, else [first, last], 1-based
                if isinstance(leds, list) and len(leds) == 2 and \
                        all(isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 300 for x in leds):
                    cfg["colours"][net][st]["leds"] = [min(leds), max(leds)]
                level = entry.get("brightness")   # None = use the global brightness
                if isinstance(level, (int, float)) and not isinstance(level, bool):
                    cfg["colours"][net][st]["brightness"] = min(1.0, max(0.0, float(level)))
    return cfg


def led_config():
    try:
        with open(LED_CONFIG) as f:
            return clean_led_config(json.load(f))
    except (IOError, OSError, ValueError):
        return default_led_config()


def save_led_config(data):
    cfg = clean_led_config(data)
    tmp = LED_CONFIG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=1, sort_keys=True)
    os.rename(tmp, LED_CONFIG)   # the LED service never sees a half-written file
    return cfg


WB_TEST = "/tmp/dreampi-netswitch.wbtest"   # unix time, touched while the white-balance test is on
WB_TEST_STALE = 3   # seconds; a closed/crashed tab stops driving the LED after this


def wb_test_active():
    """True while the settings page wants the LED held at solid white (run
    through the normal calibration pipeline) for white-balance adjustment,
    instead of its usual status effects; False once the page stops saying
    so (closed, or went quiet - stale past WB_TEST_STALE)."""
    raw = read_file(WB_TEST)
    if not raw:
        return False
    try:
        return time.time() - float(raw) <= WB_TEST_STALE
    except ValueError:
        return False


def touch_wb_test():
    tmp = WB_TEST + ".tmp"
    with open(tmp, "w") as f:
        f.write("%f" % time.time())
    os.rename(tmp, WB_TEST)


def clear_wb_test():
    try:
        os.remove(WB_TEST)
    except OSError:
        pass


def active_messages(state=None, net_state=None, wifi=True):
    """Enabled LED messages that apply right now, lowest priority first (the
    LED service draws them in this order, so later ones end up on top).
    Each: key, category, color, effect, speed, brightness (effective), leds.
    wifi=False skips netswitch_buttons.py's state (used for the DreamPi dot
    preview, which only ever previews the DreamPi-state message)."""
    if state is None:
        state = dreampi_state()[0]
    if net_state is None:
        net_state = network_state()
    active = [state]
    if net_state:
        if not net_state.get("network"):
            active.append("no-network")
        elif net_state.get("internet") is False:
            active.append("no-internet")
        if net_state.get("pi_problem"):
            active.append("pi")
        if net_state.get("ethernet"):
            active.append("ethernet")
        if net_state.get("wifi"):
            active.append("wifi")
    if wifi:
        ws = wifi_state().get("state", "idle")
        if ws in ("scanning", "hosting", "connecting"):
            active.append("wifi-setup")
        elif ws == "ok":
            active.append("wifi-ok")
        elif ws == "failed":
            active.append("wifi-failed")
    cfg = led_config()
    looks = cfg["colours"]["dcnet" if os.path.exists(FLAG) else "dcnow"]
    out = []
    for key in sorted(set(active), key=lambda k: PRIORITY.get(k, 0)):
        if key not in looks or not looks[key].get("enabled", True):
            continue
        look = dict(looks[key])
        look["key"] = key
        look["category"] = CATEGORY.get(key, "info")
        if look.get("brightness") is None:
            look["brightness"] = cfg["max_brightness"]
        out.append(look)
    return out


def status_look(state=None):
    """The most important active message (what a single LED shows), or None
    when every active message is switched off."""
    msgs = active_messages(state)
    return msgs[-1] if msgs else None


def api_state():
    dstate, dtext = dreampi_state()
    mtext, msince = modem_state()
    warnings = []
    problem = hook_problem()
    if problem:
        warnings.append("Add-on not active: %s. Calls are not affected until it is." % problem)
    problem = dcnet_problem()
    if problem:
        warnings.append("DCNET unavailable: %s. All calls go to DCNow!" % problem)
    with _checks_lock:
        checks = json.loads(json.dumps(_checks))
    pi = checks.get("pi", {})
    if pi.get("undervoltage"):
        warnings.append("Power: the Pi is getting too little power (under-voltage). Use a stronger power "
                        "supply or a shorter, thicker cable; this can make the Pi unstable or drop off the network.")
    elif pi.get("problem"):
        warnings.append("Too hot: the Pi is at %.0f\u00b0C and slows itself down. Give it more air or a heatsink."
                        % (pi.get("temp") or 0))
    net = network_state()
    if net and not net.get("network"):
        warnings.append("No network: the Pi has no working network connection.")
    elif net and net.get("internet") is False:
        why = "name lookups (DNS) fail" if "DNS" in checks["internet"]["text"] \
            else "the network works, but the internet can't be reached"
        warnings.append("No internet: %s. Dreamcast games can't get online right now." % why)
    plugged = modem_plugged()
    compat, label = modem_compat(_usb_info(modem_port()))
    if plugged is False:
        warnings.append("Modem not detected: its USB serial port is gone. Check the cable/connection.")
    elif compat is False:
        warnings.append("Modem: %s is known not to work reliably with DreamPi. "
                        "See the Modem row in Settings." % label)
    wf = wifi_state()
    wf_state = wf.get("state", "idle")
    if wf_state in ("scanning", "hosting"):
        warnings.append("Wi-Fi setup: connect a phone or PC to the “%s” Wi-Fi network, then open "
                        "http://192.168.4.1 to pick a network." % WIFI_AP_SSID)
    elif wf_state == "connecting":
        warnings.append("Wi-Fi setup: trying to connect to “%s”..." % (wf.get("ssid") or ""))
    elif wf_state == "failed":
        warnings.append("Wi-Fi setup: could not connect (%s)." % (wf.get("ssid") or "unknown reason"))
    return {"network": "dcnet" if os.path.exists(FLAG) else "dcnow",
            "autoreset": os.path.exists(AUTORESET),
            "default": "dcnet" if os.path.exists(DEFAULT_DCNET) else "dcnow",
            "debug": os.path.exists(DEBUG_DTMF),
            # the dot next to DreamPi previews that status's LED message only;
            # network problems show as warning boxes instead
            "dreampi": {"state": dstate, "text": dtext,
                        "look": (active_messages(dstate, {"network": True}, wifi=False) or [None])[-1]},
            "modem": {"text": mtext, "since": msince, "plugged": plugged, "label": label, "compat": compat},
            "internet": checks["internet"],
            "pi": {"state": pi.get("state"), "text": pi.get("text"), "line1": pi.get("line1"),
                   "line2": pi.get("line2"), "warn": pi.get("warn")},
            "wifi": {"state": wf_state, "ssid": wf.get("ssid"), "networks": wf.get("networks"),
                     "installed": os.path.exists(WIFI_ENABLED)},
            "hangup": {"busy": _hangup["busy"], "text": _hangup["text"]},
            "warnings": warnings, "now": int(time.time())}


PAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "page")


def build_page():
    """The page is one document: page/index.html with page/page.css and
    page/page.js put in where it says @@CSS@@ and @@JS@@ (one request, kept in
    memory by PAGE_BYTES). Edit those three files, not this module."""
    def part(name):
        with io.open(os.path.join(PAGE_DIR, name), encoding="utf-8", newline="") as f:
            return f.read()
    return part("index.html").replace("@@CSS@@", part("page.css")).replace("@@JS@@", part("page.js"))


PAGE = build_page()


_gz_cache = {}   # (id, len) of an unchanging body -> gzipped bytes


def _gzip(body):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as z:
        z.write(body)
    return buf.getvalue()


PAGE_BYTES = PAGE.encode("utf-8")
_static_cache = {}


def _static(name):
    """A file from static/ (only those in STATIC_FILES), kept in memory."""
    if name not in STATIC_FILES:
        return None
    if name not in _static_cache:
        try:
            with open(os.path.join(STATIC_DIR, name), "rb") as f:
                _static_cache[name] = f.read()
        except (IOError, OSError):
            return None
    return _static_cache[name]


class Handler(BaseHTTPRequestHandler):
    timeout = 20          # a client that stops talking can't hold a thread forever

    def send(self, body, ctype, cache=None, status=200, fixed=False):
        """cache: seconds the browser may keep it (None = always ask again).
        fixed: the body never changes (page, static files), so its gzipped
        form is kept in memory instead of compressed for every request."""
        if not isinstance(body, bytes):
            body = body.encode("utf-8")
        gz = len(body) > 2000 and "gzip" in (self.headers.get("Accept-Encoding") or "")
        if gz:
            key = (id(body), len(body)) if fixed else None
            if key and key in _gz_cache:
                body = _gz_cache[key]
            else:
                packed = _gzip(body)
                if key:
                    _gz_cache[key] = packed
                body = packed
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if gz:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Cache-Control", "max-age=%d" % cache if cache else "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _safely(self, handler):
        """Run a request handler; an unexpected error answers 500 and is
        logged (journalctl -u dreampi-netswitch) instead of dropping the
        connection."""
        try:
            handler()
        except (socket.timeout, IOError, OSError) as e:
            if getattr(e, "errno", None) not in (32, 104, None) and not isinstance(e, socket.timeout):
                sys.stderr.write("request %s failed: %s\n" % (self.path, e))
        except Exception:
            sys.stderr.write("request %s failed:\n%s" % (self.path, traceback.format_exc()))
            try:
                self.send("Internal error, see journalctl -u dreampi-netswitch\n",
                          "text/plain; charset=utf-8", status=500)
            except Exception:
                pass

    def do_GET(self):
        self._safely(self._get)

    def do_POST(self):
        self._safely(self._post)

    def _get(self):
        if self.path == "/ping":
            self.send("ok\n", "text/plain")
        elif self.path == "/api":
            self.send(json.dumps(api_state()), "application/json")
        elif self.path.startswith("/log"):
            m = re.search(r"from=(-?\d+)", self.path)
            self.send(json.dumps(read_log(int(m.group(1)) if m else 0)), "application/json")
        elif self.path == "/status":
            d = api_state()
            self.send("network=%s\ndefault=%s\nautoreset=%s\ndreampi=%s\nmodem=%s\ninternet=%s\npi=%s\n" % (
                d["network"], d["default"], "on" if d["autoreset"] else "off", d["dreampi"]["text"],
                d["modem"]["text"], d["internet"]["text"], d["pi"]["text"]), "text/plain; charset=utf-8")
        elif self.path == "/about":
            self.send(json.dumps(about()), "application/json")
        elif self.path.startswith("/static/"):
            name = self.path[len("/static/"):].split("?")[0]
            body = _static(name)
            if body is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send(body, STATIC_FILES[name], cache=86400, fixed=True)
        elif self.path == "/ledconfig":
            self.send(json.dumps({"config": led_config(), "defaults": default_led_config(),
                                  "states": LED_STATES,
                                  "effects": EFFECTS, "orders": LED_ORDERS, "count": led_count(),
                                  "gpio": led_gpio(), "gpios": GPIO_PINS,
                                  "installed": os.path.exists(LED_ENABLED), "hidden": led_hidden()}),
                     "application/json")
        elif self.path == "/buttonconfig":
            self.send(json.dumps({"config": {"button1_gpio": button_gpio(1), "button2_gpio": button_gpio(2),
                                             "button1_function": button_function(1),
                                             "button2_function": button_function(2),
                                             "wifi_button": wifi_button()},
                                  "gpios": BUTTON_GPIO_PINS, "functions": BUTTON_FUNCTIONS,
                                  "wifi_choices": WIFI_BUTTON_CHOICES,
                                  "wifi": os.path.exists(WIFI_ENABLED)}),
                     "application/json")
        elif self.path.split("?")[0] == "/dtmf":
            try:
                with open(DTMF_LOG, "rb") as f:
                    f.seek(0, 2)
                    size = f.tell()
                    full = "all" in self.path.split("?", 1)[-1] if "?" in self.path else False
                    start = 0 if full or size <= TEXT_TAIL else size - TEXT_TAIL
                    f.seek(start)
                    body = f.read()
                if start:
                    body = body[body.find(b"\n") + 1:]   # start at a whole line
            except IOError:
                body = b"No debug log yet. Switch on Recording and dial.\n"
            self.send(body, "text/plain; charset=utf-8")
        else:
            self.send(PAGE_BYTES, "text/html; charset=utf-8", fixed=True)

    def _post(self):
        if self.path == "/ledconfig":
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 65536)
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                cfg = save_led_config(data)
                if "count" in data:
                    save_led_count(data["count"])
                if "gpio" in data:
                    save_led_gpio(data["gpio"])
            except (ValueError, IOError, OSError) as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(str(e).encode("utf-8"))
                return
            self.send(json.dumps({"config": cfg, "count": led_count(), "gpio": led_gpio()}),
                     "application/json")
            return
        if self.path == "/buttonconfig":
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 4096)
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, IOError, OSError) as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(str(e).encode("utf-8"))
                return
            try:
                g1, g2 = int(data["button1_gpio"]), int(data["button2_gpio"])
            except (KeyError, TypeError, ValueError):
                g1 = g2 = None
            if g1 is not None and g2 is not None and g1 != g2:   # reject if they'd collide on one pin
                save_button_gpio(1, g1)
                save_button_gpio(2, g2)
            if "button1_function" in data:
                save_button_function(1, data["button1_function"])
            if "button2_function" in data:
                save_button_function(2, data["button2_function"])
            if "wifi_button" in data:
                save_wifi_button(data["wifi_button"])
            self.send(json.dumps({"config": {"button1_gpio": button_gpio(1), "button2_gpio": button_gpio(2),
                                             "button1_function": button_function(1),
                                             "button2_function": button_function(2),
                                             "wifi_button": wifi_button()}}),
                     "application/json")
            return
        if self.path == "/ledhide":
            if os.path.exists(LED_HIDDEN):
                os.remove(LED_HIDDEN)
                debug_log("web page: LED settings shown again")
            else:
                open(LED_HIDDEN, "w").close()
                debug_log("web page: LED settings hidden")
        if self.path == "/wbtest":
            touch_wb_test()
        elif self.path == "/wbtestdone":
            clear_wb_test()
        if self.path == "/dcnet":
            open(FLAG, "w").close()
            debug_log("web page: DCNET selected")
        elif self.path == "/dcnow":
            if os.path.exists(FLAG):
                os.remove(FLAG)
            debug_log("web page: DCNow! selected")
        elif self.path == "/default":
            if os.path.exists(DEFAULT_DCNET):
                os.remove(DEFAULT_DCNET)
                debug_log("web page: default network set to DCNow!")
            else:
                open(DEFAULT_DCNET, "w").close()
                debug_log("web page: default network set to DCNET")
        elif self.path == "/autoreset":
            if os.path.exists(AUTORESET):
                os.remove(AUTORESET)
                debug_log("web page: reset on openMenu turned off")
            else:
                open(AUTORESET, "w").close()
                debug_log("web page: reset on openMenu turned on")
        elif self.path == "/debug":
            if os.path.exists(DEBUG_DTMF):
                debug_log("web page: debug log stopped")
                os.remove(DEBUG_DTMF)
            else:
                open(DEBUG_DTMF, "w").close()
                if os.path.exists(DTMF_LOG):
                    os.remove(DTMF_LOG)  # start a fresh log
                debug_log("web page: debug log started (network: %s)" %
                          ("DCNET" if os.path.exists(FLAG) else "DCNow!"))
        elif self.path == "/hangup":
            start_hangup()
        elif self.path == "/clearlog":
            if os.path.exists(DTMF_LOG):
                os.remove(DTMF_LOG)
            debug_log("web page: log cleared")
        elif self.path == "/wifitoggle":
            if os.path.exists(WIFI_ENABLED):
                if wifi_state().get("state", "idle") == "idle":
                    open(WIFI_START, "w").close()
                    debug_log("web page: Wi-Fi setup started")
                else:
                    open(WIFI_STOP, "w").close()
                    debug_log("web page: Wi-Fi setup stop requested")
        elif self.path == "/wificonnect":
            # An alternative to the setup access point's own /connect: lets
            # this page pick a network too, reachable while it's up over
            # Ethernet (or anything else besides the Wi-Fi being reconfigured).
            if os.path.exists(WIFI_ENABLED):
                ssid = ""
                try:
                    length = min(int(self.headers.get("Content-Length") or 0), 4096)
                    data = json.loads(self.rfile.read(length).decode("utf-8"))
                    ssid = str(data.get("ssid") or "").strip()
                    password = str(data.get("password") or "")
                except (ValueError, IOError, OSError):
                    pass
                if ssid:
                    tmp = WIFI_CONNECT + ".tmp"
                    with open(tmp, "w") as f:
                        json.dump({"ssid": ssid, "password": password}, f)
                    os.rename(tmp, WIFI_CONNECT)
                    debug_log("web page: Wi-Fi connect requested for %s" % ssid)
        if self.headers.get("X-Requested-With"):
            self.send_response(204)   # the page's own buttons: nothing to reload
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(303)  # back to the page when JavaScript is off
        self.send_header("Content-Length", "0")
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, *args):
        pass


class Server(ThreadingMixIn, HTTPServer):
    """One thread per request, so a slow client never blocks the page.
    Listens on IPv6 and IPv4 when it can: phones often try the IPv6 address
    of dreampi.local first, and an IPv4-only server makes them wait."""
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64   # browsers open several connections at once

    def __init__(self, address, handler, *args):
        if socket.has_ipv6 and address[0] == "":
            try:
                self.address_family = socket.AF_INET6
                HTTPServer.__init__(self, ("::", address[1]), handler)
                return
            except (socket.error, OSError, ValueError):
                self.address_family = socket.AF_INET
        HTTPServer.__init__(self, address, handler)

    def server_bind(self):
        if self.address_family == socket.AF_INET6:
            try:
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)   # IPv4 too
            except (AttributeError, socket.error, OSError):
                pass
        HTTPServer.server_bind(self)

    def server_name_lookup(self):
        return "dreampi"

    def handle_error(self, request, client_address):
        # dropped connections and rejected certificates are normal; log the rest
        err = sys.exc_info()[1]
        if isinstance(err, (socket.timeout, ssl.SSLError, IOError, OSError)):
            return
        sys.stderr.write("connection error:\n%s" % traceback.format_exc())


class HTTPSServer(Server):
    """Same page over HTTPS. The TLS handshake runs in the request's own
    thread, so a browser still showing the certificate warning can't stall
    other requests."""

    def __init__(self, address, handler, context):
        self.context = context
        Server.__init__(self, address, handler)

    def finish_request(self, request, client_address):
        request.settimeout(15)
        request = self.context.wrap_socket(request, server_side=True)
        Server.finish_request(self, request, client_address)


def start_https():
    if not HTTPS_PORT:
        return
    if not (os.path.exists(CERT) and os.path.exists(KEY)):
        sys.stderr.write("HTTPS off: no certificate at %s (run install.sh)\n" % CERT)
        return
    try:
        protocol = getattr(ssl, "PROTOCOL_TLS_SERVER", ssl.PROTOCOL_SSLv23)
        context = ssl.SSLContext(protocol)
        context.load_cert_chain(CERT, KEY)
        server = HTTPSServer(("", HTTPS_PORT), Handler, context)
    except Exception as e:   # port taken, bad certificate: keep plain HTTP running
        sys.stderr.write("HTTPS off: %s\n" % e)
        return
    t = threading.Thread(target=server.serve_forever)
    t.daemon = True
    t.start()


def watchdog():
    """If the page stops answering (should never happen), exit so systemd
    restarts the service within seconds instead of leaving it dead."""
    failures = 0
    time.sleep(30)
    while True:
        try:
            s = socket.create_connection(("127.0.0.1", PORT), 10)
            s.sendall(b"GET /ping HTTP/1.0\r\n\r\n")
            ok = s.recv(64).startswith(b"HTTP/1.0 200")
            s.close()
        except (socket.error, OSError):
            ok = False
        failures = 0 if ok else failures + 1
        if failures >= 3:
            sys.stderr.write("page not answering, restarting the service\n")
            os._exit(1)
        time.sleep(20)


if __name__ == "__main__":
    for target in (checker, watchdog):
        t = threading.Thread(target=target)
        t.daemon = True
        t.start()
    start_https()
    Server(("", PORT), Handler).serve_forever()
