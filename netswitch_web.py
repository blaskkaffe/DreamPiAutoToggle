#!/usr/bin/env python3
# DreamPi Netswitch add-on - web page to choose DC Now or DCNet.
# Shows DreamPi's and the modem's live status, internet access and whether
# the game ports from the Dreamcast Live connection guide have a forwarding
# path. It only creates/removes the files that netswitch_hook.py reads.
# Works on Python 3 and 2.7.
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time

try:
    from http.server import BaseHTTPRequestHandler, HTTPServer
except ImportError:
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
try:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    from urllib.parse import urljoin
except ImportError:
    from urllib2 import Request, urlopen, HTTPError
    from urlparse import urljoin

BASE_DIR = "/opt/dreampi-netswitch"
FLAG = os.path.join(BASE_DIR, "dcnet_mode")
AUTORESET = os.path.join(BASE_DIR, "autoreset")
DEBUG_DTMF = os.path.join(BASE_DIR, "debug_dtmf")
STATUS = "/tmp/dreampi-netswitch.active"
STATE = "/tmp/dreampi-netswitch.state"
MODEM = "/tmp/dreampi-netswitch.modem"
DTMF_LOG = "/tmp/dreampi-netswitch-dtmf.log"
PEERS = "/etc/ppp/peers/dreamcast"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 80

# Games and ports from https://dreamcastlive.net/connection-guide/
GAMES = [
    ("Alien Front Online", [("UDP", 7980, 7980)]),
    ("ChuChu Rocket!", [("UDP", 9789, 9789)]),
    ("ClassiCube", [("UDP", 25565, 25565)]),
    ("Dee Dee Planet", [("UDP", 9879, 9879)]),
    ("Driving Strikers", [("UDP", 30099, 30099)]),
    ("Floigan Bros.", [("TCP", 37001, 37001)]),
    ("Internet Game Pack", [("UDP", 5656, 5656), ("TCP", 5011, 5011), ("TCP", 10500, 10503)]),
    ("NBA/NFL/NCAA 2K series", [("UDP", 5502, 5503), ("UDP", 5656, 5656), ("TCP", 5011, 5011),
                                ("TCP", 6666, 6666)]),
    ("The Next Tetris: Online Edition", [("TCP", 3512, 3512), ("UDP", 3512, 3512)]),
    ("Ooga Booga", [("UDP", 6001, 6001)]),
    ("PBA Tour Bowling 2001", [("TCP", 2300, 2400), ("UDP", 2300, 2400), ("UDP", 6500, 6500),
                               ("TCP", 47624, 47624), ("UDP", 47624, 47624), ("UDP", 13139, 13139)]),
    ("Starlancer", [("TCP", 2300, 2400), ("UDP", 2300, 2400), ("UDP", 6500, 6500),
                    ("TCP", 47624, 47624), ("UDP", 47624, 47624)]),
    ("World Series Baseball 2K2", [("UDP", 37171, 37171), ("UDP", 13713, 13713)]),
    ("Worms World Party", [("TCP", 17219, 17219)]),
]

INTERNET_EVERY = 30   # seconds between internet checks
PORTS_EVERY = 600     # seconds between port checks

_checks = {"internet": {"state": "checking", "text": "Checking...", "time": 0},
           "ports": {"state": "checking", "text": "Checking...", "games": [], "time": 0}}
_checks_lock = threading.Lock()
_recheck = threading.Event()


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
    """None when DreamPi's DCNet support is switched on, else a reason."""
    if os.path.exists("/boot/noautoupdates.txt"):
        return ("/boot/noautoupdates.txt exists, so DreamPi skips netlink_config.ini "
                "and DCNet stays off")
    for path in ("/boot/netlink_config.ini", "/home/pi/dreampi/netlink_config.ini"):
        if os.path.isfile(path):
            break
    else:
        return "netlink_config.ini not found, so DCNet is off"
    text = read_file(path) or ""
    section = re.search(r"^\[DCNet\](.*?)(?=^\[|\Z)", text, re.M | re.S)
    if not section or not re.search(r"^\s*enabled\s*=\s*yes\s*$", section.group(1), re.M):
        return "DCNet is not enabled in " + path + " ([DCNet] enabled = yes)"
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
        net = {"dcnow": "DC Now", "dcnet": "DCNet"}.get(state[5:], state[5:])
        return "call", "In a call: " + net
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


# --------------------------------------------------------------- port check

def vpn_address():
    try:
        out = subprocess.check_output(["ip", "-4", "-o", "addr", "show", "dev", "tun0"],
                                      stderr=subprocess.STDOUT).decode("utf-8", "replace")
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
        return m.group(1) if m else None
    except Exception:
        return None


def dreamcast_ip():
    """The address DreamPi gives the Dreamcast, from its PPP peers file."""
    for line in (read_file(PEERS) or "").splitlines():
        m = re.match(r"^\s*[\d.]+:([\d.]+)\s*$", line)
        if m:
            return m.group(1)
    return None


def find_igd():
    """Find the router's UPnP port mapping service. Returns (url, service type)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(3)
    locations = []
    try:
        for st in ("urn:schemas-upnp-org:device:InternetGatewayDevice:1",
                   "urn:schemas-upnp-org:device:InternetGatewayDevice:2"):
            msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
                   "MAN: \"ssdp:discover\"\r\nMX: 2\r\nST: %s\r\n\r\n" % st)
            s.sendto(msg.encode("ascii"), ("239.255.255.250", 1900))
        while True:
            data = s.recv(4096).decode("utf-8", "replace")
            m = re.search(r"^location:\s*(\S+)", data, re.I | re.M)
            if m and m.group(1) not in locations:
                locations.append(m.group(1))
    except socket.timeout:
        pass
    except Exception:
        pass
    finally:
        s.close()
    for location in locations:
        try:
            xml = urlopen(location, timeout=4).read().decode("utf-8", "replace")
        except Exception:
            continue
        for service in re.findall(r"<service>(.*?)</service>", xml, re.S):
            stype = re.search(r"<serviceType>\s*(.*?)\s*</serviceType>", service)
            ctrl = re.search(r"<controlURL>\s*(.*?)\s*</controlURL>", service)
            if stype and ctrl and ("WANIPConnection" in stype.group(1)
                                   or "WANPPPConnection" in stype.group(1)):
                return urljoin(location, ctrl.group(1)), stype.group(1)
    return None


def upnp_mapping(igd, proto, port):
    """Internal IP a router port is forwarded to, or None if not forwarded."""
    url, stype = igd
    body = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            '<u:GetSpecificPortMappingEntry xmlns:u="%s"><NewRemoteHost></NewRemoteHost>'
            '<NewExternalPort>%d</NewExternalPort><NewProtocol>%s</NewProtocol>'
            '</u:GetSpecificPortMappingEntry></s:Body></s:Envelope>' % (stype, port, proto))
    req = Request(url, body.encode("utf-8"), {
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPAction": '"%s#GetSpecificPortMappingEntry"' % stype})
    try:
        reply = urlopen(req, timeout=4).read().decode("utf-8", "replace")
    except HTTPError:
        return None  # 714 NoSuchEntryInArray: not forwarded
    m = re.search(r"<NewInternalClient>\s*([\d.]+)\s*</NewInternalClient>", reply)
    return m.group(1) if m else None


def fmt_ports(ranges):
    return ", ".join("%s %s" % (p, a if a == b else "%d-%d" % (a, b)) for p, a, b in ranges)


def check_ports():
    games = [{"name": n, "ports": fmt_ports(r), "state": "unknown", "text": ""} for n, r in GAMES]
    tun = vpn_address()
    if tun:
        for g in games:
            g["state"], g["text"] = "ok", "Via VPN"
        return {"state": "ok", "games": games,
                "text": "DreamPi's VPN tunnel is up (%s). Incoming game traffic reaches the "
                        "Dreamcast through the VPN, so router port forwarding isn't needed." % tun}
    igd = find_igd()
    if not igd:
        return {"state": "unknown", "games": games,
                "text": "No VPN tunnel, and the router doesn't answer UPnP queries, so the "
                        "forwards can't be checked. If you use a DMZ or manual forwards, "
                        "check them in the router."}
    dc = dreamcast_ip()
    cache = {}
    for g, (name, ranges) in zip(games, GAMES):
        total = missing = elsewhere = 0
        for proto, a, b in ranges:
            for port in range(a, b + 1):
                key = (proto, port)
                if key not in cache:
                    try:
                        cache[key] = upnp_mapping(igd, proto, port)
                    except Exception:
                        cache[key] = None
                total += 1
                target = cache[key]
                if target is None:
                    missing += 1
                elif dc and target != dc:
                    elsewhere += 1
        if missing == 0 and elsewhere == 0:
            g["state"], g["text"] = "ok", "Forwarded"
            continue
        parts = []
        if missing:
            parts.append("not forwarded" if missing == total else
                         "%d of %d ports not forwarded" % (missing, total))
        if elsewhere:
            parts.append("forwarded to another device" if elsewhere == total else
                         "%d of %d ports go to another device" % (elsewhere, total))
        text = ", ".join(parts)
        g["text"] = text[0].upper() + text[1:]
        g["state"] = "bad" if missing + elsewhere == total else "warn"
    ok = sum(1 for g in games if g["state"] == "ok")
    return {"state": "ok" if ok == len(games) else "warn", "games": games,
            "text": "No VPN tunnel. Router forwards checked over UPnP (Dreamcast IP %s): "
                    "%d of %d games fully forwarded. A DMZ isn't visible over UPnP."
                    % (dc or "unknown", ok, len(games))}


def checker():
    last_ports = 0
    while True:
        forced = _recheck.is_set()
        _recheck.clear()
        result = check_internet()
        result["time"] = int(time.time())
        with _checks_lock:
            _checks["internet"] = result
        if forced or time.time() - last_ports >= PORTS_EVERY:
            try:
                result = check_ports()
            except Exception as e:
                result = {"state": "unknown", "games": [], "text": "Port check failed: %s" % e}
            result["time"] = int(time.time())
            last_ports = time.time()
            with _checks_lock:
                _checks["ports"] = result
        _recheck.wait(INTERNET_EVERY)


# -------------------------------------------------------------------- page

def api_state():
    dstate, dtext = dreampi_state()
    mtext, msince = modem_state()
    warnings = []
    problem = hook_problem()
    if problem:
        warnings.append("Add-on not active: %s. Calls are not affected until it is." % problem)
    problem = dcnet_problem()
    if problem:
        warnings.append("DCNet unavailable: %s. All calls go to DC Now." % problem)
    with _checks_lock:
        checks = json.loads(json.dumps(_checks))
    return {"network": "dcnet" if os.path.exists(FLAG) else "dcnow",
            "autoreset": os.path.exists(AUTORESET),
            "debug": os.path.exists(DEBUG_DTMF),
            "dreampi": {"state": dstate, "text": dtext},
            "modem": {"text": mtext, "since": msince},
            "internet": checks["internet"], "ports": checks["ports"],
            "warnings": warnings, "now": int(time.time())}


PAGE = u"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DreamPi</title>
<style>
 body{font-family:sans-serif;background:#111;color:#eee;max-width:460px;margin:28px auto;padding:0 16px}
 h1{text-align:center;margin-bottom:14px}
 .rows{background:#1d1d1d;border-radius:10px;padding:6px 12px;margin-bottom:16px}
 .row{display:flex;align-items:baseline;padding:7px 0;border-top:1px solid #2a2a2a}
 .row:first-child{border-top:0}
 .row .k{width:84px;color:#999;flex:none} .row .v{flex:1}
 .dot{display:inline-block;width:.65em;height:.65em;border-radius:50%;margin-right:8px;background:#888}
 .ok{background:#2c2} .busy,.warn{background:#e0b400} .call{background:#39f} .bad,.off{background:#d33}
 .sub{color:#888;font-size:.85em}
 .now{font-size:1.5em;margin:14px 0;padding:16px;border-radius:10px;text-align:center;background:#9e4f10}
 .now.dcnet{background:#1c4f9e}
 button{font-size:1.1em;width:100%;padding:14px;margin:5px 0;border:0;border-radius:10px;cursor:pointer}
 .dcnow-b{background:#e8761c;color:#fff} .dcnet-b{background:#1c6fe8;color:#fff}
 .toggle{background:#2a2a2a;color:#eee;font-size:.95em;text-align:left}
 .warnbox{background:#7a1f1f;padding:11px;border-radius:8px;margin:8px 0;font-size:.9em}
 table{width:100%;border-collapse:collapse;font-size:.88em}
 td{padding:5px 3px;border-top:1px solid #2a2a2a;vertical-align:top} td.n{color:#eee}
 h2{font-size:1em;color:#bbb;margin:22px 0 6px}
 .note{color:#999;font-size:.85em;margin:4px 0 8px}
 .small button{font-size:.85em;padding:8px;width:auto} a{color:#8bf}
 #log{background:#0a0a0a;border:1px solid #2a2a2a;border-radius:8px;padding:8px;font-size:11px;line-height:1.45;
      height:55vh;overflow:auto;white-space:pre-wrap;word-break:break-all;margin-top:8px}
 #log .dtmf{color:#6f6;font-weight:bold} #log .route{color:#8bf} #log .web{color:#e0b400}
 #log .modem{color:#aaa} #log .dim{color:#555} #log .err{color:#f66}
</style></head><body>
<h1>DreamPi</h1>
<div id="warnings"></div>
<div class="rows">
 <div class="row"><span class="k">DreamPi</span><span class="v"><span class="dot" id="d-dot"></span><span id="d-text">...</span></span></div>
 <div class="row"><span class="k">Modem</span><span class="v"><span id="m-text">...</span> <span class="sub" id="m-since"></span></span></div>
 <div class="row"><span class="k">Internet</span><span class="v"><span class="dot" id="i-dot"></span><span id="i-text">...</span></span></div>
 <div class="row"><span class="k">Ports</span><span class="v"><span class="dot" id="p-dot"></span><span id="p-text">...</span></span></div>
</div>
<div class="now" id="net">Selected network:<br><b id="net-name">...</b></div>
<form method="post" action="/dcnow"><button class="dcnow-b">Use DC Now (default)</button></form>
<form method="post" action="/dcnet"><button class="dcnet-b">Use DCNet</button></form>
<form method="post" action="/autoreset"><button class="toggle" id="reset-b">Reset to DC Now when openMenu (111-1111) connects</button></form>

<h2>Numbers</h2>
<table>
<tr><td class="n">111-1111</td><td>openMenu. Always DC Now<span id="reset-note"></span></td></tr>
<tr><td class="n">222-2222</td><td>Selects DC Now and connects to it</td></tr>
<tr><td class="n">333-3333</td><td>Selects DCNet and connects to it</td></tr>
<tr><td class="n">Any other</td><td>Connects to the selected network</td></tr>
</table>

<h2>Game ports</h2>
<div class="note" id="ports-note"></div>
<table id="ports"></table>
<div class="small"><form method="post" action="/recheck"><button class="toggle">Check again</button></form></div>

<h2>Debug log</h2>
<div class="note">Records every modem event, DreamPi message and routing decision with
millisecond timing. Turn it on, then dial.</div>
<div class="small"><form method="post" action="/debug" style="display:inline"><button class="toggle" id="debug-b">Debug log</button></form>
<span id="log-tools" style="display:none"><form method="post" action="/clearlog" style="display:inline"><button class="toggle">Clear</button></form>
<a href="/dtmf" target="_blank">Open as text</a> <label class="sub"><input type="checkbox" id="follow" checked> Follow</label></span></div>
<pre id="log" style="display:none"></pre>

<script>
function $(id){return document.getElementById(id)}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function ago(t,now){if(!t)return"";var s=Math.max(0,now-t);
 if(s<60)return"("+s+"s ago)";if(s<3600)return"("+Math.floor(s/60)+" min ago)";return"("+Math.floor(s/3600)+" h ago)"}
function dot(el,state){el.className="dot "+(state||"")}
function render(d){
 $("warnings").innerHTML=d.warnings.map(function(w){return '<div class="warnbox">'+esc(w)+'</div>'}).join("");
 dot($("d-dot"),d.dreampi.state); $("d-text").textContent=d.dreampi.text;
 $("m-text").textContent=d.modem.text; $("m-since").textContent=ago(d.modem.since,d.now);
 dot($("i-dot"),d.internet.state); $("i-text").textContent=d.internet.text;
 var ok=0; d.ports.games.forEach(function(g){if(g.state=="ok")ok++});
 dot($("p-dot"),d.ports.state);
 $("p-text").textContent=d.ports.games.length?(ok+" of "+d.ports.games.length+" games ready"):d.ports.text;
 $("ports-note").textContent=d.ports.text+(d.ports.time?" Checked "+ago(d.ports.time,d.now).replace(/[()]/g,"")+".":"");
 $("ports").innerHTML=d.ports.games.map(function(g){return '<tr><td class="n"><span class="dot '+esc(g.state)+
  '"></span>'+esc(g.name)+'<div class="sub">'+esc(g.ports)+'</div></td><td>'+esc(g.text)+'</td></tr>'}).join("");
 $("net").className="now "+d.network; $("net-name").textContent=d.network=="dcnet"?"DCNet":"DC Now";
 $("reset-b").innerHTML=(d.autoreset?"&#9745;":"&#9744;")+" Reset to DC Now when openMenu (111-1111) connects";
 $("reset-note").textContent=d.autoreset?", and resets the selection":"";
 $("debug-b").innerHTML=(d.debug?"&#9745;":"&#9744;")+" Debug log "+(d.debug?"(recording)":"(off)");
 $("log-tools").style.display=d.debug?"inline":"none";
 $("log").style.display=(d.debug||logSize)?"block":"none";
 debugOn=d.debug;
}
var logSize=0,debugOn=false,logBusy=false;
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
 if(logBusy||(!debugOn&&logSize))return; logBusy=true;
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
Array.prototype.forEach.call(document.forms,function(f){f.onsubmit=function(e){e.preventDefault();
 var x=new XMLHttpRequest();x.open("POST",f.getAttribute("action"),true);
 x.onload=function(){refresh();pollLog()};x.send()}});
refresh(); setInterval(refresh,1000);
pollLog(); setInterval(pollLog,700);
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def send(self, body, ctype):
        if not isinstance(body, bytes):
            body = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api":
            self.send(json.dumps(api_state()), "application/json")
        elif self.path.startswith("/log"):
            m = re.search(r"from=(-?\d+)", self.path)
            self.send(json.dumps(read_log(int(m.group(1)) if m else 0)), "application/json")
        elif self.path == "/status":
            d = api_state()
            self.send("network=%s\nautoreset=%s\ndreampi=%s\nmodem=%s\ninternet=%s\n" % (
                d["network"], "on" if d["autoreset"] else "off", d["dreampi"]["text"],
                d["modem"]["text"], d["internet"]["text"]), "text/plain; charset=utf-8")
        elif self.path == "/dtmf":
            try:
                with open(DTMF_LOG, "rb") as f:
                    body = f.read()
            except IOError:
                body = b"No DTMF log yet. Enable the debug log and dial.\n"
            self.send(body, "text/plain; charset=utf-8")
        else:
            self.send(PAGE, "text/html; charset=utf-8")

    def do_POST(self):
        if self.path == "/dcnet":
            open(FLAG, "w").close()
            debug_log("web page: DCNet selected")
        elif self.path == "/dcnow":
            if os.path.exists(FLAG):
                os.remove(FLAG)
            debug_log("web page: DC Now selected")
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
                          ("DCNet" if os.path.exists(FLAG) else "DC Now"))
        elif self.path == "/clearlog":
            if os.path.exists(DTMF_LOG):
                os.remove(DTMF_LOG)
            debug_log("web page: log cleared")
        elif self.path == "/recheck":
            _recheck.set()
        self.send_response(303)  # back to the page when JavaScript is off
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    t = threading.Thread(target=checker)
    t.daemon = True
    t.start()
    HTTPServer(("", PORT), Handler).serve_forever()
