#!/usr/bin/env python3
# DreamPi Netswitch add-on - web page to choose DCNow! or DCNET.
# Shows DreamPi's and the modem's live status and internet access, plus an
# optional debug timeline. It only creates/removes the files that
# netswitch_hook.py reads. This module is the HTTP side (page, API, HTTPS,
# watchdog); settings and state are in netswitch_core.py and netswitch_ledconfig.py, measurements in
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
import netswitch_numbers as numbers
import netswitch_probes as probes
import netswitch_security as security
import netswitch_update as updater
import importlib

# Optional modules. Each is a set of files; with every file present the feature is part of the page, with any of
# them missing it is simply not there (nothing else notices). The page follows the files while the service runs:
# refresh_modules() looks at them whenever the page is requested, so adding or deleting them takes effect on the
# next reload (the LED *service* is started or stopped by install.sh, see docs/led.md).
#   players: the online-players list              (netswitch_players.py + page/players.js)
#   led:     the status LEDs and their settings   (netswitch_ledconfig.py, netswitch_led.py, netswitch_led_drivers.py
#                                                  + page/led.html, led.js, led.css)
_HERE = os.path.dirname(os.path.abspath(__file__))
OPTIONAL_MODULES = {
    "players": {"python": ["netswitch_players.py"], "page": ["players.js"], "import": "netswitch_players"},
    "led": {"python": ["netswitch_ledconfig.py", "netswitch_led.py", "netswitch_led_drivers.py"],
            "page": ["led.html", "led.js", "led.css"], "import": "netswitch_ledconfig"},
}
LED_PATHS = ("/ledconfig", "/ledhide", "/wbtest", "/wbtestdone")   # answered only while the LED module is present


def module_present(name):
    spec = OPTIONAL_MODULES[name]
    return (all(os.path.exists(os.path.join(_HERE, f)) for f in spec["python"])
            and all(os.path.exists(os.path.join(PAGE_DIR, f)) for f in spec["page"]))


def _load_optional(name):
    """The module's Python file when all its files are there and it imports, else None."""
    if not module_present(name):
        return None
    try:
        return importlib.import_module(OPTIONAL_MODULES[name]["import"])
    except Exception as e:      # a broken module must not take the page down with it
        sys.stderr.write("optional module %s not loaded: %s\n" % (name, e))
        return None


players = None      # filled in by refresh_modules() below
ledconfig = None

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
    """What the DreamPi dot previews: the LED message that is showing (LED module present), else a plain
    look for the state so the dot still says something."""
    if ledconfig is not None:
        return (ledconfig.active_messages(dstate, {"network": True}, wifi=False) or [None])[-1]
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
    wf = core.wifi_state()
    wf_state = wf.get("state", "idle")
    if wf_state in ("scanning", "hosting"):
        warnings.append("Wi-Fi setup: connect a phone or PC to the “%s” Wi-Fi network, then open "
                        "http://192.168.4.1 to pick a network." % core.WIFI_AP_SSID)
    elif wf_state == "connecting":
        warnings.append("Wi-Fi setup: trying to connect to “%s”..." % (wf.get("ssid") or ""))
    elif wf_state == "failed":
        warnings.append("Wi-Fi setup: could not connect (%s)." % (wf.get("ssid") or "unknown reason"))
    return {"network": "dcnet" if os.path.exists(core.FLAG) else "dcnow",
            "autoreset": os.path.exists(core.AUTORESET),
            "default": "dcnet" if os.path.exists(core.DEFAULT_DCNET) else "dcnow",
            "debug": os.path.exists(core.DEBUG_DTMF),
            # the dot next to DreamPi previews that status's LED message only;
            # network problems show as warning boxes instead
            "dreampi": {"state": dstate, "text": dtext,
                        "look": _dot_look(dstate)},
            "modem": {"text": mtext, "since": msince, "plugged": plugged, "label": label, "compat": compat},
            "internet": checks["internet"],
            "pi": {"state": pi.get("state"), "text": pi.get("text"), "line1": pi.get("line1"),
                   "line2": pi.get("line2"), "warn": pi.get("warn")},
            "wifi": {"state": wf_state, "ssid": wf.get("ssid"), "networks": wf.get("networks"),
                     "installed": os.path.exists(core.WIFI_ENABLED), "demo": os.path.exists(core.WIFI_DEMO)},
            "hangup": {"busy": probes._hangup["busy"], "text": probes._hangup["text"]},
            "pin": security.pin_required(),     # the page asks for it before update / restart / Wi-Fi connect
            "warnings": warnings, "now": int(time.time())}


PAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "page")


def build_page():
    """The page is one document: page/index.html with page/page.css and
    page/page.js put in where it says @@CSS@@ and @@JS@@ (one request, kept in
    memory by PAGE_BYTES). Edit those three files, not this module. The optional
    modules add themselves: players.js as a script of its own, the LED module's
    markup / styles / script at @@LED@@, @@LED_GPIO_ROW@@, @@LED_GPIO_NOTE@@, the end of
    the CSS and the end of the script. Without a module those markers are just empty."""
    def part(name):
        with io.open(os.path.join(PAGE_DIR, name), encoding="utf-8", newline="") as f:
            return f.read()
    modules = ""
    if players is not None and os.path.exists(os.path.join(PAGE_DIR, "players.js")):
        modules = '<script src="/players.js" defer></script>'
    css, js = part("page.css"), part("page.js")
    led_parts = {"LED": "", "LED_GPIO_ROW": "", "LED_GPIO_NOTE": ""}
    if ledconfig is not None and all(os.path.exists(os.path.join(PAGE_DIR, f)) for f in OPTIONAL_MODULES["led"]["page"]):
        for name, text in re.findall(r"<!--part:(\w+)-->\n(.*?)(?=<!--part:|\Z)", part("led.html"), re.S):
            led_parts[name] = text
        css += "\n" + part("led.css")
        js += "\n" + part("led.js")
    html = part("index.html").replace("@@CSS@@", css).replace("@@JS@@", js).replace("@@MODULES@@", modules)
    for name, text in led_parts.items():
        html = html.replace("@@%s@@" % name, text)
    return html


_gz_cache = {}   # (id, len) of an unchanging body -> gzipped bytes


def _gzip(body):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as z:
        z.write(body)
    return buf.getvalue()


_static_cache = {}
_watched = ["index.html", "page.css", "page.js", "players.js", "led.html", "led.js", "led.css"]
_page_state = {"sig": None}
_page_lock = threading.Lock()
PAGE = PAGE_BYTES = None


def _signature():
    files = [os.path.join(PAGE_DIR, f) for f in _watched]
    for spec in OPTIONAL_MODULES.values():
        files += [os.path.join(_HERE, f) for f in spec["python"]]
    sig = []
    for path in files:
        try:
            sig.append(os.path.getmtime(path))
        except OSError:
            sig.append(None)
    return (PAGE_DIR, tuple(sig))


def refresh_modules(force=False):
    """Follow the files: when a page or module file was added, removed or changed since the page was built,
    load or drop the optional modules and build the page again. Cheap (a few stat calls) and only done
    when the page itself or one of the module endpoints is asked for."""
    global players, ledconfig, PAGE, PAGE_BYTES
    sig = _signature()
    if sig == _page_state["sig"] and not force:
        return
    with _page_lock:
        sig = _signature()
        if sig == _page_state["sig"] and not force:
            return
        players = _load_optional("players")
        ledconfig = _load_optional("led")
        PAGE = build_page()
        PAGE_BYTES = PAGE.encode("utf-8")
        _gz_cache.clear()
        _page_state["sig"] = sig


refresh_modules(force=True)


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


def _numbers_reply():
    return {"numbers": numbers.numbers(), "defaults": numbers.default_numbers(),
            "actions": [{"key": a[0], "label": a[1], "sub": a[2]} for a in numbers.ACTIONS],
            "min": numbers.MIN_LEN, "max": numbers.MAX_LEN, "per_action": numbers.MAX_PER_ACTION}


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
        if self.path in ("/", "/ledconfig", "/players", "/players.js") or self.path.startswith("/?"):
            refresh_modules()
        if self.path == "/ping":
            self.send("ok\n", "text/plain")
        elif self.path == "/api":
            self.send(json.dumps(api_state()), "application/json")
        elif self.path.startswith("/log"):
            m = re.search(r"from=(-?\d+)", self.path)
            self.send(json.dumps(core.read_log(int(m.group(1)) if m else 0)), "application/json")
        elif self.path.split("?")[0] == "/tag":
            # For openMenu over the PPP link: a tiny HTTP/1.0 answer, no markup, no caching.
            code = core.tag()
            text = dict(core.TAGS).get(code, "") if "text" in self.path else code
            self.send(text + "\n", "text/plain; charset=utf-8")
        elif self.path == "/status":
            d = api_state()
            self.send("network=%s\ntag=%s\ndefault=%s\nautoreset=%s\ndreampi=%s\nmodem=%s\ninternet=%s\npi=%s\n" % (
                d["network"], core.tag(), d["default"], "on" if d["autoreset"] else "off", d["dreampi"]["text"],
                d["modem"]["text"], d["internet"]["text"], d["pi"]["text"]), "text/plain; charset=utf-8")
        elif self.path == "/about":
            rows = probes.about()
            rows.append(("PIN", "Asked before update, restart and Wi-Fi connect" if security.pin_required()
                         else "Off: anyone on your network can update or restart (install.sh --pin sets one)"))
            self.send(json.dumps(rows), "application/json")
        elif self.path.startswith("/static/"):
            name = self.path[len("/static/"):].split("?")[0]
            body = _static(name)
            if body is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send(body, STATIC_FILES[name], cache=86400, fixed=True)
        elif self.path == "/ledconfig" and ledconfig is None:
            self._refuse(404, "The LED module is not installed")
        elif self.path == "/ledconfig" and ledconfig is not None:
            self.send(json.dumps({"config": ledconfig.led_config(), "defaults": ledconfig.default_led_config(),
                                  "states": ledconfig.LED_STATES, "groups": ledconfig.GROUPS,
                                  "effects": ledconfig.EFFECTS, "orders": ledconfig.LED_ORDERS, "count": ledconfig.led_count(),
                                  "gpio": ledconfig.led_gpio(), "gpios": ledconfig.GPIO_PINS,
                                  "installed": ledconfig.led_count() > 0, "hidden": ledconfig.led_hidden()}),
                     "application/json")
        elif self.path == "/numbers":
            self.send(json.dumps(_numbers_reply()), "application/json")
        elif self.path == "/update":
            self.send(json.dumps(updater.status()), "application/json")
        elif self.path == "/players" and players is not None:
            self.send(json.dumps(players.status()), "application/json")
        elif self.path == "/players.js" and players is not None and os.path.exists(os.path.join(PAGE_DIR, "players.js")):
            with open(os.path.join(PAGE_DIR, "players.js"), "rb") as f:
                self.send(f.read(), "application/javascript; charset=utf-8")
        elif self.path == "/buttonconfig":
            self.send(json.dumps({"config": {"button1_gpio": core.button_gpio(1), "button2_gpio": core.button_gpio(2),
                                             "button1_function": core.button_function(1),
                                             "button2_function": core.button_function(2),
                                             "wifi_button": core.wifi_button()},
                                  "gpios": core.BUTTON_GPIO_PINS, "functions": core.BUTTON_FUNCTIONS,
                                  "wifi_choices": core.WIFI_BUTTON_CHOICES,
                                  "wifi": os.path.exists(core.WIFI_ENABLED)}),
                     "application/json")
        elif self.path.split("?")[0] == "/dtmf":
            try:
                with open(core.DTMF_LOG, "rb") as f:
                    f.seek(0, 2)
                    size = f.tell()
                    full = "all" in self.path.split("?", 1)[-1] if "?" in self.path else False
                    start = 0 if full or size <= core.TEXT_TAIL else size - core.TEXT_TAIL
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
        path = self.path.split("?")[0]
        if path in LED_PATHS:
            refresh_modules()
        if path in LED_PATHS and ledconfig is None:
            return self._refuse(404, "The LED module is not installed")
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
        if self.path == "/ledconfig":
            try:
                data = json.loads(self._body(65536).decode("utf-8"))
                cfg = ledconfig.save_led_config(data)
                if "count" in data:
                    ledconfig.save_led_count(data["count"])
                if "gpio" in data:
                    ledconfig.save_led_gpio(data["gpio"])
            except (ValueError, IOError, OSError) as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(str(e).encode("utf-8"))
                return
            self.send(json.dumps({"config": cfg, "count": ledconfig.led_count(), "gpio": ledconfig.led_gpio()}),
                     "application/json")
            return
        if self.path == "/reboot":
            started, message = probes.start_reboot()
            self.send(json.dumps({"started": started, "message": message}), "application/json")
            return
        if self.path in ("/update/check", "/update/start"):
            if not self.headers.get("X-Requested-With"):   # the check is harmless but still only for the page
                return self._refuse(403, "Refused: this request did not come from the page")
            message = ""
            if self.path == "/update/check":
                updater.check_in_background()
            else:
                started, message = updater.start_update()
            self.send(json.dumps({"message": message, "status": updater.status()}), "application/json")
            return
        if self.path == "/numbers":
            try:
                numbers.save_numbers(json.loads(self._body(16384).decode("utf-8")))
            except (ValueError, IOError, OSError) as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(str(e).encode("utf-8"))
                return
            self.send(json.dumps(_numbers_reply()), "application/json")
            return
        if self.path == "/buttonconfig":
            try:
                data = json.loads(self._body(4096).decode("utf-8"))
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
                core.save_button_gpio(1, g1)
                core.save_button_gpio(2, g2)
            if "button1_function" in data:
                core.save_button_function(1, data["button1_function"])
            if "button2_function" in data:
                core.save_button_function(2, data["button2_function"])
            if "wifi_button" in data:
                core.save_wifi_button(data["wifi_button"])
            self.send(json.dumps({"config": {"button1_gpio": core.button_gpio(1), "button2_gpio": core.button_gpio(2),
                                             "button1_function": core.button_function(1),
                                             "button2_function": core.button_function(2),
                                             "wifi_button": core.wifi_button()}}),
                     "application/json")
            return
        if self.path == "/ledhide":
            if os.path.exists(core.LED_HIDDEN):
                os.remove(core.LED_HIDDEN)
                core.debug_log("web page: LED settings shown again")
            else:
                open(core.LED_HIDDEN, "w").close()
                core.debug_log("web page: LED settings hidden")
        if self.path == "/wbtest":
            ledconfig.touch_wb_test()
        elif self.path == "/wbtestdone":
            ledconfig.clear_wb_test()
        if self.path == "/dcnet":
            open(core.FLAG, "w").close()
            core.debug_log("web page: DCNET selected")
        elif self.path == "/dcnow":
            if os.path.exists(core.FLAG):
                os.remove(core.FLAG)
            core.debug_log("web page: DCNow! selected")
        elif self.path == "/default":
            if os.path.exists(core.DEFAULT_DCNET):
                os.remove(core.DEFAULT_DCNET)
                core.debug_log("web page: default network set to DCNow!")
            else:
                open(core.DEFAULT_DCNET, "w").close()
                core.debug_log("web page: default network set to DCNET")
        elif self.path == "/autoreset":
            if os.path.exists(core.AUTORESET):
                os.remove(core.AUTORESET)
                core.debug_log("web page: reset on openMenu turned off")
            else:
                open(core.AUTORESET, "w").close()
                core.debug_log("web page: reset on openMenu turned on")
        elif self.path == "/debug":
            if os.path.exists(core.DEBUG_DTMF):
                core.debug_log("web page: debug log stopped")
                os.remove(core.DEBUG_DTMF)
            else:
                open(core.DEBUG_DTMF, "w").close()
                if os.path.exists(core.DTMF_LOG):
                    os.remove(core.DTMF_LOG)  # start a fresh log
                core.debug_log("web page: debug log started (network: %s)" %
                          ("DCNET" if os.path.exists(core.FLAG) else "DCNow!"))
        elif self.path == "/hangup":
            probes.start_hangup()
        elif self.path == "/clearlog":
            if os.path.exists(core.DTMF_LOG):
                os.remove(core.DTMF_LOG)
            core.debug_log("web page: log cleared")
        elif self.path == "/wifitoggle":
            if os.path.exists(core.WIFI_ENABLED):
                if core.wifi_state().get("state", "idle") == "idle":
                    open(core.WIFI_START, "w").close()
                    core.debug_log("web page: Wi-Fi setup started")
                else:
                    open(core.WIFI_STOP, "w").close()
                    core.debug_log("web page: Wi-Fi setup stop requested")
        elif self.path == "/wificonnect":
            # An alternative to the setup access point's own /connect: lets
            # this page pick a network too, reachable while it's up over
            # Ethernet (or anything else besides the Wi-Fi being reconfigured).
            if os.path.exists(core.WIFI_ENABLED):
                ssid = ""
                try:
                    data = json.loads(self._body(4096).decode("utf-8"))
                    ssid = str(data.get("ssid") or "").strip()[:32]      # an SSID is at most 32 bytes
                    password = str(data.get("password") or "")[:63]      # a WPA passphrase at most 63
                except (ValueError, IOError, OSError, AttributeError):
                    pass
                if ssid:
                    tmp = core.WIFI_CONNECT + ".tmp"
                    with open(tmp, "w") as f:
                        json.dump({"ssid": ssid, "password": password}, f)
                    os.rename(tmp, core.WIFI_CONNECT)
                    core.debug_log("web page: Wi-Fi connect requested for %s" % ssid)
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
    if len(sys.argv) > 1:
        PORT = int(sys.argv[1])
    if len(sys.argv) > 2:
        HTTPS_PORT = int(sys.argv[2])
    for target in (probes.checker, watchdog):
        t = threading.Thread(target=target)
        t.daemon = True
        t.start()
    start_https()
    Server(("", PORT), Handler).serve_forever()
