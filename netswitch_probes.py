# DreamPi Netswitch add-on - things the web service measures: internet and
# link checks, Pi health, hang up, versions, modem identification, and the
# checker() loop that publishes them. Works on Python 3 and 2.7.
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time

import netswitch_core as core

INTERNET_EVERY = 30   # seconds between internet checks while it works
INTERNET_RETRY = 5    # ... and while it doesn't
LINK_EVERY = 0.5      # seconds between checks of cables / Wi-Fi / route and the modem (a few small file reads: next to no CPU)
HEALTH_EVERY = 2      # ... and of the Pi's temperature and power flags (the slower ones; they change slowly)
STATE_BEAT = 5        # the file the LED service reads is written when something changed and at least this often (it ignores one older than NET_STALE)

_checks = {"internet": {"state": "checking", "text": "Checking...", "time": 0},
           "pi": {"state": "checking", "text": "Checking...", "problem": False, "undervoltage": False}}
_checks_lock = threading.Lock()


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
    return {"state": "ok", "text": "Connected", "ms": best}      # the ping is its own field: the page shows it as the row's subtitle


def _sys(iface, name):
    return core.read_file("/sys/class/net/%s/%s" % (iface, name))


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


WIFI_WEAK_DBM = -75           # a signal at or below this is "weak" (the same line the Wi-Fi setup list calls Weak)
LATENCY_HIGH_MS = 200         # an internet connection slower than this (average round trip) or losing this many packets is "slow" for gaming
LOSS_HIGH_PERCENT = 10


def wifi_level():
    """The signal strength of the Wi-Fi link in dBm (from /proc/net/wireless), or None without Wi-Fi or a reading."""
    try:
        with open("/proc/net/wireless") as f:
            for line in f.readlines()[2:]:
                parts = line.split()
                if len(parts) > 3:
                    return int(float(parts[3].rstrip(".")))
    except (IOError, OSError, ValueError):
        pass
    return None


def parse_ping(text):
    """(average round trip in ms or None, packet loss in percent or None) from the output of ping."""
    loss = avg = None
    m = re.search(r"([\d.]+)% packet loss", text)
    if m:
        loss = float(m.group(1))
    m = re.search(r"= [\d.]+/([\d.]+)/[\d.]+", text)
    if m:
        avg = float(m.group(1))
    return avg, loss


def ping_quality(host="1.1.1.1"):
    """Three quick pings: (average ms or None, loss percent or None); (None, None) when ping isn't there or the answer isn't readable."""
    try:
        out = subprocess.check_output(["ping", "-c", "3", "-i", "0.3", "-W", "1", host], stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:      # ping exits 1 when some or all of the packets were lost: its text is still the answer
        out = e.output or b""
    except OSError:
        return None, None
    return parse_ping(out.decode("ascii", "replace"))


def is_slow(avg, loss):
    return bool((loss is not None and loss >= LOSS_HIGH_PERCENT) or (avg is not None and avg >= LATENCY_HIGH_MS))


_net = {"links": None, "internet": {"state": "checking", "text": "Checking...", "time": 0}, "quality": (None, None),
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
        if result["state"] == "ok":
            _net["quality"] = ping_quality()
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
    raw = core.read_file("/sys/class/thermal/thermal_zone0/temp")
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
    raw = core.read_file(THROTTLED_SYSFS)
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
    ip = lan_ip()      # shown with the internet (the switcher's Internet row), not in the Pi's lines
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
        core.debug_log("web page: " + text)
        sys.stderr.write("hang up: %s\n" % text)

    try:
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
                if core.dreampi_state()[0] == "ok":
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
    if not core.dreampi_state()[0].startswith("call"):
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
ADDON_VERSION = os.path.join(core.BASE_DIR, "version")   # written by install.sh


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
    rows = [("Add-on", core.read_file(ADDON_VERSION) or "unknown")]
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
    "conexant usb modem",   # the plain descriptor of Conexant-chip modems with no brand of their own; confirmed working on a real DreamPi + Pi
)
# Reported NOT to work: same case as the good ones above, but an older/
# different chip inside.
UNKNOWN_MODEMS = (
    "conceptronic c56u",   # the original, without "-v2"/"se"
)


def modem_port():
    return core.read_file(MODEM_PORT)


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
        vendor, product = core.read_file(os.path.join(d, "idVendor")), core.read_file(os.path.join(d, "idProduct"))
        if not vendor or not product:
            return None
        return {"vendor": vendor, "product": product,
                "manufacturer": core.read_file(os.path.join(d, "manufacturer")) or "",
                "product_name": core.read_file(os.path.join(d, "product")) or "",
                "serial": core.read_file(os.path.join(d, "serial")) or ""}
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


def new_checker_state():
    return {"poke": core.poke_stamp("internet"), "health": 0.0, "pi": None, "sig": None, "written": 0.0}


def checker_step(seen, now=None):
    """One round of checker(): `seen` is what the last rounds saw (new_checker_state())."""
    now = time.time() if now is None else now
    links = link_state()
    if links != _net["links"]:           # plugged/unplugged, Wi-Fi joined/lost
        _net["links"] = links
        _net["recheck"].set()
    stamp = core.poke_stamp("internet")
    if stamp != seen["poke"]:            # somebody asked for it now
        seen["poke"] = stamp
        _net["recheck"].set()
    if seen["pi"] is None or now - seen["health"] >= HEALTH_EVERY:
        seen["pi"], seen["health"] = pi_health(), now
        core.trim_log()
    pi = seen["pi"]
    internet = _net["internet"]
    if not links["network"]:
        internet = {"state": "bad", "text": "No network connection", "time": int(time.time())}
    shown = dict(internet)
    if internet["state"] == "ok" and (links["ethernet"] or links["wifi"]):
        via = " and ".join(n for n, on in (("Ethernet", links["ethernet"]), ("Wi-Fi", links["wifi"])) if on)
        shown["text"] = internet["text"].replace("Connected", "Connected via " + via, 1)
    with _checks_lock:
        _checks["internet"] = shown
        _checks["pi"] = pi
    flags = pi.get("throttled")
    level = wifi_level() if links["wifi"] else None
    avg, loss = _net["quality"]
    data = {"ethernet": links["ethernet"], "wifi": links["wifi"],
            "network": links["network"], "pi_problem": pi["problem"],
            "internet": None if internet["state"] == "checking" else internet["state"] == "ok",
            # what the LED messages are made from (modules/led/netswitch_ledconfig.py)
            "dns_fail": internet["state"] == "warn",
            "no_ip": bool((links["ethernet"] or links["wifi"]) and not links["network"]),
            "wifi_weak": level is not None and level <= WIFI_WEAK_DBM,
            "slow": is_slow(avg, loss) if internet["state"] == "ok" else False,
            "modem": modem_plugged(),
            "undervoltage": bool(pi.get("undervoltage")),
            "throttled": bool(flags is not None and flags & 0x4),
            "hot": pi.get("temp") is not None and pi["temp"] >= 80,
            "warm": pi.get("temp") is not None and pi["temp"] >= 70}
    sig = json.dumps(data, sort_keys=True)
    if sig != seen["sig"] or now - seen["written"] >= STATE_BEAT:      # a change goes out at once; otherwise just a sign of life
        data["time"] = now
        core._write_net_state(data)
        seen["sig"], seen["written"] = sig, now


def checker():
    """Cables / Wi-Fi / route and the modem every half second (cheap, so a change shows quickly), the Pi's health every 2 s, and the
    shared state file for the LED service (written when something changed). core.poke("internet") makes the internet check run
    now, from any process."""
    t = threading.Thread(target=internet_checker)
    t.daemon = True
    t.start()
    seen = new_checker_state()
    while True:
        checker_step(seen)
        time.sleep(LINK_EVERY)
