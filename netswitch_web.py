#!/usr/bin/env python3
# DreamPi Netswitch add-on - web page to choose DCNow! or DCNET.
# Shows DreamPi's and the modem's live status and internet access, plus an
# optional debug timeline. It only creates/removes the files that
# netswitch_hook.py reads. This module is the HTTP side (page, API, HTTPS,
# watchdog); settings and state are in netswitch_core.py, the optional features in modules/ (netswitch_modules.py loads them), measurements in
# netswitch_probes.py. Works on Python 3 and 2.7.
import gzip
import io
import json
import os
import re
import socket
import ssl
import sys
import threading
import time
import traceback
try:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from socketserver import ThreadingMixIn
except ImportError:
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
    from SocketServer import ThreadingMixIn

import netswitch_core as core
import netswitch_modules as modules
import netswitch_probes as probes
import netswitch_security as security
import netswitch_update as updater

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
PORT = 80
HTTPS_PORT = 443   # 0 = no HTTPS; both can be given on the command line: netswitch_web.py [port] [https port]
CERT = os.path.join(core.BASE_DIR, "https.crt")   # self-signed, made by install.sh
KEY = os.path.join(core.BASE_DIR, "https.key")


def _dot_look(dstate):
    """What the DreamPi dot previews: a plain look for the state. The LED module replaces it with the look of the
    LED message that is showing (its api() hook), so the dot still says something without it."""
    dcnet = os.path.exists(core.FLAG)
    plain = {"ok": ("#1c6fe8" if dcnet else "#ff8c00", "breathe"), "busy": ("#ffd000", "breathe"), "off": ("#ff0000", "blink"),
             "call-dcnow": ("#ff8c00", "solid"), "call-dcnet": ("#0046ff", "solid"), "call": ("#aa00ff", "solid"),
             "unknown": ("#3c3c3c", "solid")}.get(dstate)
    return {"color": plain[0], "effect": plain[1], "speed": "slow"} if plain else None


def api_state():
    dstate, dtext = core.dreampi_state()
    mtext, msince = core.modem_state()
    warnings = []
    problem = core.hook_problem()
    if problem:
        warnings.append("Add-on not active: %s. Calls are not affected until it is." % problem)
    problem = core.dcnet_problem()
    if problem:
        warnings.append("DCNET unavailable: %s. All calls go to DCNow!" % problem)
    with probes._checks_lock:
        checks = json.loads(json.dumps(probes._checks))
    pi = checks.get("pi", {})
    if pi.get("undervoltage"):
        warnings.append("Power: the Pi is getting too little power (under-voltage). Use a stronger power "
                        "supply or a shorter, thicker cable; this can make the Pi unstable or drop off the network.")
    elif pi.get("problem"):
        warnings.append("Too hot: the Pi is at %.0f\u00b0C and slows itself down. Give it more air or a heatsink."
                        % (pi.get("temp") or 0))
    net = core.network_state()
    if net and not net.get("network"):
        warnings.append("No network: the Pi has no working network connection.")
    elif net and net.get("internet") is False:
        why = "name lookups (DNS) fail" if "DNS" in checks["internet"]["text"] \
            else "the network works, but the internet can't be reached"
        warnings.append("No internet: %s. Dreamcast games can't get online right now." % why)
    plugged = probes.modem_plugged()
    compat, label = probes.modem_compat(probes._usb_info(probes.modem_port()))
    if plugged is False:
        warnings.append("Modem not detected: its USB serial port is gone. Check the cable/connection.")
    elif compat is False:
        warnings.append("Modem: %s is known not to work reliably with DreamPi. "
                        "See the Modem row in Settings." % label)
    d = {"network": "dcnet" if os.path.exists(core.FLAG) else "dcnow",
         "dreampi": {"state": dstate, "text": dtext, "look": _dot_look(dstate)},
         "modem": {"text": mtext, "since": msince, "plugged": plugged, "label": label, "compat": compat},
         "internet": checks["internet"],
         "pi": {"state": pi.get("state"), "text": pi.get("text"), "line1": pi.get("line1"),
                "line2": pi.get("line2"), "warn": pi.get("warn")},
         "hangup": {"busy": probes._hangup["busy"], "text": probes._hangup["text"]},
         "pin": security.pin_required(),     # the page asks for it before update / restart / Wi-Fi connect
         "warnings": warnings, "now": int(time.time())}
    modules.apply_api(d, warnings)          # what the enabled modules add: debug, wifi, the dot's LED look ...
    return d


PAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "page")


BASE_PAGE_FILES = ("index.html", "page.css", "page.js")


def build_page():
    """The page is one document: page/index.html with page/page.css and page/page.js put in where it says
    @@CSS@@ and @@JS@@ (one request, kept in memory as PAGE_BYTES). Edit those files, not this module. The
    enabled modules add themselves (netswitch_modules.page_parts()): their markup at the @@SLOT:name@@ markers,
    their styles after page.css and their script after page.js. Without a module its markers are just empty."""
    def part(name):
        with io.open(os.path.join(PAGE_DIR, name), encoding="utf-8", newline="") as f:
            return f.read()
    extra = modules.page_parts()
    html = part("index.html").replace("@@CSS@@", part("page.css") + "\n" + extra["css"]).replace("@@JS@@", part("page.js") + "\n" + extra["js"])
    for name, text in extra["slots"].items():
        html = html.replace("@@SLOT:%s@@" % name, text)
    return html


_gz_cache = {}   # (id, len) of an unchanging body -> gzipped bytes


def _gzip(body):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as z:
        z.write(body)
    return buf.getvalue()


_static_cache = {}
_page_state = {"sig": None}
_page_lock = threading.Lock()
PAGE = PAGE_BYTES = None


def _page_signature():
    sig = [PAGE_DIR]
    for f in BASE_PAGE_FILES:
        try:
            sig.append(os.path.getmtime(os.path.join(PAGE_DIR, f)))
        except OSError:
            sig.append(None)
    return tuple(sig)


def refresh_page(force=False):
    """Follow the files: when a page file or a module was added, removed, switched or edited since the page was
    built, load the enabled modules again and build the page again. Cheap (a few stat calls); done for every request
    so a module switched on, or its files copied in or deleted, shows up on the next page load without a restart."""
    global PAGE, PAGE_BYTES
    changed = modules.refresh(force=force)
    sig = _page_signature()
    if not changed and sig == _page_state["sig"] and not force:
        return
    with _page_lock:
        sig = _page_signature()
        PAGE = build_page()
        PAGE_BYTES = PAGE.encode("utf-8")
        _gz_cache.clear()
        _page_state["sig"] = sig


refresh_page(force=True)


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


def _button_config():
    return {"button1_gpio": core.button_gpio(1), "button2_gpio": core.button_gpio(2),
            "button1_function": core.button_function(1), "button2_function": core.button_function(2),
            "wifi_button": core.wifi_button()}


def _button_reply():
    return {"config": _button_config(), "gpios": core.BUTTON_GPIO_PINS, "functions": core.BUTTON_FUNCTIONS,
            "wifi_choices": core.WIFI_BUTTON_CHOICES, "wifi": core.wifi_enabled()}


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
        # nobody may frame the page (clickjacking the update/restart buttons) or have it guessed as another type
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
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

    def _refuse(self, status, message):
        self.send(message + "\n", "text/plain; charset=utf-8", status=status)

    def do_GET(self):
        if not security.host_allowed(self.headers.get("Host")):
            return self._refuse(421, "Unknown host name: use the Pi's IP address or its .local name "
                                     "(or list the name in /opt/dreampi-netswitch/allowed_hosts)")
        self._safely(self._get)

    def do_POST(self):
        if not security.host_allowed(self.headers.get("Host")):
            return self._refuse(421, "Unknown host name")
        self._safely(self._post)

    def _body(self, limit):
        """The request body, at most `limit` bytes (a negative or bad Content-Length counts as none)."""
        try:
            length = max(0, min(int(self.headers.get("Content-Length") or 0), limit))
        except ValueError:
            length = 0
        return self.rfile.read(length) if length else b""

    def _get(self):
        refresh_page()          # follows added / removed / switched modules and edited page files
        path = self.path.split("?")[0]
        if path == "/ping":
            self.send("ok\n", "text/plain")
        elif path == "/api":
            self.send(json.dumps(api_state()), "application/json")
        elif path == "/tag":
            # For openMenu over the PPP link: a tiny HTTP/1.0 answer, no markup, no caching.
            code = core.tag()
            text = dict(core.TAGS).get(code, "") if "text" in self.path else code
            self.send(text + "\n", "text/plain; charset=utf-8")
        elif path == "/status":
            d = api_state()
            self.send("network=%s\ntag=%s\ndreampi=%s\nmodem=%s\ninternet=%s\npi=%s\n" % (
                d["network"], core.tag(), d["dreampi"]["text"],
                d["modem"]["text"], d["internet"]["text"], d["pi"]["text"]), "text/plain; charset=utf-8")
        elif path == "/about":
            rows = probes.about()
            rows.append(("PIN", "Asked before update, restart and Wi-Fi connect" if security.pin_required()
                         else "Off: anyone on your network can update or restart (install.sh --pin sets one)"))
            self.send(json.dumps(rows), "application/json")
        elif path.startswith("/static/"):
            name = path[len("/static/"):]
            body = _static(name)
            if body is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send(body, STATIC_FILES[name], cache=86400, fixed=True)
        elif path == "/modules":
            self.send(json.dumps({"modules": modules.listing()}), "application/json")
        elif path == "/update":
            self.send(json.dumps(updater.status()), "application/json")
        elif path == "/buttonconfig":
            self.send(json.dumps(_button_reply()), "application/json")
        elif modules.route("GET", path):
            modules.route("GET", path)(self)         # an enabled module's own endpoint
        elif path == "/":
            self.send(PAGE_BYTES, "text/html; charset=utf-8", fixed=True)
        else:
            self._refuse(404, "Not found (or the module that answers it is off)")

    def _post(self):
        refresh_page()
        path = self.path.split("?")[0]
        # Everything here changes something, and some of it runs as root: only the page itself may ask
        # (not another site's form or script), and the actions that reboot, update or change Wi-Fi
        # also need the PIN when one is set.
        if not security.post_allowed(self.headers, strict=path in security.PROTECTED):
            return self._refuse(403, "Refused: this request did not come from the page")
        if path in security.PROTECTED:
            ok, message = security.check_pin(self.headers.get("X-Netswitch-Pin") or "")
            if not ok:
                core.debug_log("web page: %s refused (%s)" % (path, message))
                self.send(json.dumps({"started": False, "message": message}), "application/json",
                          status=429 if message.startswith("Too many") else 401)
                return
        if path == "/reboot":
            started, message = probes.start_reboot()
            self.send(json.dumps({"started": started, "message": message}), "application/json")
            return
        if path in ("/update/check", "/update/start"):
            if not self.headers.get("X-Requested-With"):   # the check is harmless but still only for the page
                return self._refuse(403, "Refused: this request did not come from the page")
            message = ""
            if path == "/update/check":
                updater.check_in_background()
            else:
                started, message = updater.start_update()
            self.send(json.dumps({"message": message, "status": updater.status()}), "application/json")
            return
        if path == "/modules":
            return self._post_modules()
        if path == "/buttonconfig":
            return self._post_buttons()
        if path == "/dcnet":
            open(core.FLAG, "w").close()
            core.debug_log("web page: DCNET selected")
        elif path == "/dcnow":
            if os.path.exists(core.FLAG):
                os.remove(core.FLAG)
            core.debug_log("web page: DCNow! selected")
        elif path == "/hangup":
            probes.start_hangup()
        elif modules.route("POST", path):
            if modules.route("POST", path)(self) is True:    # an enabled module's own endpoint; True = it has answered
                return
        else:
            return self._refuse(404, "Not found (or the module that answers it is off)")
        if self.headers.get("X-Requested-With"):
            self.send_response(204)   # the page's own buttons: nothing to reload
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(303)  # back to the page when JavaScript is off
        self.send_header("Content-Length", "0")
        self.send_header("Location", "/")
        self.end_headers()

    def _post_modules(self):
        """The Modules menu: switch an installed module on or off."""
        try:
            data = json.loads(self._body(1024).decode("utf-8"))
            name, on = data["name"], data["enabled"]
            if not isinstance(name, type(u"")) or not isinstance(on, bool):
                raise ValueError("name and enabled needed")
        except (ValueError, KeyError, TypeError, IOError, OSError) as e:
            return self.send("Bad request: %s" % e, "text/plain; charset=utf-8", status=400)
        if not core.save_module_enabled(name, on):
            return self.send("No such module: %s" % name, "text/plain; charset=utf-8", status=404)
        core.debug_log("web page: module %s switched %s" % (name, "on" if on else "off"))
        refresh_page(force=True)
        self.send(json.dumps({"modules": modules.listing()}), "application/json")

    def _post_buttons(self):
        try:
            data = json.loads(self._body(4096).decode("utf-8"))
        except (ValueError, IOError, OSError) as e:
            return self.send(str(e), "text/plain; charset=utf-8", status=400)
        try:
            g1, g2 = int(data["button1_gpio"]), int(data["button2_gpio"])
        except (KeyError, TypeError, ValueError):
            g1 = g2 = None
        if g1 is not None and g2 is not None and g1 != g2:   # reject if they'd collide on one pin
            core.save_button_gpio(1, g1)
            core.save_button_gpio(2, g2)
        if "button1_function" in data:
            core.save_button_function(1, data["button1_function"])
        if "button2_function" in data:
            core.save_button_function(2, data["button2_function"])
        if "wifi_button" in data:
            core.save_wifi_button(data["wifi_button"])
        self.send(json.dumps({"config": _button_config()}), "application/json")

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
    if len(sys.argv) > 1:
        PORT = int(sys.argv[1])
    if len(sys.argv) > 2:
        HTTPS_PORT = int(sys.argv[2])
    core.reset_network_after_boot()      # DCNow! after every reboot
    for target in (probes.checker, watchdog):
        t = threading.Thread(target=target)
        t.daemon = True
        t.start()
    start_https()
    Server(("", PORT), Handler).serve_forever()
