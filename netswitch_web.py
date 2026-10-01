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
LED_CONFIG = os.path.join(BASE_DIR, "led.json")     # brightness, colours, wire order, calibration
LED_ENABLED = os.path.join(BASE_DIR, "led_enabled")  # written by install.sh --led
LED_COUNT = os.path.join(BASE_DIR, "led_count")      # number of LEDs, editable from the page
LED_GPIO = os.path.join(BASE_DIR, "led_gpio")        # output pin (10, 12, 18 or 21), likewise
LED_HIDDEN = os.path.join(BASE_DIR, "led_hidden")    # exists = LED settings hidden on the page
STATUS = "/tmp/dreampi-netswitch.active"
STATE = "/tmp/dreampi-netswitch.state"
MODEM = "/tmp/dreampi-netswitch.modem"
DTMF_LOG = "/tmp/dreampi-netswitch-dtmf.log"
# Wi-Fi setup (netswitch_wifi.py, install.sh --wifi)
WIFI_BUTTON_ENABLED = os.path.join(BASE_DIR, "wifi_button_enabled")  # written by install.sh
WIFI_START = os.path.join(BASE_DIR, "wifi_start")   # touched to ask netswitch_wifi.py to start
WIFI_STOP = os.path.join(BASE_DIR, "wifi_stop")     # touched to ask it to stop / cancel
WIFI_CONNECT = os.path.join(BASE_DIR, "wifi_connect")   # {"ssid":..., "password":...}, an alternative
                                                         # to the setup access point's own /connect -
                                                         # lets the regular page pick a network too,
                                                         # useful when it's reachable some other way
                                                         # (e.g. Ethernet) while Wi-Fi is being set up
WIFI_STATE = "/tmp/dreampi-netswitch.wifi"          # written by netswitch_wifi.py
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
    """Latest Wi-Fi setup state written by netswitch_wifi.py: state (idle /
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
    # Wi-Fi setup (netswitch_wifi.py) always outranks everything else: while
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
    Set at install time (install.sh --leds=N) and editable from the page."""
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
# Up to two physical GPIO buttons (netswitch_wifi.py, install.sh --wifi),
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

# Colour calibration: a 9 (hue) x 3 (lightness) grid of reference swatches.
# Calibrating a cell means the page found (by eye, sliding R/G/B while the
# LED shows the result live) which actual colour to send so the LED looks
# like that swatch; led.json keeps that colour, or null for an uncalibrated
# (identity) cell. netswitch_led.py turns the difference between a cell's
# swatch and its calibrated colour into a hue/lightness-interpolated
# correction applied to every colour the LEDs show - see calib_offset()
# there. Hues are plain HSL degrees, not evenly spaced (matching how the
# eye tells hues apart); "white" is the grey (zero-saturation) anchor every
# hue's correction is blended towards as saturation drops.
CALIB_HUES = (("red", 0), ("orange", 30), ("yellow", 60), ("green", 120),
             ("cyan", 180), ("blue", 240), ("purple", 270), ("magenta", 300))
CALIB_COLUMNS = tuple(name for name, _ in CALIB_HUES) + ("white",)
CALIB_ROWS = ("light", "medium", "dark")
CALIB_LIGHTNESS = {"light": 0.75, "medium": 0.5, "dark": 0.25}
_CALIB_HUE_DEG = dict(CALIB_HUES)


def calib_swatch(column, row):
    """The reference '#rrggbb' for one grid cell."""
    lightness = CALIB_LIGHTNESS[row]
    hue, sat = (0.0, 0.0) if column == "white" else (_CALIB_HUE_DEG[column] / 360.0, 1.0)
    r, g, b = colorsys.hls_to_rgb(hue, lightness, sat)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def default_led_config():
    cfg = {"brightness": 0.08, "order": "GRB",
           "calibrate": dict((col, dict((row, None) for row in CALIB_ROWS)) for col in CALIB_COLUMNS),
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
        cfg["brightness"] = min(1.0, max(0.0, float(data.get("brightness", cfg["brightness"]))))
    except (TypeError, ValueError):
        pass
    if data.get("order") in LED_ORDERS:
        cfg["order"] = data["order"]
    calibrate = data.get("calibrate")
    if isinstance(calibrate, dict):
        for col in CALIB_COLUMNS:
            cell = calibrate.get(col)
            if not isinstance(cell, dict):
                continue
            for row in CALIB_ROWS:
                v = cell.get(row)
                if isinstance(v, _TEXT) and _COLOUR_RE.match(v):
                    cfg["calibrate"][col][row] = v.lower()
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


CALIB_PREVIEW = "/tmp/dreampi-netswitch.calibpreview"   # live "#rrggbb" while matching a swatch
CALIB_PREVIEW_STALE = 3   # seconds; a closed/crashed tab stops driving the LED after this


def calib_preview():
    """(r, g, b) 0..255 the page wants the LED to show right now while the
    settings' colour calibration popup is open, or None (use the normal
    status effects) if nothing is being previewed or the page went quiet."""
    raw = read_file(CALIB_PREVIEW)
    if not raw:
        return None
    try:
        when, r, g, b = raw.split()
        if time.time() - float(when) > CALIB_PREVIEW_STALE:
            return None
        return tuple(max(0, min(255, int(v))) for v in (r, g, b))
    except ValueError:
        return None


def save_calib_preview(r, g, b):
    tmp = CALIB_PREVIEW + ".tmp"
    with open(tmp, "w") as f:
        f.write("%f %d %d %d" % (time.time(), r, g, b))
    os.rename(tmp, CALIB_PREVIEW)


def clear_calib_preview():
    try:
        os.remove(CALIB_PREVIEW)
    except OSError:
        pass


def active_messages(state=None, net_state=None, wifi=True):
    """Enabled LED messages that apply right now, lowest priority first (the
    LED service draws them in this order, so later ones end up on top).
    Each: key, category, color, effect, speed, brightness (effective), leds.
    wifi=False skips netswitch_wifi.py's state (used for the DreamPi dot
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
            look["brightness"] = cfg["brightness"]
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
                     "installed": os.path.exists(WIFI_BUTTON_ENABLED)},
            "hangup": {"busy": _hangup["busy"], "text": _hangup["text"]},
            "warnings": warnings, "now": int(time.time())}


PAGE = u"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DreamPi</title>
<link rel="icon" type="image/png" id="fav" href="/static/favicon-dcnow.png">
<link rel="apple-touch-icon" id="touch" href="/static/touch-dcnow.png">
<style>
 :root{--r:29px;--bw:4px;--dcnow:#e8761c;--dcnow-l:#f6b27a;--dcnet:#1c6fe8;--dcnet-l:#80b1f6;--card:#1b1b1b;--line:#2a2a2a;--muted:#999}
 *{box-sizing:border-box}
 body{font-family:-apple-system,"Segoe UI",Roboto,sans-serif;background:#111;color:#eee;max-width:460px;margin:24px auto;padding:0 16px}
 header{position:relative;margin-bottom:16px} h1{text-align:center;margin:0;font-size:1.9em}
 h2{font-size:.8em;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin:22px 4px 8px;font-weight:600}
 .card{background:var(--card);border-radius:var(--r);padding:6px 20px;margin-bottom:14px}
 .sub{color:#888;font-size:.85em} .note{color:var(--muted);font-size:.85em;margin:8px 4px} a{color:#8bf}
 button{font:inherit;cursor:pointer;border:0;color:#fff}
 .rows{cursor:pointer;user-select:none}
 .row{display:flex;align-items:baseline;padding:11px 0;border-top:1px solid var(--line)} .row:first-child{border-top:0}
 .row .k{width:84px;color:var(--muted);flex:none} .row .v{flex:1}
 .rows .more{display:none} .rows.open .more{display:flex}
 .arrow{color:#aaa;flex:none;margin-left:8px;transition:transform .15s} .rows.open .arrow{transform:rotate(90deg)}
 .dot{display:inline-block;width:.65em;height:.65em;border-radius:50%;margin-right:8px;background:#888}
 @keyframes blink{50%{opacity:.12}} @keyframes breathe{0%,100%{opacity:1}50%{opacity:.08}}
 @keyframes rgbc{0%,100%{background:#f00}17%{background:#ff0}33%{background:#0f0}50%{background:#0ff}67%{background:#00f}83%{background:#f0f}}
 .ok{background:#2c2} .busy,.warn{background:#e0b400} .call{background:#b04cff} .bad,.off{background:#d33}
 .call-dcnow{background:#ff7a1a} .call-dcnet{background:#2a7bff}
 .warnbox{background:#7a1f1f;border:var(--bw) solid #a84a4a;padding:10px 20px;border-radius:var(--r);margin:0 0 12px;font-size:.9em}
 .now{font-size:1.3em;margin:0 0 16px;padding:14px 24px;border-radius:var(--r);text-align:center;background:#9e4f10;border:var(--bw) solid #c9793a;line-height:1.35}
 .now b{font-size:1.25em;display:block} .now.dcnet{background:#1c4f9e;border-color:#5a86cf}
 /* status rows inside the network box: closed = just the DreamPi status,
    centred under the network name; open = all rows with their labels */
 .now .row{font-size:.62em;line-height:1.35;padding:9px 0;border-top:1px solid rgba(255,255,255,.18);text-align:left}
 .now .row.main{justify-content:center;border-top:0;padding:8px 0 2px}
 .now .row.main .k{display:none} .now .row.main .v{flex:none}
 .now .row .k{color:rgba(255,255,255,.65);width:68px} .now .row .v{min-width:0;display:flex;align-items:baseline} .now .row .v > .dot{flex:none} .now .row .v > span:last-child{min-width:0} .now .sub{color:rgba(255,255,255,.65)}
 .now .arrow{color:rgba(255,255,255,.7);font-size:.9em}
 .now .dot{box-shadow:0 0 0 2px rgba(255,255,255,.35)} .now .row.hang{justify-content:center;padding:12px 0 2px}
 .now .row.hang form{width:100%} .now .row.hang .pill-s{display:block;width:100%;padding:9px 12px;font-size:1em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .now .row.hang .pill-s{background:rgba(160,30,30,.85);border-color:rgba(230,110,110,.85)}
 .now .row.hang .pill-s.arm{background:#d33;border-color:#f99}
 .nw{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis} .sub.blk{display:block}
 .now.open .row.main{justify-content:flex-start;margin-top:10px;padding:9px 0;border-top:1px solid rgba(255,255,255,.18)}
 .now.open .row.main .k{display:block} .now.open .row.main .v{flex:1}
 .pill{display:block;width:100%;margin:0 0 12px;padding:13px;border-radius:var(--r);font-size:1.1em;font-weight:600;letter-spacing:.02em}
 .dcnow-b{background:rgba(232,118,28,.82);border:var(--bw) solid rgba(246,178,122,.82)} .dcnet-b{background:rgba(28,111,232,.82);border:var(--bw) solid rgba(128,177,246,.82)}
 .pill:active{filter:brightness(1.1)}
 .pill-s{display:inline-block;padding:7px 16px;border-radius:999px;background:rgba(42,42,42,.82);border:var(--bw) solid rgba(80,80,80,.85);color:#eee;font-size:.88em}
 .wide{display:flex;align-items:center;justify-content:space-between;width:100%;padding:12px 20px;border-radius:var(--r);background:var(--card);border:var(--bw) solid #3a3a3a;color:#eee;font-size:1em;text-align:left}
 .wide .arrow{margin-left:8px} .wide.open .arrow{transform:rotate(90deg)}
 .bar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:20px 0 0}
 .cog{position:absolute;right:0;top:50%;transform:translateY(-50%);padding:6px;background:transparent;color:#3a3a3a;line-height:0}
 .cog svg{width:30px;height:30px;fill:currentColor;display:block} .cog:hover{color:#5a5a5a}
 #settings{display:none;position:fixed;top:0;right:0;bottom:0;left:0;background:#111;overflow:auto;z-index:10}
 #settings.open{display:block} body.settings-open{overflow:hidden}
 #settings .in{max-width:460px;margin:24px auto;padding:0 16px 40px}
 .srow{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 0;border-top:1px solid var(--line);margin:0}
 .srow:first-child{border-top:0} .srow .sub{display:block;margin-top:2px}
 .switch{position:relative;flex:none;width:104px;height:40px;padding:0;border-radius:var(--r);font-size:.8em;font-weight:bold;
         background:rgba(232,118,28,.82);border:var(--bw) solid rgba(246,178,122,.82);transition:background .2s,border-color .2s}
 .switch .knob{position:absolute;top:4px;left:68px;width:24px;height:24px;border-radius:50%;background:#fff;transition:left .2s;box-shadow:0 1px 3px rgba(0,0,0,.5)}
 .switch .lbl{position:absolute;top:0;bottom:0;left:11px;line-height:32px}
 .switch.dcnet{background:rgba(28,111,232,.82);border-color:rgba(128,177,246,.82)} .switch.dcnet .knob{left:4px} .switch.dcnet .lbl{left:auto;right:12px}
 .cbox{-webkit-appearance:none;appearance:none;flex:none;display:inline-block;width:30px;height:30px;margin:0;padding:0;border-radius:8px;
       border:var(--bw) solid #777;background:transparent center/18px no-repeat;vertical-align:middle;cursor:pointer}
 .cbox.on,.cbox:checked{background-image:url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M5 12.5l4.5 4.5L19 7.5' fill='none' stroke='white' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E\")}
 .cbox.on.dcnow,.cbox.dcnow:checked{background-color:var(--dcnow);border-color:var(--dcnow)}
 .cbox.on.dcnet,.cbox.dcnet:checked{background-color:var(--dcnet);border-color:var(--dcnet)}
 table{width:100%;border-collapse:collapse;font-size:.88em}
 td,th{padding:10px 3px;border-top:1px solid var(--line);vertical-align:top;text-align:left;font-weight:normal}
 tr:first-child td{border-top:0}
 td.n{color:#eee;white-space:nowrap;word-break:keep-all;overflow-wrap:normal;width:1%;padding-right:14px}
 .ledtab td,.ledtab th{vertical-align:middle}
 .ledtab th{color:var(--muted);font-size:.78em;border-top:0;padding:4px 3px 8px;text-align:center} .ledtab th:first-child{text-align:left}
 .ledtab tbody tr:first-child td{border-top:1px solid var(--line)}
 .ledtab td.c{width:1%;padding:8px 4px;text-align:center}
 .tabs{display:flex;gap:8px;padding:10px 0 4px} .tabs button{flex:1;padding:7px 4px;font-size:.85em}
 .tabs .sel.dcnow{background:rgba(232,118,28,.82);border-color:rgba(246,178,122,.82)} .tabs .sel.dcnet{background:rgba(28,111,232,.82);border-color:rgba(128,177,246,.82)}
 .chip{display:inline-block;height:34px;padding:0 4px;border-radius:7px;border:var(--bw) solid #555;background:transparent;color:#ccc;font-size:.72em;line-height:1.1;vertical-align:middle}
 .fx{width:74px} .fx small{display:block;color:#888;font-size:.9em} .lvl{width:52px;color:#777}
 .ledtab td.name{padding-left:0} .ledtab td.name .cbox{margin-right:8px}
 .ledtab tr.grp td{border-top:0;padding:14px 0 4px;color:var(--muted);font-size:.72em;text-transform:uppercase;letter-spacing:.08em}
 .ledtab tr.dis td:not(.name),.ledtab tr.dis .lbl-t{opacity:.35}
 .secrow{display:flex;align-items:center;gap:8px;margin-bottom:12px;flex-wrap:wrap}
 .secrow input[type=number],.srow input[type=number]{width:54px;padding:5px 6px;border-radius:8px;border:var(--bw) solid #555;background:#1a1a1a;color:#eee;font:inherit;font-size:.85em}
 select.ord{padding:5px 6px;border-radius:8px;border:var(--bw) solid #555;background:#1a1a1a;color:#eee;font:inherit;font-size:.85em}
 .calib-grid{display:flex;flex-direction:column;gap:6px}
 .calib-row{display:flex;gap:6px}
 .calib-sw{flex:1;aspect-ratio:1;min-width:0;padding:0;border-radius:8px;border:var(--bw) solid rgba(255,255,255,.28);position:relative}
 .calib-sw.done::after{content:"";position:absolute;right:3px;bottom:3px;width:7px;height:7px;border-radius:50%;background:#fff;box-shadow:0 0 0 2px rgba(0,0,0,.45)}
 .calib-swatches{display:flex;gap:10px;margin-bottom:4px}
 .calib-sq{width:36px;height:36px;border-radius:8px;border:var(--bw) solid #555}
 .lvl.on.dcnow{background:var(--dcnow);border-color:var(--dcnow);color:#fff} .lvl.on.dcnet{background:var(--dcnet);border-color:var(--dcnet);color:#fff}
 .in{position:relative}
 .pop{display:none;position:absolute;z-index:20;width:290px;padding:12px 16px;border-radius:var(--r);background:#262626;box-shadow:0 6px 24px rgba(0,0,0,.6)}
 .pop.open{display:block} .pop .t{font-size:.85em;color:#ccc;margin-bottom:8px}
 .pop .range{padding:6px 0 10px} .pop .bar{margin:0;justify-content:space-between}
 .opts{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px} .opts button{padding:6px 12px;font-size:.82em}
 .opts .sel.dcnow,.secrow .sel.dcnow{background:var(--dcnow);border-color:var(--dcnow-l)} .opts .sel.dcnet,.secrow .sel.dcnet{background:var(--dcnet);border-color:var(--dcnet-l)}
 .opts button:disabled{opacity:.35;cursor:default}
 .th-dcnow{color:var(--dcnow-l)!important} .th-dcnet{color:var(--dcnet-l)!important}
 input[type=color]{-webkit-appearance:none;appearance:none;width:34px;height:34px;padding:0;border:var(--bw) solid #555;border-radius:7px;background:none;vertical-align:middle;cursor:pointer}
 input[type=color]::-webkit-color-swatch-wrapper{padding:0} input[type=color]::-webkit-color-swatch{border:0;border-radius:4px}
 input[type=color]::-moz-color-swatch{border:0;border-radius:4px}
 input[type=password],input[type=text]{width:100%;padding:10px 12px;margin:0 0 10px;border-radius:12px;border:var(--bw) solid #555;background:#1a1a1a;color:#eee;font:inherit;font-size:.9em}
 #wifi-networks{padding:10px 0 14px}
 .wnet{display:block;width:100%;margin-bottom:6px;padding:9px 12px;text-align:left;border-radius:12px;background:rgba(42,42,42,.82);border:var(--bw) solid rgba(80,80,80,.85);color:#eee;font-size:.88em}
 .wnet .sig{float:right;opacity:.6;font-size:.85em}
 .range{display:flex;align-items:center;gap:12px;padding:12px 0} .range > span:first-child{white-space:nowrap} .range input{flex:1;min-width:60px;accent-color:var(--dcnow)}
 .saved{color:#6c6;font-size:1em;text-transform:none;letter-spacing:0;margin-left:8px;opacity:0;transition:opacity .3s} .saved.show{opacity:1}
 #log{background:#0a0a0a;border:var(--bw) solid var(--line);border-radius:12px;padding:8px;font-size:11px;line-height:1.45;
      height:55vh;overflow:auto;white-space:pre-wrap;word-break:break-all;margin-top:12px}
 #log .dtmf{color:#6f6;font-weight:bold} #log .route{color:#8bf} #log .web{color:#e0b400}
 #log .modem{color:#aaa} #log .dim{color:#555} #log .err{color:#f66}
 #dcbg{display:none;position:fixed;top:0;left:0;width:100vw;height:100vh;height:100lvh;z-index:-1;overflow:hidden;pointer-events:none;
       background:linear-gradient(to bottom,#9cc3dc,#4d639c);transform:translateZ(0)}
 body.dcbg #dcbg{display:block} body.dcbg{background:transparent} html.dcbg{background:#4d639c}
 body.dcbg{--card:rgba(20,20,20,.78)} body.dcbg .wide{background:rgba(20,20,20,.78)}
 body.dcbg .now,body.dcbg .now.dcnet{background:rgba(20,20,20,.78)}   /* grey like the Dreamcast BIOS pop-ups; the border keeps the network colour */
 body.dcbg h1{text-shadow:0 1px 4px rgba(0,0,0,.6)}
 body.settings-open > :not(#settings):not(#dcbg){visibility:hidden}
 body.dcbg #settings{background:transparent}
 body.dcbg .note,body.dcbg h2{color:#eee;text-shadow:0 1px 3px rgba(0,0,0,.8)}
</style></head><body>
<div id="dcbg"></div>
<header><h1>DreamPi</h1><button class="cog" id="cog" type="button" title="Settings" aria-label="Settings"><svg viewBox="0 0 24 24" aria-hidden="true"><path fill-rule="evenodd" d="M10.3 1.5h3.4l.5 2.6a8.3 8.3 0 0 1 2.1.9l2.2-1.5 2.4 2.4-1.5 2.2c.4.7.7 1.4.9 2.1l2.6.5v3.4l-2.6.5a8.3 8.3 0 0 1-.9 2.1l1.5 2.2-2.4 2.4-2.2-1.5c-.7.4-1.4.7-2.1.9l-.5 2.6h-3.4l-.5-2.6a8.3 8.3 0 0 1-2.1-.9l-2.2 1.5-2.4-2.4 1.5-2.2a8.3 8.3 0 0 1-.9-2.1l-2.6-.5v-3.4l2.6-.5c.2-.7.5-1.4.9-2.1L3.4 5.9l2.4-2.4L8 5c.7-.4 1.4-.7 2.1-.9zM12 8.2a3.8 3.8 0 1 0 0 7.6 3.8 3.8 0 0 0 0-7.6z"/></svg></button></header>
<div id="warnings"></div>
<div class="now rows" id="net" title="Show or hide details">
 <div class="nlabel">Selected network:</div><b id="net-name">...</b>
 <div class="row main"><span class="k">DreamPi</span><span class="v"><span class="dot" id="d-dot"></span><span id="d-text">...</span></span><span class="arrow">&#9656;</span></div>
 <div class="row more"><span class="k">Modem</span><span class="v"><span><span class="nw" id="m-text">...</span><span class="sub blk" id="m-since"></span></span></span></div>
 <div class="row more"><span class="k">Internet</span><span class="v"><span class="dot" id="i-dot"></span><span id="i-text">...</span></span></div>
 <div class="row more"><span class="k">Pi</span><span class="v"><span class="dot" id="p-dot"></span><span id="p-text">...</span></span></div>
 <div class="row more hang" id="hang-row" style="display:none"><form method="post" action="/hangup" id="hang-f"><button class="pill-s" id="hang-b" type="submit"
  title="Ends the current call and gets the modem ready again">Hang up</button></form></div>
</div>
<form method="post" action="/dcnow"><button class="pill dcnow-b">DCNow! / DreamPi</button></form>
<form method="post" action="/dcnet"><button class="pill dcnet-b">DCNET / FLYCAST</button></form>
<div class="bar" id="debug-bar" style="display:none"><button class="wide" id="show-debug" type="button"><span>Debug log</span><span class="arrow">&#9656;</span></button></div>
<div id="debug" style="display:none">
<div class="note">Records every modem event, DreamPi message and routing decision with
millisecond timing. Turn recording on, then dial.</div>
<div class="bar" style="margin-top:6px"><form method="post" action="/debug"><button class="pill-s" id="debug-b">Recording</button></form>
<span id="log-tools" style="display:none"><form method="post" action="/clearlog" style="display:inline"><button class="pill-s">Clear</button></form>
<a class="pill-s" href="/dtmf" target="_blank" style="text-decoration:none">Newest 256 KB</a>
<a class="pill-s" href="/dtmf?all" target="_blank" style="text-decoration:none">Full log</a>
<label class="sub" style="display:inline-flex;align-items:center;gap:6px;white-space:nowrap;margin-left:4px"><input type="checkbox" class="cbox dcnow" id="follow" checked>Follow</label></span></div>
<pre id="log" style="display:none"></pre>
</div>

<div id="settings" role="dialog" aria-label="Settings"><div class="in">
<header><h1>Settings</h1><button class="cog" id="close-settings" type="button" title="Close" aria-label="Close"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5.6 3.5 12 9.9l6.4-6.4 2.1 2.1-6.4 6.4 6.4 6.4-2.1 2.1-6.4-6.4-6.4 6.4-2.1-2.1 6.4-6.4-6.4-6.4z"/></svg></button></header>
<h2>Network</h2>
<div class="card">
 <form method="post" action="/default" class="srow"><span>Default network<span class="sub">Where Auto reset goes back to</span></span>
  <button class="switch" id="default-b" type="submit"><span class="lbl" id="default-l">DCNow!</span><span class="knob"></span></button></form>
 <form method="post" action="/autoreset" class="srow"><span>Auto reset<span class="sub">Dialing 111-1111 returns to the default network</span></span>
  <button class="cbox" id="reset-b" type="submit" aria-label="Auto reset"></button></form>
 <div class="srow"><span>Debug log<span class="sub">Show the debug log on the main page (this browser only)</span></span>
  <input type="checkbox" class="cbox dcnow" id="dbg-b" aria-label="Show debug log"></div>
 <div class="srow" id="wifi-row" style="display:none"><span>Wi-Fi setup<span class="sub" id="wifi-sub">Search for a Wi-Fi network to connect the Pi to</span></span>
  <button class="pill-s" id="wifi-b" type="button">Search</button></div>
 <div id="wifi-networks" style="display:none">
  <div id="wifi-list"></div>
  <button type="button" class="pill-s" id="wifi-manual" style="margin-bottom:10px">Enter a network name manually</button>
  <div id="wifi-form" style="display:none">
   <input type="text" id="wifi-ssid" placeholder="Network name" readonly>
   <input type="password" id="wifi-pass" placeholder="Password" style="display:none">
   <button type="button" class="pill-s" id="wifi-connect-b" disabled>Connect</button>
  </div>
 </div>
</div>

<h2>Phone numbers</h2>
<div class="card">
<table>
<tr><td class="n">111-1111</td><td>Always directs to DCNow! for compatibility with openMenu and standard ISP configs.<br>
<span class="sub">When &quot;Auto reset&quot; is enabled, dialing it also resets the network to the default network.<span id="reset-note"></span></span></td></tr>
<tr><td class="n">555-0001</td><td>Selects DCNow! / DreamPi and connects to it<br>
<span class="sub">Can be set in the Dreamcast ISP config to always connect to DCNow!</span></td></tr>
<tr><td class="n">555-0002</td><td>Selects DCNET / FLYCAST and connects to it<br>
<span class="sub">Can be set in the Dreamcast ISP config to always connect to DCNET.</span></td></tr>
<tr><td class="n">Any other</td><td>Connects to the currently selected network.<br>
<span class="sub">Set your Dreamcast ISP config to any 7-digit number to use this feature.</span></td></tr>
</table>
</div>

<h2>Appearance</h2>
<div class="card">
 <div class="srow"><span>Dreamcast background<span class="sub">Animated, saved in this browser only</span></span>
  <input type="checkbox" class="cbox dcnow" id="bg-b" aria-label="Dreamcast background"></div>
</div>

<div id="gpio-section" style="display:none;position:relative">
<h2>GPIO <span class="saved" id="gpio-saved">Saved &#10003;</span></h2>
<div class="card">
 <div class="srow" id="gpio-led-row" style="display:none"><span>LED<span class="sub">LEDs connected, output pin and wire order</span></span>
  <div style="display:flex;gap:8px"><input type="number" id="led-count-i" min="1" max="300" aria-label="LEDs connected"><select class="ord" id="led-gpio" aria-label="LED output pin"></select><select class="ord" id="led-order" aria-label="Wire order"></select></div></div>
 <div class="srow" id="gpio-btn1-row" style="display:none"><span>Button 1<span class="sub">Function and pin</span></span>
  <div style="display:flex;gap:8px"><select class="ord" id="btn1-fn" aria-label="Button 1 function"></select><select class="ord" id="btn1-gpio" aria-label="Button 1 pin"></select></div></div>
 <div class="srow" id="gpio-btn2-row" style="display:none"><span>Button 2<span class="sub">Function and pin</span></span>
  <div style="display:flex;gap:8px"><select class="ord" id="btn2-fn" aria-label="Button 2 function"></select><select class="ord" id="btn2-gpio" aria-label="Button 2 pin"></select></div></div>
 <div class="srow" id="gpio-wifi-row" style="display:none"><span>Wi-Fi setup<span class="sub">Which button (or both) starts it</span></span>
  <select class="ord" id="wifi-btn-sel" aria-label="Wi-Fi setup button"></select></div>
</div>
<div class="note">LED count, output pin and wire order (most WS2812 strips are GRB) take effect within a second; switching the LED output pin to GPIO10 only works if SPI was enabled when installing (<code>sudo ./install.sh --led-gpio=10</code>, needs a reboot). Button pin and function changes take effect within a couple of seconds - pick two different pins for the two buttons. A button's own function (Off, Toggle network, Select DCNow!, Select DCNET) fires on a short press; "Wi-Fi setup" is which button, or both held together, starts Wi-Fi setup with a 3-second hold.</div>
</div>

<div id="led-section" style="display:none;position:relative">
<h2>Status LED<span id="led-count-t"></span> <span class="saved" id="led-saved">Saved &#10003;</span></h2>
<div class="card">
 <div class="calib-grid" id="calib-grid"></div>
</div>
<div class="note">Colour calibration: tap a swatch, then move the sliders until the LED (it shows them live) matches the swatch as closely as you can, and tap Done. A dot marks swatches you've matched; every other colour the LEDs show blends the nearest ones. Fixes a wrong-looking hue as well as washing out at high brightness, not just overall brightness.</div>
<div class="card">
 <div class="range"><span>Global brightness</span><input type="range" id="led-bright" min="0" max="1000" step="1"><span id="led-bright-v" style="width:3em;text-align:right"></span></div>
 <div class="tabs"><button class="pill-s" type="button" id="tab-dcnow">DCNow! selected</button><button class="pill-s" type="button" id="tab-dcnet">DCNET selected</button></div>
 <table class="ledtab"><thead><tr><th>Message</th><th>colour</th><th>effect</th><th>level</th></tr></thead><tbody id="led-rows"></tbody></table>
</div>
<div class="bar" style="margin-top:0"><button class="pill-s" id="led-reset" type="button">Reset LED settings to defaults</button></div>
<div class="note">The tabs choose which selected network the table is for. Tick a message to use it; the LED is off when no ticked message applies. Errors always have higher priority than information. Effect: tap to pick solid, blink, breathe, RGB or (with a strip) an animation, its speed, and with a strip which LEDs it uses (later messages in the list draw underneath earlier ones). Level: its own brightness; grey means the global brightness above. The status dot on the main page previews the most important message.</div>
<div class="card">
 <div class="srow"><span>Hide these settings<span class="sub">Removes this Status LED section from Settings; only reversible by deleting led_hidden in /opt/dreampi-netswitch</span></span>
  <button class="pill-s" id="led-hide-b" type="button">Hide</button></div>
</div>
<div id="fx-pop" class="pop"><div class="t" id="fx-t"></div>
 <div class="opts" id="fx-opts"></div>
 <div class="opts" id="fx-speed" style="align-items:center"><span class="sub" style="margin-right:4px">Speed</span><button class="pill-s" type="button" data-speed="slow">Slow</button><button class="pill-s" type="button" data-speed="fast">Fast</button></div>
 <div class="secrow" id="fx-sec"><span class="sub">LEDs</span>
  <button class="pill-s" type="button" id="sec-all">All</button>
  <input type="number" id="sec-a" min="1" max="300" aria-label="First LED"><span class="sub">to</span><input type="number" id="sec-b" min="1" max="300" aria-label="Last LED"></div>
 <div class="bar" style="justify-content:flex-end"><button class="pill-s" id="fx-done" type="button">Done</button></div></div>
<div id="lvl-pop" class="pop"><div class="t" id="lvl-t"></div>
 <div class="range"><input type="range" id="lvl-r" min="0" max="1000" step="1"><span id="lvl-v" style="width:3em;text-align:right"></span></div>
 <div class="bar"><button class="pill-s" id="lvl-base" type="button">Use global</button><button class="pill-s" id="lvl-done" type="button">Done</button></div></div>
<div id="calib-pop" class="pop"><div class="t" id="calib-t"></div>
 <div class="calib-swatches"><span class="calib-sq" id="calib-ref" title="Swatch"></span><span class="calib-sq" id="calib-live" title="Your sliders"></span></div>
 <div class="range"><span>R</span><input type="range" id="calib-r" min="0" max="255" step="1" style="accent-color:#f33"><span id="calib-r-v" style="width:2.5em;text-align:right"></span></div>
 <div class="range"><span>G</span><input type="range" id="calib-g" min="0" max="255" step="1" style="accent-color:#3f3"><span id="calib-g-v" style="width:2.5em;text-align:right"></span></div>
 <div class="range"><span>B</span><input type="range" id="calib-b" min="0" max="255" step="1" style="accent-color:#39f"><span id="calib-b-v" style="width:2.5em;text-align:right"></span></div>
 <div class="bar"><button class="pill-s" id="calib-reset" type="button">Reset</button><button class="pill-s" id="calib-done" type="button">Done</button></div></div>
</div>
<h2>About</h2>
<div class="card"><table class="about" id="about"></table></div>
<div class="note">The DreamPi script versions are the dates DreamPi's own auto-update compares.</div>
</div></div>

<script>
function $(id){return document.getElementById(id)}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function ago(t,now){if(!t)return"";var s=Math.max(0,now-t);
 if(s<60)return"("+s+"s ago)";if(s<3600)return"("+Math.floor(s/60)+" min ago)";return"("+Math.floor(s/3600)+" h ago)"}
function dot(el,state){el.className="dot "+(state||"")}
// Status dot preview of the LED effect: [keyframes, slow s, fast s, timing]
var DOT_FX={blink:["blink",1,.4,"steps(1)"],breathe:["breathe",4,1.6,"ease-in-out"],rgb:["rgbc",20,10,"linear"],
 rainbow:["rgbc",20,10,"linear"],scanner:["breathe",3,1.2,"ease-in-out"],comet:["breathe",3,1.2,"ease-in-out"],
 chase:["blink",.6,.24,"steps(1)"],twinkle:["breathe",3,1.2,"ease-in-out"]};
function lookDot(el,look){if(!look){el.className="dot";el.style.background="#333";el.style.animation="none";return}
 var f=DOT_FX[look.effect];el.className="dot";el.style.background=look.color;
 el.style.animation=f?f[0]+" "+(look.speed=="fast"?f[2]:f[1])+"s "+f[3]+" infinite":"none"}
var favNet="dcnow";
function render(d){
 // Hang up only while in a call (or while a hang up is still running)
 $("hang-row").style.display=(d.dreampi.state.indexOf("call")==0||(d.hangup&&d.hangup.busy))?"":"none";
 if(d.hangup){var hb=$("hang-b");
  if(d.hangup.busy){hb.disabled=true;hb.className="pill-s";
   hb.textContent=d.hangup.text?d.hangup.text.charAt(0).toUpperCase()+d.hangup.text.slice(1):"Hanging up..."}
  else if(hb.disabled){hb.disabled=false;hb.textContent="Hang up"}}
 $("warnings").innerHTML=d.warnings.map(function(w){return '<div class="warnbox">'+esc(w)+'</div>'}).join("");
 lookDot($("d-dot"),d.dreampi.look); $("d-text").textContent=d.dreampi.text;
 $("m-text").textContent=d.modem.text; $("m-since").textContent=ago(d.modem.since,d.now).replace(/[()]/g,"");
 dot($("i-dot"),d.internet.state); $("i-text").textContent=d.internet.text;
 dot($("p-dot"),d.pi.state);
 $("p-text").innerHTML=d.pi.line1?'<span class="nw">'+esc(d.pi.line1)+'</span><span class="sub blk">'+esc(d.pi.line2)+
  (d.pi.warn?'<br>'+esc(d.pi.warn):'')+'</span>':esc(d.pi.text||"...");
 $("net").className="now rows "+d.network+($("net").classList.contains("open")?" open":"");
 if(d.network!=favNet){favNet=d.network;$("fav").href="/static/favicon-"+d.network+".png";$("touch").href="/static/touch-"+d.network+".png"} $("net-name").textContent=d.network=="dcnet"?"DCNET":"DCNow!";
 var defName=d.default=="dcnet"?"DCNET":"DCNow!";
 $("default-b").className="switch "+d.default; $("default-l").textContent=d.default=="dcnet"?"DCNET":"DCNow!";
 $("reset-b").className="cbox "+d.default+(d.autoreset?" on":"");
 $("reset-note").textContent=" (Auto reset is "+(d.autoreset?"on, default: "+defName:"off")+")";
 $("debug-b").innerHTML=(d.debug?"&#9679; Recording":"Recording off");
 $("log-tools").style.display=d.debug?"inline":"none";
 $("log").style.display=(d.debug||logSize)?"block":"none";
 debugOn=d.debug;
 $("wifi-row").style.display=d.wifi.installed?"flex":"none";
 var wl=WIFI_LABELS[d.wifi.state]||WIFI_LABELS.idle;
 $("wifi-b").textContent=wl[0];
 $("wifi-sub").textContent=wl[1].replace("%s",d.wifi.ssid||"");
 $("wifi-b").disabled=d.wifi.state=="ok";
 var showNets=d.wifi.state=="hosting"||d.wifi.state=="scanning";
 $("wifi-networks").style.display=showNets?"block":"none";
 if(showNets&&d.wifi.networks){var key=JSON.stringify(d.wifi.networks);
  if(key!=wifiListKey){wifiListKey=key;renderWifiList(d.wifi.networks)}}
 else if(!showNets){wifiListKey=null;wifiChosen=null;$("wifi-form").style.display="none";$("wifi-list").innerHTML=""}
}
var WIFI_LABELS={
 idle:["Search","Search for a Wi-Fi network to connect the Pi to"],
 scanning:["Stop","Scanning for Wi-Fi networks..."],
 hosting:["Stop","Pick a network below, or connect to “DreamPi WiFi Config” and open http://192.168.4.1"],
 connecting:["Stop","Connecting to “%s”..."],
 ok:["Connected","Connected to “%s”"],
 failed:["Stop","Couldn't connect (%s)"]};
$("wifi-b").onclick=function(){
 var x=new XMLHttpRequest();x.open("POST","/wifitoggle",true);x.setRequestHeader("X-Requested-With","netswitch");
 x.onload=refresh;x.send()};
// Wi-Fi network list, shown in Settings too while scanning/hosting (not just on the
// temporary "DreamPi WiFi Config" page) - useful when this page is still reachable,
// for example over Ethernet, while the Pi's Wi-Fi is being (re)configured.
var wifiListKey=null,wifiChosen=null;
function wifiBars(sig){if(sig==null)return"";var n=sig>=-55?4:sig>=-65?3:sig>=-75?2:1;return " "+"█".repeat(n)+"░".repeat(4-n)}
function renderWifiList(nets){
 $("wifi-list").innerHTML=nets.map(function(n,i){
  return '<button type="button" class="wnet" data-i="'+i+'">'+(n.secured?"🔒 ":"")+esc(n.ssid)+
   '<span class="sig">'+esc(wifiBars(n.signal))+'</span></button>'}).join("")||
  '<div class="sub" style="margin:4px 0 10px">No networks found. Enter one manually.</div>';
 Array.prototype.forEach.call($("wifi-list").querySelectorAll(".wnet"),function(b){
  b.onclick=function(){wifiSelect(nets[+b.dataset.i])}})}
function wifiSelect(n){wifiChosen=n;$("wifi-ssid").value=n.ssid;$("wifi-ssid").readOnly=true;
 $("wifi-pass").style.display=n.secured?"block":"none";$("wifi-pass").value="";
 $("wifi-connect-b").disabled=false;$("wifi-connect-b").textContent="Connect";$("wifi-form").style.display="block"}
$("wifi-manual").onclick=function(){wifiSelect({ssid:"",secured:true});$("wifi-ssid").readOnly=false;$("wifi-ssid").focus()};
$("wifi-connect-b").onclick=function(){
 var ssid=$("wifi-ssid").value.trim();if(!ssid)return;
 $("wifi-connect-b").disabled=true;$("wifi-connect-b").textContent="Connecting...";
 var x=new XMLHttpRequest();x.open("POST","/wificonnect",true);x.setRequestHeader("Content-Type","application/json");
 x.onload=refresh;x.send(JSON.stringify({ssid:ssid,password:$("wifi-pass").value}))};
var logSize=0,debugOn=false,logBusy=false,debugOpen=false;
$("net").onclick=function(e){if(e.target.closest&&e.target.closest(".hang"))return;this.classList.toggle("open")};
// Hang up: tap once to arm, again within 4 s to confirm (a call in progress is easy to end by accident)
var hangArm=0;
$("hang-f").onsubmit=function(e){e.preventDefault();e.stopPropagation();var b=$("hang-b");
 if(b.disabled)return;
 if(Date.now()-hangArm>4000){hangArm=Date.now();b.textContent="Tap again to hang up";b.className="pill-s arm";
  setTimeout(function(){if(Date.now()-hangArm>=4000&&!b.disabled){b.textContent="Hang up";b.className="pill-s"}},4100);return}
 hangArm=0;b.disabled=true;b.textContent="Hanging up...";b.className="pill-s";
 var x=new XMLHttpRequest();x.open("POST","/hangup",true);x.setRequestHeader("X-Requested-With","netswitch");x.onload=refresh;x.send()};
function showSettings(open){$("settings").classList.toggle("open",open);
 if(!open)closePops();
 document.body.classList.toggle("settings-open",open);if(open){loadLed();loadButtons();loadAbout()}}
function loadAbout(){var x=new XMLHttpRequest();x.open("GET","/about",true);
 x.onload=function(){if(x.status!=200)return;$("about").innerHTML=JSON.parse(x.responseText).map(function(r){
  return '<tr><td class="n">'+esc(r[0])+'</td><td>'+esc(r[1])+'</td></tr>'}).join("")};x.send()}
$("cog").onclick=function(){showSettings(true)};
$("close-settings").onclick=function(){showSettings(false)};
document.addEventListener("keydown",function(e){if(e.key=="Escape"){if(lvlCur||fxCur||calibCur)closePops();else showSettings(false)}});
// Optional Dreamcast background (static/dc-background.js), remembered per browser
function bgWanted(){try{return localStorage.getItem("netswitch-bg")==="on"}catch(e){return false}}
function loadScript(src,done){var sc=document.createElement("script");sc.src=src;sc.onload=done;
 sc.onerror=function(){document.body.classList.remove("dcbg")};document.head.appendChild(sc)}
function setBg(on){
 try{localStorage.setItem("netswitch-bg",on?"on":"off")}catch(e){}
 $("bg-b").checked=on;document.body.classList.toggle("dcbg",on);document.documentElement.classList.toggle("dcbg",on);
 if(!on){if(window.DCBackground)DCBackground.stop();return}
 function go(){if(document.body.classList.contains("dcbg"))DCBackground.start($("dcbg"))}
 if(window.DCBackground)go();
 else if(window.THREE)loadScript("/static/dc-background.js",go);
 else loadScript("/static/three.min.js",function(){loadScript("/static/dc-background.js",go)})}
$("bg-b").onchange=function(){setBg(this.checked)};
if(bgWanted())setBg(true);
// Debug log menu: hidden unless switched on in settings, remembered per browser
function setDebugMenu(on){
 try{localStorage.setItem("netswitch-debug",on?"on":"off")}catch(e){}
 $("dbg-b").checked=on;$("debug-bar").style.display=on?"flex":"none";
 if(!on){debugOpen=false;$("debug").style.display="none";$("show-debug").classList.remove("open")}}
$("dbg-b").onchange=function(){setDebugMenu(this.checked)};
var led=null,ledDefaults=null,ledTimer=null,ledStates=[],ledEffects=[],ledCount=1,ledGpio=18,ledNet="dcnow";
var calibColumns=[],calibRows=[],calibSwatches={};
var ledInstalled=false,ledHiddenFlag=false,buttonsInstalled=false;
function updateGpioSection(){
 var ledOn=ledInstalled&&!ledHiddenFlag;
 $("gpio-led-row").style.display=ledOn?"flex":"none";
 $("gpio-btn1-row").style.display=buttonsInstalled?"flex":"none";
 $("gpio-btn2-row").style.display=buttonsInstalled?"flex":"none";
 $("gpio-wifi-row").style.display=buttonsInstalled?"flex":"none";
 $("gpio-section").style.display=(ledOn||buttonsInstalled)?"block":"none"}
function loadLed(){var x=new XMLHttpRequest();x.open("GET","/ledconfig",true);
 x.onload=function(){if(x.status!=200)return;var r=JSON.parse(x.responseText);
  led=r.config;ledDefaults=r.defaults;ledStates=r.states;ledEffects=r.effects;ledCount=r.count||1;ledGpio=r.gpio||18;
  calibColumns=r.calib_columns;calibRows=r.calib_rows;calibSwatches=r.calib_swatches;
  $("led-section").style.display=(r.installed&&!r.hidden)?"block":"none";   // install.sh --led, not hidden
  ledInstalled=r.installed;ledHiddenFlag=r.hidden;updateGpioSection();
  $("led-count-t").textContent=ledCount>1?" ("+ledCount+" LEDs)":"";
  if(!$("led-order").options.length)$("led-order").innerHTML=r.orders.map(function(o){
   return '<option value="'+o+'">'+o+'</option>'}).join("");
  if(!$("led-gpio").options.length)$("led-gpio").innerHTML=r.gpios.map(function(g){
   return '<option value="'+g+'">GPIO'+g+'</option>'}).join("");
  $("led-count-i").value=ledCount;$("led-gpio").value=ledGpio;$("led-order").value=led.order;
  buildCalib();
  buildLed()};x.send()}
function buildLed(){
 ["dcnow","dcnet"].forEach(function(n){$("tab-"+n).className="pill-s "+n+(n==ledNet?" sel":"")});
 var grp="";
 $("led-rows").innerHTML=ledStates.map(function(s){var st=s[0],h="";
  if(s[2]!=grp){grp=s[2];h='<tr class="grp"><td colspan="4">'+(grp=="error"?"Errors":grp=="wifi"?"Wi-Fi setup":"Information")+'</td></tr>'}
  return h+'<tr id="r-'+st+'"><td class="name"><input type="checkbox" class="cbox '+ledNet+'" id="e-'+st+'" title="Show this message" aria-label="Show '+esc(s[1])+'"><span class="lbl-t">'+esc(s[1])+'</span></td>'+
  '<td class="c"><input type="color" id="c-'+st+'" data-state="'+st+'" aria-label="Colour"></td>'+
  '<td class="c"><button type="button" class="chip fx" id="f-'+st+'" data-state="'+st+'" data-label="'+esc(s[1])+'"></button></td>'+
  '<td class="c"><button type="button" class="chip lvl" id="l-'+st+'" data-state="'+st+'" data-label="'+esc(s[1])+'"></button></td></tr>'}).join("");
 ledStates.forEach(function(s){var st=s[0];
  $("c-"+st).addEventListener("input",function(){led.colours[ledNet][st].color=this.value;saveLed()});
  $("e-"+st).onchange=function(){led.colours[ledNet][st].enabled=this.checked;showRow(st);saveLed()};
  $("f-"+st).onclick=function(e){e.stopPropagation();openFx(this)};
  $("l-"+st).onclick=function(e){e.stopPropagation();openLvl(this)}});
 showLed()}
["dcnow","dcnet"].forEach(function(n){$("tab-"+n).onclick=function(){ledNet=n;closePops();buildLed()}});
function netName(n){return n=="dcnet"?"DCNET":"DCNow!"}
function effectName(e){for(var i=0;i<ledEffects.length;i++)if(ledEffects[i][0]==e)return ledEffects[i][1];return e}
function showLed(){$("led-bright").value=brightToSlider(led.brightness);$("led-bright-v").textContent=pct(led.brightness);
 $("led-order").value=led.order;
 buildCalib();
 ledStates.forEach(function(s){var st=s[0],c=led.colours[ledNet][st];
  $("c-"+st).value=c.color;$("e-"+st).checked=c.enabled!==false;showRow(st);showFx(st);showLvl(st)})}
function cap(s){return s.charAt(0).toUpperCase()+s.slice(1)}
function buildCalib(){
 $("calib-grid").innerHTML=calibRows.map(function(row){
  return '<div class="calib-row">'+calibColumns.map(function(col){
   var ref=calibSwatches[col][row],v=(led.calibrate[col]||{})[row];
   return '<button type="button" class="calib-sw'+(v?' done':'')+'" style="background:'+ref+
    '" data-col="'+col+'" data-row="'+row+'" title="'+cap(col)+', '+row+'" aria-label="'+cap(col)+', '+row+'"></button>';
  }).join('')+'</div>'}).join('');
 Array.prototype.forEach.call($("calib-grid").querySelectorAll("button"),function(b){
  b.onclick=function(e){e.stopPropagation();openCalib(this)}})}
function showRow(st){$("r-"+st).className=led.colours[ledNet][st].enabled===false?"dis":""}
function showFx(st){var el=$("f-"+st);if(!el)return;var c=led.colours[ledNet][st];
 var sub=[];if(c.effect!="solid")sub.push(c.speed);if(ledCount>1&&c.leds)sub.push(c.leds[0]==c.leds[1]?"LED "+c.leds[0]:c.leds[0]+"-"+c.leds[1]);
 el.innerHTML=esc(effectName(c.effect))+(sub.length?"<small>"+sub.join(" · ")+"</small>":"")}
function showLvl(st){var el=$("l-"+st);if(!el)return;var b=led.colours[ledNet][st].brightness,own=b!==null&&b!==undefined;
 el.className="chip lvl "+ledNet+(own?" on":"");el.textContent=pct(own?b:led.brightness)}
function placePop(pop,el){var box=pop.parentNode.getBoundingClientRect(),r=el.getBoundingClientRect();
 pop.classList.add("open");
 pop.style.left=Math.min(Math.max(r.right-box.left-pop.offsetWidth,0),box.width-pop.offsetWidth)+"px";
 pop.style.top=(r.bottom-box.top+6)+"px"}
var lvlCur=null,fxCur=null,calibCur=null;
function closePops(){$("lvl-pop").classList.remove("open");$("fx-pop").classList.remove("open");$("calib-pop").classList.remove("open");
 if(calibCur)stopCalibPreview();
 lvlCur=fxCur=calibCur=null}
function openFx(el){closePops();var st=el.dataset.state,c=led.colours[ledNet][st];fxCur=st;
 $("fx-t").textContent=el.dataset.label+", "+netName(ledNet)+" selected";
 $("fx-opts").innerHTML=ledEffects.filter(function(e){return !e[2]||ledCount>1||e[0]==c.effect}).map(function(e){
  return '<button type="button" class="pill-s" data-fx="'+e[0]+'">'+esc(e[1])+'</button>'}).join("");
 Array.prototype.forEach.call($("fx-opts").querySelectorAll("button"),function(b){b.onclick=function(){c.effect=b.dataset.fx;fxMark();saveLed()}});
 $("fx-sec").style.display=ledCount>1?"flex":"none";
 $("sec-a").max=$("sec-b").max=ledCount;
 fxMark();placePop($("fx-pop"),el)}
function fxMark(){if(!fxCur)return;var c=led.colours[ledNet][fxCur],fixed=c.effect=="solid";
 Array.prototype.forEach.call($("fx-opts").querySelectorAll("button"),function(b){b.className="pill-s "+ledNet+(b.dataset.fx==c.effect?" sel":"")});
 Array.prototype.forEach.call($("fx-speed").querySelectorAll("button"),function(b){b.disabled=fixed;
  b.className="pill-s "+ledNet+(!fixed&&b.dataset.speed==c.speed?" sel":"")});
 var L=c.leds;$("sec-all").className="pill-s "+ledNet+(L?"":" sel");
 $("sec-a").value=L?L[0]:"";$("sec-b").value=L?L[1]:"";$("sec-a").placeholder="1";$("sec-b").placeholder=ledCount;
 showFx(fxCur)}
$("sec-all").onclick=function(){if(!fxCur)return;led.colours[ledNet][fxCur].leds=null;fxMark();saveLed()};
function secInput(){if(!fxCur)return;var a=parseInt($("sec-a").value,10),b=parseInt($("sec-b").value,10);
 if(isNaN(a)&&isNaN(b))return;if(isNaN(a))a=1;if(isNaN(b))b=ledCount;
 a=Math.max(1,Math.min(ledCount,a));b=Math.max(1,Math.min(ledCount,b));
 led.colours[ledNet][fxCur].leds=[Math.min(a,b),Math.max(a,b)];
 $("sec-all").className="pill-s "+ledNet;showFx(fxCur);saveLed()}
$("sec-a").onchange=$("sec-b").onchange=secInput;
Array.prototype.forEach.call($("fx-speed").querySelectorAll("button"),function(b){b.onclick=function(){
 if(!fxCur)return;led.colours[ledNet][fxCur].speed=b.dataset.speed;fxMark();saveLed()}});
$("fx-done").onclick=closePops;
function openLvl(el){closePops();var st=el.dataset.state,c=led.colours[ledNet][st];
 if(c.brightness===null||c.brightness===undefined){c.brightness=led.brightness;showLvl(st);saveLed()}
 lvlCur=st;
 $("lvl-t").textContent=el.dataset.label+", "+netName(ledNet)+" selected";
 $("lvl-r").style.accentColor=ledNet=="dcnet"?"#1c6fe8":"#e8761c";$("lvl-r").value=brightToSlider(c.brightness);$("lvl-v").textContent=pct(c.brightness);
 placePop($("lvl-pop"),el)}
$("lvl-r").oninput=function(){if(!lvlCur)return;var b=Math.round(sliderToBright(this.value)*1000)/1000;
 led.colours[ledNet][lvlCur].brightness=b;$("lvl-v").textContent=pct(b);showLvl(lvlCur);saveLed()};
$("lvl-base").onclick=function(){if(!lvlCur)return;led.colours[ledNet][lvlCur].brightness=null;showLvl(lvlCur);saveLed();closePops()};
$("lvl-done").onclick=closePops;
$("lvl-pop").onclick=$("fx-pop").onclick=$("calib-pop").onclick=function(e){e.stopPropagation()};
$("settings").addEventListener("click",function(){if(lvlCur||fxCur||calibCur)closePops()});
function hexToRgb(hex){var n=parseInt(hex.slice(1),16);return [n>>16&255,n>>8&255,n&255]}
function rgbToHex(rgb){return "#"+rgb.map(function(v){var h=Math.max(0,Math.min(255,Math.round(v))).toString(16);
 return h.length<2?"0"+h:h}).join("")}
function openCalib(el){closePops();var col=el.dataset.col,row=el.dataset.row;calibCur={col:col,row:row};
 var ref=calibSwatches[col][row],v=(led.calibrate[col]||{})[row]||ref;
 $("calib-t").textContent=cap(col)+", "+row;
 $("calib-ref").style.background=ref;
 setCalibSliders(hexToRgb(v));
 placePop($("calib-pop"),el);
 clearInterval(calibHeartbeat);calibHeartbeat=setInterval(function(){sendCalibPreview(calibRgb())},1000)}
function setCalibSliders(rgb){["r","g","b"].forEach(function(c,i){$("calib-"+c).value=rgb[i];$("calib-"+c+"-v").textContent=rgb[i]});
 calibLive()}
function calibRgb(){return ["r","g","b"].map(function(c){return parseInt($("calib-"+c).value,10)})}
function calibLive(){var rgb=calibRgb();$("calib-live").style.background=rgbToHex(rgb);sendCalibPreview(rgb)}
var calibTimer=null,calibHeartbeat=null;
function sendCalibPreview(rgb){clearTimeout(calibTimer);calibTimer=setTimeout(function(){
 var x=new XMLHttpRequest();x.open("POST","/calibpreview",true);x.setRequestHeader("Content-Type","application/json");
 x.setRequestHeader("X-Requested-With","netswitch");x.send(JSON.stringify({r:rgb[0],g:rgb[1],b:rgb[2]}))},100)}
function stopCalibPreview(){clearTimeout(calibTimer);clearInterval(calibHeartbeat);calibHeartbeat=null;
 var x=new XMLHttpRequest();x.open("POST","/calibdone",true);x.setRequestHeader("X-Requested-With","netswitch");x.send()}
["r","g","b"].forEach(function(c){$("calib-"+c).oninput=function(){$("calib-"+c+"-v").textContent=this.value;calibLive()}});
$("calib-reset").onclick=function(){if(!calibCur)return;
 led.calibrate[calibCur.col][calibCur.row]=null;
 setCalibSliders(hexToRgb(calibSwatches[calibCur.col][calibCur.row]));
 buildCalib();saveLed()};
$("calib-done").onclick=function(){if(calibCur)led.calibrate[calibCur.col][calibCur.row]=rgbToHex(calibRgb());
 buildCalib();saveLed();closePops()};
function saveLed(){clearTimeout(ledTimer);ledTimer=setTimeout(function(){
 var x=new XMLHttpRequest();x.open("POST","/ledconfig",true);x.setRequestHeader("Content-Type","application/json");
 led.count=ledCount;led.gpio=ledGpio;
 x.onload=function(){if(x.status!=200)return;var el=$("led-saved");el.classList.add("show");
  setTimeout(function(){el.classList.remove("show")},1200);refresh()};x.send(JSON.stringify(led))},250)}
// Logarithmic slider: the left half covers 0-9 %, where an indicator LED is most useful.
var LOG_BASE=100;
function sliderToBright(p){return (Math.pow(LOG_BASE,p/1000)-1)/(LOG_BASE-1)}
function brightToSlider(b){return Math.round(1000*Math.log(1+b*(LOG_BASE-1))/Math.log(LOG_BASE))}
function pct(b){var v=b*100;return (v<10&&v>0?v.toFixed(1):Math.round(v))+"%"}
$("led-bright").oninput=function(){led.brightness=Math.round(sliderToBright(this.value)*1000)/1000;$("led-bright-v").textContent=pct(led.brightness);
 ledStates.forEach(function(s){showLvl(s[0])});saveLed()};
$("led-reset").onclick=function(){var order=led.order,calib=led.calibrate;   // wiring facts, not a look to reset
 led=JSON.parse(JSON.stringify(ledDefaults));led.order=order;led.calibrate=calib;showLed();saveLed()};
$("led-count-i").onchange=function(){var n=parseInt(this.value,10);
 if(isNaN(n))return;ledCount=Math.max(1,Math.min(300,n));this.value=ledCount;
 $("led-count-t").textContent=ledCount>1?" ("+ledCount+" LEDs)":"";saveLed()};
$("led-gpio").onchange=function(){ledGpio=parseInt(this.value,10);saveLed()};
$("led-order").onchange=function(){led.order=this.value;saveLed()};
$("led-hide-b").onclick=function(){
 if(!confirm("Hide the Status LED settings? This can only be undone on the Pi itself, by deleting led_hidden in /opt/dreampi-netswitch."))return;
 var x=new XMLHttpRequest();x.open("POST","/ledhide",true);x.setRequestHeader("X-Requested-With","netswitch");
 x.onload=function(){$("led-section").style.display="none";ledHiddenFlag=true;updateGpioSection()};x.send()};
var btn=null,btnTimer=null;
function loadButtons(){var x=new XMLHttpRequest();x.open("GET","/buttonconfig",true);
 x.onload=function(){if(x.status!=200)return;var r=JSON.parse(x.responseText);
  btn=r.config;buttonsInstalled=r.installed;
  if(!$("btn1-gpio").options.length){var gOpts=r.gpios.map(function(g){return '<option value="'+g+'">GPIO'+g+'</option>'}).join("");
   $("btn1-gpio").innerHTML=gOpts;$("btn2-gpio").innerHTML=gOpts}
  if(!$("btn1-fn").options.length){var fOpts=r.functions.map(function(f){return '<option value="'+f[0]+'">'+esc(f[1])+'</option>'}).join("");
   $("btn1-fn").innerHTML=fOpts;$("btn2-fn").innerHTML=fOpts}
  if(!$("wifi-btn-sel").options.length)$("wifi-btn-sel").innerHTML=r.wifi_choices.map(function(c){
   return '<option value="'+c[0]+'">'+esc(c[1])+'</option>'}).join("");
  $("btn1-gpio").value=btn.button1_gpio;$("btn1-fn").value=btn.button1_function;
  $("btn2-gpio").value=btn.button2_gpio;$("btn2-fn").value=btn.button2_function;
  $("wifi-btn-sel").value=btn.wifi_button;
  updateGpioSection()};x.send()}
function saveButtons(){clearTimeout(btnTimer);btnTimer=setTimeout(function(){
 var x=new XMLHttpRequest();x.open("POST","/buttonconfig",true);x.setRequestHeader("Content-Type","application/json");
 x.onload=function(){if(x.status!=200)return;var el=$("gpio-saved");el.classList.add("show");
  setTimeout(function(){el.classList.remove("show")},1200);loadButtons()};x.send(JSON.stringify(btn))},250)}
$("btn1-gpio").onchange=function(){btn.button1_gpio=parseInt(this.value,10);saveButtons()};
$("btn1-fn").onchange=function(){btn.button1_function=this.value;saveButtons()};
$("btn2-gpio").onchange=function(){btn.button2_gpio=parseInt(this.value,10);saveButtons()};
$("btn2-fn").onchange=function(){btn.button2_function=this.value;saveButtons()};
$("wifi-btn-sel").onchange=function(){btn.wifi_button=this.value;saveButtons()};
$("show-debug").onclick=function(){debugOpen=!debugOpen;
 $("debug").style.display=debugOpen?"block":"none";
 this.classList.toggle("open",debugOpen);
 if(debugOpen){pollLog();var el=$("log");el.scrollTop=el.scrollHeight}};
setDebugMenu((function(){try{return localStorage.getItem("netswitch-debug")==="on"}catch(e){return false}})());
function cls(line){
 if(/modem: DTMF/.test(line))return"dtmf";
 if(/netswitch:|add-on:/.test(line))return"route";
 if(/web page:/.test(line))return"web";
 if(/underrun/.test(line))return"dim";
 if(/fail|error|Couldn't|Unable|No carrier|NO CARRIER/i.test(line))return"err";
 if(/modem/.test(line))return"modem";
 return"";
}
function pollLog(){
 if(!debugOpen||logBusy||(!debugOn&&logSize))return; logBusy=true;
 var x=new XMLHttpRequest();x.open("GET","/log?from="+logSize,true);
 x.onload=function(){logBusy=false;if(x.status!=200)return;var r=JSON.parse(x.responseText);
  var el=$("log");if(r.reset)el.innerHTML="";
  if(r.text){var html=r.text.split(/\\r?\\n/).filter(function(l){return l.length}).map(function(l){
    return '<div class="'+cls(l)+'">'+esc(l)+'</div>'}).join("");
   el.insertAdjacentHTML("beforeend",html);
   if($("follow").checked)el.scrollTop=el.scrollHeight;}
  logSize=r.size;};
 x.onerror=function(){logBusy=false};x.send();
}
function refresh(){var x=new XMLHttpRequest();x.open("GET","/api",true);
 x.onload=function(){if(x.status==200)render(JSON.parse(x.responseText))};x.send()}
Array.prototype.forEach.call(document.forms,function(f){if(f.id=="hang-f")return;f.onsubmit=function(e){e.preventDefault();
 var x=new XMLHttpRequest();x.open("POST",f.getAttribute("action"),true);x.setRequestHeader("X-Requested-With","netswitch");
 x.onload=function(){refresh();pollLog()};x.send()}});
refresh(); setInterval(refresh,1000);
pollLog(); setInterval(pollLog,700);
</script>
</body></html>"""


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
            swatches = dict((col, dict((row, calib_swatch(col, row)) for row in CALIB_ROWS))
                            for col in CALIB_COLUMNS)
            self.send(json.dumps({"config": led_config(), "defaults": default_led_config(),
                                  "states": LED_STATES,
                                  "effects": EFFECTS, "orders": LED_ORDERS, "count": led_count(),
                                  "gpio": led_gpio(), "gpios": GPIO_PINS,
                                  "calib_columns": CALIB_COLUMNS, "calib_rows": CALIB_ROWS,
                                  "calib_swatches": swatches,
                                  "installed": os.path.exists(LED_ENABLED), "hidden": led_hidden()}),
                     "application/json")
        elif self.path == "/buttonconfig":
            self.send(json.dumps({"config": {"button1_gpio": button_gpio(1), "button2_gpio": button_gpio(2),
                                             "button1_function": button_function(1),
                                             "button2_function": button_function(2),
                                             "wifi_button": wifi_button()},
                                  "gpios": BUTTON_GPIO_PINS, "functions": BUTTON_FUNCTIONS,
                                  "wifi_choices": WIFI_BUTTON_CHOICES,
                                  "installed": os.path.exists(WIFI_BUTTON_ENABLED)}),
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
        if self.path == "/calibpreview":
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 1024)
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                save_calib_preview(*(max(0, min(255, int(data[k]))) for k in ("r", "g", "b")))
            except (ValueError, KeyError, TypeError, IOError, OSError):
                pass
        elif self.path == "/calibdone":
            clear_calib_preview()
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
            if os.path.exists(WIFI_BUTTON_ENABLED):
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
            if os.path.exists(WIFI_BUTTON_ENABLED):
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
