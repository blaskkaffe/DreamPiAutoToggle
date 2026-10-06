#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Check-in add-on - Wi-Fi setup (optional, install.sh --wifi).
# Library for netswitch_wifi_service.py (service dreampi-netswitch-wifi): the page's Settings > System > Wi-Fi setup
# button (POST /wifitoggle) touches wifi_start / wifi_stop and the service calls this module's
# setup_cycle(), which does the rest. The original design notes follow.
#
# Wi-Fi setup is the optional part (install.sh --wifi, or the Modules menu): the page's "Wi-Fi setup"
# button in Settings > System (POST /wifitoggle, which just touches
# wifi_start / wifi_stop under /opt/dreampi-netswitch - the same files this
# service watches), starts:
#   1. Scans for Wi-Fi networks on the wireless interface and keeps the list
#      in memory for the length of the setup session.
#   2. Hosts an open access point named "CheckIn WiFi Config" (192.168.4.1)
#      with hostapd + dnsmasq, and a small web page (styled like the main
#      page) listing the scanned networks plus a manual SSID/password entry.
#   3. When a network is chosen, tears the access point down, writes it into
#      wpa_supplicant.conf (via wpa_passphrase) and waits for the Pi to
#      associate and reach the internet.
#   4. On success Wi-Fi setup ends and everything returns to normal. On failure the
#      whole cycle repeats (rescans and re-hosts the access point) until the page cancels it.
# The current state is written to /tmp/dreampi-netswitch.wifi for the web page (a warning banner and the Settings button) to read.
#
# This assumes the classic Raspberry Pi OS network stack Raspberry Pi OS normally
# runs on: wpa_supplicant + dhcpcd managing the wireless interface, and
# hostapd + dnsmasq available to host the setup access point (install.sh
# installs them with apt if missing, and disables their own systemd units
# so they don't fight the ones this service starts by hand). It has not been
# tried on real Wi-Fi hardware; see the README and CLAUDE.md "Not yet
# verified" for details of what's untested.
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time

try:
    from http.server import BaseHTTPRequestHandler, HTTPServer
except ImportError:   # not expected (this service only ever runs under python3)
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                                            # this module's other files
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))          # the add-on's base files (netswitch_core ...)
import netswitch_core as core  # noqa: E402  (paths, settings, debug_log())
import netswitch_probes as probes  # noqa: E402  (check_internet())

BASE_DIR = core.BASE_DIR
HOSTAPD_CONF = os.path.join(BASE_DIR, "wifi_hostapd.conf")
DNSMASQ_CONF = os.path.join(BASE_DIR, "wifi_dnsmasq.conf")
WPA_CONF = "/etc/wpa_supplicant/wpa_supplicant.conf"

AP_SSID = core.WIFI_AP_SSID
AP_IP = "192.168.4.1"
AP_DHCP_FROM, AP_DHCP_TO = "192.168.4.10", "192.168.4.100"
SCAN_WAIT = 4             # seconds to let a scan finish before reading results
AP_TIMEOUT = 600          # the open setup access point closes itself after this many seconds without a choice
CONNECT_TIMEOUT = 25      # seconds to wait for an IP address after a connect attempt
RESULT_PAUSE = 5          # seconds the green/red result shows before moving on

_devnull = subprocess.DEVNULL


def run(cmd, timeout=15):
    """Best-effort system command: failures (missing unit, wrong state,
    missing tool) are expected and never allowed to bring the service down."""
    try:
        subprocess.run(cmd, stdout=_devnull, stderr=_devnull, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        pass


def output(cmd, timeout=10):
    try:
        return subprocess.check_output(cmd, stderr=_devnull, timeout=timeout).decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return None


# --------------------------------------------------------------- interface

# Demo mode (install.sh --wifi-demo, marker wifi_demo): the whole setup cycle runs
# on dummy networks, without touching hostapd, dnsmasq, wpa_supplicant or the
# interface, so the page, the LED states and the flow can be tried on a Pi that
# has no Wi-Fi. A connect succeeds for open networks and for the password "demo"
# (anything else fails after a short wait, to show the failure state).
DEMO_NETWORKS = [
    {"ssid": "Office-Wifi", "signal": -45, "secured": True},
    {"ssid": "Neighbour 5G", "signal": -62, "secured": True},
    {"ssid": "CoffeeShop Free", "signal": -70, "secured": False},
    {"ssid": "A_Very_Long_Network_Name_To_See_How_The_List_Copes", "signal": -78, "secured": True},
    {"ssid": "Old Router", "signal": -85, "secured": True},
]
DEMO_PASSWORD = "demo"
DEMO_CONNECT_SECONDS = 3


def demo():
    return os.path.exists(core.WIFI_DEMO)


def wifi_iface():
    """The first wireless interface, or None."""
    if demo():
        return "wlan0"
    try:
        for name in sorted(os.listdir("/sys/class/net")):
            if os.path.isdir("/sys/class/net/%s/wireless" % name):
                return name
    except OSError:
        pass
    return None


def has_ip(iface):
    out = output(["ip", "-4", "addr", "show", iface])
    return bool(out and " inet " in out)


# ------------------------------------------------------------------- state

def set_state(state, ssid=None, networks=None):
    data = {"state": state, "ssid": ssid, "time": time.time()}
    if networks is not None:
        data["networks"] = networks
    tmp = core.WIFI_STATE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.rename(tmp, core.WIFI_STATE)
    except (IOError, OSError):
        pass


def stop_requested():
    return os.path.exists(core.WIFI_STOP)


def start_requested():
    return os.path.exists(core.WIFI_START)


def clear_flags():
    for path in (core.WIFI_START, core.WIFI_STOP, core.WIFI_CONNECT):
        try:
            os.remove(path)
        except OSError:
            pass


def check_external_connect():
    """A connect request dropped by the regular page (POST /wificonnect),
    an alternative to the setup access point's own /connect for whenever
    the regular page is reachable some other way (e.g. Ethernet) while
    Wi-Fi is being set up. Returns (ssid, password) or None."""
    try:
        with open(core.WIFI_CONNECT) as f:
            data = json.load(f)
        os.remove(core.WIFI_CONNECT)
    except (IOError, OSError, ValueError):
        return None
    ssid = str(data.get("ssid") or "").strip()
    return (ssid, str(data.get("password") or "")) if ssid else None


def wait_or_stop(seconds):
    """Sleep up to `seconds`, checking for a stop request every 0.5 s.
    Returns True if a stop was requested."""
    end = time.time() + seconds
    while time.time() < end:
        if stop_requested():
            return True
        time.sleep(min(0.5, max(0, end - time.time())))
    return False


# --------------------------------------------------------------- scanning

def scan_networks(iface):
    """[{"ssid": ..., "signal": dBm or None, "secured": bool}, ...], best
    signal first, one entry per SSID. Empty (not None) on any failure - the
    setup page still offers a manual SSID/password field."""
    if demo():
        core.log("wifi demo: scanning (dummy networks)")
        if wait_or_stop(SCAN_WAIT):
            return []
        return [dict(n) for n in DEMO_NETWORKS]
    run(["wpa_cli", "-i", iface, "scan"])
    if wait_or_stop(SCAN_WAIT):
        return []
    text = output(["wpa_cli", "-i", iface, "scan_results"])
    networks = {}
    if text:
        for line in text.splitlines()[1:]:   # header: bssid / frequency / signal level / flags / ssid
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            try:
                signal = int(parts[2])
            except ValueError:
                signal = None
            ssid = parts[4].strip()
            if not ssid:
                continue
            secured = "WPA" in parts[3] or "WEP" in parts[3]
            if ssid not in networks or (signal is not None and signal > (networks[ssid]["signal"] or -999)):
                networks[ssid] = {"ssid": ssid, "signal": signal, "secured": secured}
    return sorted(networks.values(), key=lambda n: n["signal"] if n["signal"] is not None else -999, reverse=True)


# -------------------------------------------------------------- AP hosting

def write_hostapd_conf(iface):
    with open(HOSTAPD_CONF, "w") as f:
        f.write("interface=%s\ndriver=nl80211\nssid=%s\nhw_mode=g\nchannel=6\n"
                "auth_algs=1\nwmm_enabled=0\nignore_broadcast_ssid=0\n" % (iface, AP_SSID))


def write_dnsmasq_conf(iface):
    with open(DNSMASQ_CONF, "w") as f:
        f.write("interface=%s\nbind-interfaces\nexcept-interface=lo\nno-resolv\n"
                "dhcp-range=%s,%s,255.255.255.0,12h\ndhcp-option=3,%s\ndhcp-option=6,%s\n"
                "address=/#/%s\n" % (iface, AP_DHCP_FROM, AP_DHCP_TO, AP_IP, AP_IP, AP_IP))


_procs = {}


def start_ap(iface):
    if demo():
        core.log("wifi demo: access point not started")
        return
    run(["systemctl", "stop", "wpa_supplicant@%s.service" % iface])
    run(["systemctl", "stop", "wpa_supplicant.service"])
    run(["systemctl", "stop", "dhcpcd.service"])
    run(["ip", "link", "set", iface, "down"])
    run(["ip", "addr", "flush", "dev", iface])
    run(["ip", "link", "set", iface, "up"])
    run(["ip", "addr", "add", AP_IP + "/24", "dev", iface])
    write_hostapd_conf(iface)
    write_dnsmasq_conf(iface)
    _procs["hostapd"] = subprocess.Popen(["hostapd", HOSTAPD_CONF], stdout=_devnull, stderr=_devnull)
    time.sleep(1)
    _procs["dnsmasq"] = subprocess.Popen(["dnsmasq", "-C", DNSMASQ_CONF, "--no-daemon", "--pid-file="],
                                         stdout=_devnull, stderr=_devnull)


def stop_ap(iface):
    if demo():
        return
    for name in ("dnsmasq", "hostapd"):
        p = _procs.pop(name, None)
        if not p:
            continue
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
    run(["ip", "addr", "flush", "dev", iface])
    run(["ip", "link", "set", iface, "down"])


def restore_client(iface):
    if demo():
        return
    run(["ip", "link", "set", iface, "up"])
    run(["systemctl", "start", "dhcpcd.service"])
    run(["systemctl", "start", "wpa_supplicant@%s.service" % iface])
    run(["systemctl", "start", "wpa_supplicant.service"])


# ------------------------------------------------------------------ connect

def _wpa_escape(text):
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _network_block(ssid, password):
    if not password:
        return 'network={\n\tssid="%s"\n\tkey_mgmt=NONE\n}\n' % _wpa_escape(ssid)
    text = output(["wpa_passphrase", ssid, password])
    if not text:
        # no wpa_passphrase (unlikely - it ships with wpasupplicant): fall
        # back to a plain-text psk, which wpa_supplicant also accepts.
        return 'network={\n\tssid="%s"\n\tpsk="%s"\n}\n' % (_wpa_escape(ssid), _wpa_escape(password))
    return re.sub(r"^\s*#psk=.*\n", "", text, flags=re.M)   # drop the plaintext-password comment


def save_network(ssid, password):
    """Add ssid/password to wpa_supplicant.conf, replacing any existing
    entry for the same SSID, so it also reconnects automatically after a
    reboot."""
    try:
        with open(WPA_CONF) as f:
            existing = f.read()
    except IOError:
        existing = "ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\nupdate_config=1\ncountry=US\n"
    header, blocks = [], []
    for part in re.split(r"(network=\{.*?\n\})", existing, flags=re.S):
        if part.startswith("network={"):
            if 'ssid="%s"' % _wpa_escape(ssid) not in part:
                blocks.append(part)
        elif part.strip():
            header.append(part)
    blocks.append(_network_block(ssid, password))
    tmp = WPA_CONF + ".tmp"
    with open(tmp, "w") as f:
        f.write("".join(header).rstrip() + "\n\n" + "\n".join(b.strip() + "\n" for b in blocks))
    os.chmod(tmp, 0o600)   # it holds the Wi-Fi passwords
    os.rename(tmp, WPA_CONF)


def try_connect(iface, ssid, password):
    if demo():
        known = dict((n["ssid"], n) for n in DEMO_NETWORKS).get(ssid)
        ok = (known is not None and not known["secured"]) or password == DEMO_PASSWORD
        core.log("wifi demo: connecting to %s %s" % (ssid, "(will succeed)" if ok else "(will fail)"))
        return not wait_or_stop(DEMO_CONNECT_SECONDS) and ok
    restore_client(iface)
    save_network(ssid, password)
    run(["wpa_cli", "-i", iface, "reconfigure"])
    deadline = time.time() + CONNECT_TIMEOUT
    while time.time() < deadline:
        if stop_requested():
            return False
        if has_ip(iface):
            return probes.check_internet()["state"] in ("ok", "warn")
        time.sleep(1)
    return False


# --------------------------------------------------------- setup web page

AP_STYLE = """
:root{--r:29px;--bw:4px;--acc:#1c6fe8;--acc-l:#80b1f6;--card:#1b1b1b;--line:#2a2a2a;--muted:#999}
*{box-sizing:border-box}
body{font-family:-apple-system,"Segoe UI",Roboto,sans-serif;background:#111;color:#eee;max-width:460px;margin:24px auto;padding:0 16px}
h1{text-align:center;margin:0 0 4px;font-size:1.7em} .note{color:var(--muted);font-size:.9em;text-align:center;margin:0 0 20px}
button{font:inherit;cursor:pointer;border:0;color:#fff}
.card{background:var(--card);border-radius:var(--r);padding:6px 16px;margin-bottom:14px}
.row{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:13px 4px;border-top:1px solid var(--line);text-align:left;width:100%;background:none}
.row:first-child{border-top:0} .row.sel{color:#fff}
.ssid{flex:1;min-width:0;text-align:left;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sig{color:var(--muted);font-size:.82em;flex:none;margin-left:8px}
.lock{flex:none;margin-right:6px;opacity:.7}
.pill{display:block;width:100%;margin:0 0 12px;padding:13px;border-radius:var(--r);font-size:1.05em;font-weight:600;
      background:rgba(28,111,232,.82);border:var(--bw) solid rgba(128,177,246,.82)}
.pill:disabled{opacity:.4}
.pill-s{display:inline-block;padding:9px 18px;border-radius:999px;background:rgba(42,42,42,.82);border:var(--bw) solid rgba(80,80,80,.85);color:#eee;font-size:.9em;width:100%}
input[type=password],input[type=text]{width:100%;padding:11px 14px;margin:8px 0 14px;border-radius:14px;border:var(--bw) solid #555;background:#1a1a1a;color:#eee;font:inherit}
.msg{padding:10px 14px;border-radius:14px;margin:0 0 14px;font-size:.9em}
.msg.err{background:#7a1f1f;border:var(--bw) solid #a84a4a}
.msg.ok{background:#1f6a2f;border:var(--bw) solid #4aa85e}
"""

AP_SCRIPT = """
function $(id){return document.getElementById(id)}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
var NETWORKS = %(networks)s, chosen = null;
function bars(sig){if(sig==null)return"";var n=sig>=-55?4:sig>=-65?3:sig>=-75?2:1;return " "+"\\u2588".repeat(n)+"\\u2591".repeat(4-n)}
function renderList(){
 $("list").innerHTML = NETWORKS.map(function(n,i){
  return '<button type="button" class="row" data-i="'+i+'">'+
   (n.secured?'<span class="lock">&#128274;</span>':'<span class="lock"></span>')+
   '<span class="ssid">'+esc(n.ssid)+'</span><span class="sig">'+esc(bars(n.signal))+'</span></button>'
 }).join("") || '<div class="note" style="margin:16px 4px">No networks found. Enter one below.</div>';
 Array.prototype.forEach.call($("list").querySelectorAll(".row"), function(b){
  b.onclick=function(){select(NETWORKS[+b.dataset.i])}});
}
function select(n){
 chosen = n; $("ssid").value = n.ssid; $("pass").style.display = n.secured ? "block" : "none";
 $("pass").value=""; $("connect").disabled=false; $("form").style.display="block";
 $("form").scrollIntoView({behavior:"smooth", block:"nearest"});
}
$("manual").onclick=function(){select({ssid:"", secured:true}); $("ssid").readOnly=false; $("ssid").focus()};
$("connect").onclick=function(){
 var ssid=$("ssid").value.trim(); if(!ssid)return;
 $("connect").disabled=true; $("connect").textContent="Connecting...";
 var x=new XMLHttpRequest(); x.open("POST","/connect",true);
 x.setRequestHeader("Content-Type","application/x-www-form-urlencoded");
 x.onload=function(){$("msg").className="msg ok";$("msg").style.display="block";
  $("msg").textContent="Trying to connect the Pi to \\u201c"+ssid+"\\u201d. This Wi-Fi network will close now; "+
   "check the Pi's normal page to see if it worked."};
 x.onerror=function(){}; x.send("ssid="+encodeURIComponent(ssid)+"&password="+encodeURIComponent($("pass").value))};
$("stop").onclick=function(){
 var x=new XMLHttpRequest(); x.open("POST","/stop",true); x.send();
 $("msg").className="msg ok"; $("msg").style.display="block"; $("msg").textContent="Wi-Fi setup cancelled.";
};
renderList();
"""

AP_PAGE_TMPL = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>CheckIn WiFi Config</title>
<style>%(style)s</style></head><body>
<h1>CheckIn WiFi Config</h1>
<div class="note">Choose the Wi-Fi network for the Pi to use, then enter its password.</div>
<div id="msg" class="msg" style="display:none"></div>
<div class="card" id="list"></div>
<button type="button" class="pill-s" id="manual" style="margin-bottom:14px">Enter a network name manually</button>
<div class="card" id="form" style="display:none">
 <input type="text" id="ssid" placeholder="Network name" readonly>
 <input type="password" id="pass" placeholder="Password" style="display:none">
 <button type="button" class="pill" id="connect" disabled>Connect</button>
</div>
<button type="button" class="pill-s" id="stop">Cancel Wi-Fi setup</button>
<script>%(script)s</script>
</body></html>"""


def _ap_page(networks):
    # SSIDs come from whoever runs a nearby network: keep "</script>" and friends
    # from ending the script block (JSON stays valid with \u escapes).
    data = json.dumps(networks).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    script = AP_SCRIPT % {"networks": data}
    return (AP_PAGE_TMPL % {"style": AP_STYLE, "script": script}).encode("utf-8")


def ap_expired(deadline):
    return time.time() > deadline


def run_ap_server(networks):
    """Serves the setup page on the access point until a network is chosen
    or setup is cancelled. Returns ("connect", ssid, password) or ("stop", None, None)."""
    result = queue.Queue()
    if demo():   # no access point: only the regular page's network list (wifi_connect) and the stop flag
        while True:
            if stop_requested():
                return ("stop", None, None)
            external = check_external_connect()
            if external:
                return ("connect", external[0], external[1])
            time.sleep(1)
    page = _ap_page(networks)

    class Handler(BaseHTTPRequestHandler):
        timeout = 10     # this server handles one connection at a time: a stalled client mustn't block it

        def _send(self, body, ctype="text/plain; charset=utf-8", status=200):
            if not isinstance(body, bytes):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            # a handful of OS captive-portal probes: send them to the page too
            if self.path.split("?")[0] in ("/", "/generate_204", "/hotspot-detect.html",
                                            "/ncsi.txt", "/connecttest.txt", "/fwlink"):
                self._send(page, "text/html; charset=utf-8")
            else:
                self._send(b"", status=404)

        def do_POST(self):
            try:
                length = max(0, min(int(self.headers.get("Content-Length") or 0), 4096))
                data = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            except (ValueError, IOError):
                data = {}
            if self.path == "/connect":
                ssid = (data.get("ssid") or [""])[0].strip()
                password = (data.get("password") or [""])[0]
                if ssid:
                    result.put(("connect", ssid, password))
                self._send("ok")
            elif self.path == "/stop":
                result.put(("stop", None, None))
                self._send("ok")
            else:
                self._send(b"", status=404)

        def log_message(self, *args):
            pass

    try:
        server = HTTPServer((AP_IP, 80), Handler)
    except OSError:
        return ("stop", None, None)   # couldn't bind the AP IP; give up this round
    t = threading.Thread(target=server.serve_forever)
    t.daemon = True
    t.start()
    deadline = time.time() + AP_TIMEOUT
    try:
        while True:
            try:
                return result.get(timeout=1)
            except queue.Empty:
                if stop_requested():
                    return ("stop", None, None)
                if ap_expired(deadline):
                    core.log("wifi setup: nobody chose a network, the access point is closed")
                    return ("stop", None, None)
                external = check_external_connect()
                if external:
                    return ("connect", external[0], external[1])
    finally:
        server.shutdown()
        server.server_close()


# --------------------------------------------------------------- main loop

_active_iface = [None]   # set while an access point may be up, for graceful_exit()


def graceful_exit(*_):
    """A service stop (uninstall, restart, reboot) mid-setup must not leave
    the Wi-Fi interface stuck in access-point mode; tear it down and hand
    it back to normal client networking."""
    iface = _active_iface[0]
    if iface:
        try:
            stop_ap(iface)
        except Exception:
            pass
        try:
            restore_client(iface)
        except Exception:
            pass
    sys.exit(0)


def setup_cycle(iface):
    """One full Wi-Fi setup session: scan, host, wait for a choice or a
    cancel, try to connect, and on failure loop back to scanning again."""
    _active_iface[0] = iface
    try:
        _setup_cycle(iface)
    finally:
        _active_iface[0] = None


def _setup_cycle(iface):
    while True:
        set_state("scanning")
        networks = scan_networks(iface)
        if stop_requested():
            break
        set_state("hosting", ssid=AP_SSID, networks=networks)
        try:
            start_ap(iface)
        except Exception:
            core.log("wifi setup: could not start the access point")
            break
        action, ssid, password = run_ap_server(networks)
        stop_ap(iface)
        if action != "connect":
            break
        set_state("connecting", ssid=ssid)
        core.log("wifi setup: trying to connect to %s" % ssid)
        ok = try_connect(iface, ssid, password)
        if stop_requested():
            break
        if ok:
            core.log("wifi setup: connected to %s" % ssid)
            set_state("ok", ssid=ssid)
            wait_or_stop(RESULT_PAUSE)
            break
        core.log("wifi setup: could not connect to %s, trying again" % ssid)
        set_state("failed", ssid=ssid)
        if wait_or_stop(RESULT_PAUSE):
            break
    restore_client(iface)
    set_state("idle")
    clear_flags()
