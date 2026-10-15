# Base - network watch: writes one line to the service's log (journalctl -u <service>) whenever the computer's network changes: a link going up or
# down, an address added, lost or changed, the router answering ping or not. After a "the screens lost contact" there is then a record of what the
# host's own network did (the page itself can not make the computer stop answering ping). Reads /sys/class/net and runs `ip` and `ping` when they
# exist; nothing is changed. Python 3 only.
import os
import re
import subprocess
import sys
import time

SYS_NET = "/sys/class/net"
SKIP = ("lo", "veth", "docker", "br-", "virbr", "tun", "tap")


def _run(argv, timeout=5):
    try:
        return subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return ""


def parse_addrs(text):
    """{interface: [address/len, ...]} from `ip -4 -o addr show` (one line per address: "2: eth0    inet 192.168.1.20/24 brd ...")."""
    out = {}
    for line in (text or "").splitlines():
        m = re.match(r"\d+:\s+(\S+)\s+inet\s+(\S+)", line)
        if m:
            out.setdefault(m.group(1).split("@")[0], []).append(m.group(2))
    return out


def parse_gateway(text):
    """The address of the default route from `ip -4 route show default`, or ""."""
    m = re.search(r"default via (\S+)", text or "")
    return m.group(1) if m else ""


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except (IOError, OSError):
        return ""


def snapshot():
    """{interface: {"state": operstate, "carrier": "0"/"1"/"", "addrs": [...]}} for the real interfaces, and the default gateway."""
    addrs = parse_addrs(_run(["ip", "-4", "-o", "addr", "show"]))
    nets = {}
    try:
        names = sorted(os.listdir(SYS_NET))
    except OSError:
        names = []
    for n in names:
        if n.startswith(SKIP):
            continue
        d = os.path.join(SYS_NET, n)
        speed = _read(os.path.join(d, "speed"))
        nets[n] = {"state": _read(os.path.join(d, "operstate")), "carrier": _read(os.path.join(d, "carrier")), "addrs": sorted(addrs.get(n, [])),
                   "link": ("%s Mb/s %s" % (speed, _read(os.path.join(d, "duplex")) or "?")) if speed.isdigit() else ""}      # what the card negotiated with the switch
    return {"nets": nets, "gateway": parse_gateway(_run(["ip", "-4", "route", "show", "default"]))}


def gateway_answers(gw):
    """True / False when `ping` could be asked, None when there is no gateway or no ping command."""
    if not gw:
        return None
    try:
        return subprocess.run(["ping", "-c", "1", "-W", "2", gw], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return None


def changes(old, new):
    """The lines to log for two snapshots (nothing when they are the same)."""
    lines = []
    for n in sorted(set(old["nets"]) | set(new["nets"])):
        a, b = old["nets"].get(n), new["nets"].get(n)
        if a is None:
            lines.append("interface %s appeared (%s, %s)" % (n, b["state"] or "?", ", ".join(b["addrs"]) or "no address"))
        elif b is None:
            lines.append("interface %s is gone" % n)
        else:
            if a["state"] != b["state"] or a["carrier"] != b["carrier"]:
                lines.append("%s link %s -> %s (carrier %s -> %s)" % (n, a["state"] or "?", b["state"] or "?", a["carrier"] or "?", b["carrier"] or "?"))
            if a.get("link", "") != b.get("link", ""):
                lines.append("%s negotiated %s -> %s" % (n, a.get("link") or "nothing", b.get("link") or "nothing"))
            if a["addrs"] != b["addrs"]:
                lines.append("%s address %s -> %s" % (n, ", ".join(a["addrs"]) or "none", ", ".join(b["addrs"]) or "none"))
    if old["gateway"] != new["gateway"]:
        lines.append("default gateway %s -> %s" % (old["gateway"] or "none", new["gateway"] or "none"))
    return lines


def watch(every=10, log=None):
    """Forever: log what changes in the network. Runs in a thread of the web service."""
    log = log or (lambda text: sys.stderr.write("network: %s\n" % text))
    last = snapshot()
    log("watching %s; gateway %s" % (", ".join("%s %s %s %s" % (n, v["state"] or "?", "/".join(v["addrs"]) or "no address", v.get("link", "")) for n, v in sorted(last["nets"].items())) or "no interface", last["gateway"] or "none"))
    gw_ok = None
    wall, mono = time.time(), time.monotonic()
    while True:
        time.sleep(every)
        w, m = time.time(), time.monotonic()
        slept = (w - wall) - (m - mono)           # the monotonic clock stands still while the computer is suspended, the wall clock does not
        if slept > 5:
            log("the computer was ASLEEP (suspended) for about %d s: it did not answer anybody meanwhile. Stop it from sleeping (install.sh does, unless --allow-sleep); check the BIOS / desktop power settings" % slept)
        elif m - mono > every * 4:
            log("this service was not running for %d s (the computer was stalled)" % (m - mono))
        wall, mono = w, m
        now = snapshot()
        for line in changes(last, now):
            log(line)
        last = now
        ok = gateway_answers(now["gateway"])
        if ok is not None and ok != gw_ok:
            if gw_ok is not None or not ok:
                log("the router %s %s ping" % (now["gateway"], "answers" if ok else "does NOT answer"))
            gw_ok = ok
