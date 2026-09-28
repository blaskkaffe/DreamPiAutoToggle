#!/usr/bin/env python3
# DreamPi Netswitch add-on - web page to choose DC Now or DCNet.
# It only creates/removes the files that netswitch_hook.py reads.
# Works on Python 3 and 2.7.
import os
import re
import sys

try:
    from http.server import BaseHTTPRequestHandler, HTTPServer
except ImportError:
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer

BASE_DIR = "/opt/dreampi-netswitch"
FLAG = os.path.join(BASE_DIR, "dcnet_mode")
AUTORESET = os.path.join(BASE_DIR, "autoreset")
STATUS = "/tmp/dreampi-netswitch.active"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 80

PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DreamPi network</title>
<style>
 body{{font-family:sans-serif;background:#111;color:#eee;max-width:440px;margin:32px auto;padding:0 16px;text-align:center}}
 .now{{font-size:1.6em;margin:20px 0;padding:18px;border-radius:10px;background:{color}}}
 button{{font-size:1.15em;width:100%;padding:15px;margin:6px 0;border:0;border-radius:10px;cursor:pointer}}
 .dcnow{{background:#e8761c;color:#fff}} .dcnet{{background:#1c6fe8;color:#fff}}
 .toggle{{background:#2a2a2a;color:#eee;font-size:1em;text-align:left}}
 .warn{{background:#7a1f1f;padding:12px;border-radius:8px;margin-top:16px;font-size:.9em;text-align:left}}
 table{{width:100%;margin-top:22px;border-collapse:collapse;font-size:.9em;text-align:left;color:#bbb}}
 td{{padding:5px 4px;border-top:1px solid #2a2a2a}} td:first-child{{white-space:nowrap;color:#eee}}
</style></head><body>
<h1>DreamPi</h1>
{warning}
<div class="now">Selected network:<br><b>{active}</b></div>
<form method="post" action="/dcnow"><button class="dcnow">Use DC Now (default)</button></form>
<form method="post" action="/dcnet"><button class="dcnet">Use DCNet</button></form>
<form method="post" action="/autoreset"><button class="toggle">{box} Reset to DC Now when openMenu (111-1111) connects</button></form>
<table>
<tr><td>111-1111</td><td>openMenu. Always DC Now{reset_note}</td></tr>
<tr><td>222-2222</td><td>Selects DC Now and connects to it</td></tr>
<tr><td>333-3333</td><td>Selects DCNet and connects to it</td></tr>
<tr><td>Any other</td><td>Connects to the selected network</td></tr>
</table>
</body></html>"""


def hook_problem():
    """None when DreamPi is running with the hook loaded, else a reason."""
    try:
        with open(STATUS) as f:
            status = f.read().strip()
    except IOError:
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
    try:
        with open(path) as f:
            text = f.read()
    except IOError:
        return "could not read " + path
    section = re.search(r"^\[DCNet\](.*?)(?=^\[|\Z)", text, re.M | re.S)
    if not section or not re.search(r"^\s*enabled\s*=\s*yes\s*$", section.group(1), re.M):
        return "DCNet is not enabled in " + path + " ([DCNet] enabled = yes)"
    return None


class Handler(BaseHTTPRequestHandler):
    def send_page(self):
        dcnet = os.path.exists(FLAG)
        reset = os.path.exists(AUTORESET)
        warning = ""
        problem = hook_problem()
        if problem:
            warning += ('<div class="warn"><b>Add-on not active:</b> %s. '
                        'Calls are not affected until it is.</div>' % problem)
        problem = dcnet_problem()
        if problem:
            warning += ('<div class="warn"><b>DCNet unavailable:</b> %s. '
                        'All calls go to DC Now.</div>' % problem)
        body = PAGE.format(active="DCNet" if dcnet else "DC Now",
                           color="#1c4f9e" if dcnet else "#9e4f10",
                           box="&#9745;" if reset else "&#9744;",
                           reset_note=", and resets the selection" if reset else "",
                           warning=warning).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/status":
            body = ("network=%s\nautoreset=%s\n" % (
                "dcnet" if os.path.exists(FLAG) else "dcnow",
                "on" if os.path.exists(AUTORESET) else "off")).encode("ascii")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_page()

    def do_POST(self):
        if self.path == "/dcnet":
            open(FLAG, "w").close()
        elif self.path == "/dcnow" and os.path.exists(FLAG):
            os.remove(FLAG)
        elif self.path == "/autoreset":
            if os.path.exists(AUTORESET):
                os.remove(AUTORESET)
            else:
                open(AUTORESET, "w").close()
        self.send_response(303)  # back to the page, so refresh doesn't resend
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("", PORT), Handler).serve_forever()
