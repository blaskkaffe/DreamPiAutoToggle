#!/usr/bin/env python3
# DreamPi Netswitch add-on - web page to choose DCNow! or DCNET.
# Shows DreamPi's and the modem's live status and internet access, plus an
# optional debug timeline. It only creates/removes the files that
# netswitch_hook.py reads.
# Works on Python 3 and 2.7.
import json
import os
import re
import socket
import sys
import threading
import time

try:
    from http.server import BaseHTTPRequestHandler, HTTPServer
except ImportError:
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer

BASE_DIR = "/opt/dreampi-netswitch"
FLAG = os.path.join(BASE_DIR, "dcnet_mode")
AUTORESET = os.path.join(BASE_DIR, "autoreset")
DEFAULT_DCNET = os.path.join(BASE_DIR, "default_dcnet")
DEBUG_DTMF = os.path.join(BASE_DIR, "debug_dtmf")
STATUS = "/tmp/dreampi-netswitch.active"
STATE = "/tmp/dreampi-netswitch.state"
MODEM = "/tmp/dreampi-netswitch.modem"
DTMF_LOG = "/tmp/dreampi-netswitch-dtmf.log"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 80

INTERNET_EVERY = 30   # seconds between internet checks

_checks = {"internet": {"state": "checking", "text": "Checking...", "time": 0}}
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


def checker():
    while True:
        result = check_internet()
        result["time"] = int(time.time())
        with _checks_lock:
            _checks["internet"] = result
        time.sleep(INTERNET_EVERY)


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
        warnings.append("DCNET unavailable: %s. All calls go to DCNow!" % problem)
    with _checks_lock:
        checks = json.loads(json.dumps(_checks))
    return {"network": "dcnet" if os.path.exists(FLAG) else "dcnow",
            "autoreset": os.path.exists(AUTORESET),
            "default": "dcnet" if os.path.exists(DEFAULT_DCNET) else "dcnow",
            "debug": os.path.exists(DEBUG_DTMF),
            "dreampi": {"state": dstate, "text": dtext},
            "modem": {"text": mtext, "since": msince},
            "internet": checks["internet"],
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
 .rows{cursor:pointer;user-select:none} .rows .more{display:none} .rows.open .more{display:flex}
 .arrow{color:#aaa;flex:none;margin-left:8px;font-size:1.1em;transition:transform .15s} .rows.open .arrow{transform:rotate(90deg)}
 .dot{display:inline-block;width:.65em;height:.65em;border-radius:50%;margin-right:8px;background:#888}
 .ok{background:#2c2} .busy,.warn{background:#e0b400} .call{background:#b04cff} .bad,.off{background:#d33}
 .call-dcnow{background:#ff7a1a} .call-dcnet{background:#2a7bff}
 .sub{color:#888;font-size:.85em}
 .now{font-size:1.5em;margin:14px 0;padding:16px;border-radius:10px;text-align:center;background:#9e4f10}
 .now.dcnet{background:#1c4f9e}
 button{font-size:1.1em;width:100%;padding:14px;margin:5px 0;border:0;border-radius:10px;cursor:pointer}
 .dcnow-b{background:#e8761c;color:#fff} .dcnet-b{background:#1c6fe8;color:#fff}
 .toggle{background:#2a2a2a;color:#eee;font-size:.95em;text-align:left}
 .prefs{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin:10px 2px 0}
 .pref{display:flex;align-items:center;gap:9px;color:#ccc}
 .prefs button{margin:0;padding:0;border:0}
 .prefs .switch{position:relative;width:96px;height:32px;border-radius:16px;background:#e8761c;color:#fff;font-size:.8em;font-weight:bold;transition:background .2s}
 .switch .knob{position:absolute;top:3px;left:67px;width:26px;height:26px;border-radius:50%;background:#fff;transition:left .2s;box-shadow:0 1px 3px rgba(0,0,0,.5)}
 .switch .lbl{position:absolute;top:0;bottom:0;left:10px;line-height:32px}
 .switch.dcnet{background:#1c6fe8} .switch.dcnet .knob{left:3px} .switch.dcnet .lbl{left:auto;right:12px}
 .prefs .check{width:26px;height:26px;border-radius:6px;border:2px solid #888;background:transparent;color:transparent;font-size:1em;line-height:1}
 .prefs .check.on{color:#fff}
 .prefs .check.on.dcnow{background:#e8761c;border-color:#e8761c} .prefs .check.on.dcnet{background:#1c6fe8;border-color:#1c6fe8}
 .warnbox{background:#7a1f1f;padding:11px;border-radius:8px;margin:8px 0;font-size:.9em}
 table{width:100%;border-collapse:collapse;font-size:.88em}
 td{padding:5px 3px;border-top:1px solid #2a2a2a;vertical-align:top} td.n{color:#eee;white-space:nowrap;word-break:keep-all;overflow-wrap:normal;width:1%;padding-right:12px}
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
<div class="rows" id="rows" title="Show or hide details">
 <div class="row"><span class="k">DreamPi</span><span class="v"><span class="dot" id="d-dot"></span><span id="d-text">...</span></span><span class="arrow">&#9656;</span></div>
 <div class="row more"><span class="k">Modem</span><span class="v"><span id="m-text">...</span> <span class="sub" id="m-since"></span></span></div>
 <div class="row more"><span class="k">Internet</span><span class="v"><span class="dot" id="i-dot"></span><span id="i-text">...</span></span></div>
</div>
<div class="now" id="net">Selected network:<br><b id="net-name">...</b></div>
<form method="post" action="/dcnow"><button class="dcnow-b">DCNow! / DreamPi</button></form>
<form method="post" action="/dcnet"><button class="dcnet-b">DCNET / FLYCAST</button></form>
<div class="prefs">
 <form method="post" action="/default" class="pref"><span>Default network</span>
  <button class="switch" id="default-b" type="submit" title="Network that 111-1111 resets to"><span class="lbl" id="default-l">DCNow!</span><span class="knob"></span></button></form>
 <form method="post" action="/autoreset" class="pref" title="Switch back to the default network when openMenu dials 111-1111"><span>Auto reset</span>
  <button class="check" id="reset-b" type="submit">&#10003;</button></form>
</div>

<h2>Phone numbers</h2>
<table>
<tr><td class="n">111-1111</td><td>Always directs to DCNow! for compatibility with openMenu and standard ISP configs.<br>
<span class="sub">When &quot;Auto reset&quot; is enabled, dialing it also resets the network to the default network.<span id="reset-note"></span></span></td></tr>
<tr><td class="n">222-2222</td><td>Selects DCNow! / DreamPi and connects to it</td></tr>
<tr><td class="n">333-3333</td><td>Selects DCNET / FLYCAST and connects to it</td></tr>
<tr><td class="n">Any other</td><td>Connects to the currently selected network.<br>
<span class="sub">Set your Dreamcast ISP config to any 7-digit number to use this feature.</span></td></tr>
</table>

<div class="small" style="margin-top:26px"><button class="toggle" id="show-debug" type="button">Debug log &#9656;</button></div>
<div id="debug" style="display:none">
<div class="note">Records every modem event, DreamPi message and routing decision with
millisecond timing. Turn recording on, then dial.</div>
<div class="small"><form method="post" action="/debug" style="display:inline"><button class="toggle" id="debug-b">Recording</button></form>
<span id="log-tools" style="display:none"><form method="post" action="/clearlog" style="display:inline"><button class="toggle">Clear</button></form>
<a href="/dtmf" target="_blank">Open as text</a> <label class="sub"><input type="checkbox" id="follow" checked> Follow</label></span></div>
<pre id="log" style="display:none"></pre>
</div>

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
 $("net").className="now "+d.network; $("net-name").textContent=d.network=="dcnet"?"DCNET":"DCNow!";
 var defName=d.default=="dcnet"?"DCNET":"DCNow!";
 $("default-b").className="switch "+d.default; $("default-l").textContent=d.default=="dcnet"?"DCNET":"DCNow!";
 $("reset-b").className="check "+d.default+(d.autoreset?" on":"");
 $("reset-note").textContent=" (Auto reset is "+(d.autoreset?"on, default: "+defName:"off")+")";
 $("debug-b").innerHTML=(d.debug?"&#9745; Recording":"&#9744; Recording (off)");
 $("log-tools").style.display=d.debug?"inline":"none";
 $("log").style.display=(d.debug||logSize)?"block":"none";
 debugOn=d.debug;
}
var logSize=0,debugOn=false,logBusy=false,debugOpen=false;
$("rows").onclick=function(){this.classList.toggle("open")};
$("show-debug").onclick=function(){debugOpen=!debugOpen;
 $("debug").style.display=debugOpen?"block":"none";
 this.innerHTML=debugOpen?"Debug log &#9662;":"Debug log &#9656;";
 if(debugOpen){pollLog();var el=$("log");el.scrollTop=el.scrollHeight}};
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
            self.send("network=%s\ndefault=%s\nautoreset=%s\ndreampi=%s\nmodem=%s\ninternet=%s\n" % (
                d["network"], d["default"], "on" if d["autoreset"] else "off", d["dreampi"]["text"],
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
        elif self.path == "/clearlog":
            if os.path.exists(DTMF_LOG):
                os.remove(DTMF_LOG)
            debug_log("web page: log cleared")
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
