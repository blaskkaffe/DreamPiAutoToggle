#!/usr/bin/env python3
# Base - the web service: the HTTP side (page, API, HTTPS, watchdog). Settings and state are in base_core.py, the features
# (and what they measure) are modules in modules/ that base_modules.py loads. Works on Python 3 and 2.7.
import gzip
import io
import json
import re
import os
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

import base_core as core
import base_modules as modules
import base_security as security

STATIC_DIR = core.project_path("static")          # the project's pictures: served from /static/ (a plain file name with one of these endings)
STATIC_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".ico": "image/x-icon", ".svg": "image/svg+xml"}
_STATIC_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _static_type(name):
    """The content type of a file of static/, or None (not a picture, not a plain name, or not there)."""
    if not _STATIC_NAME.match(name or "") or os.path.splitext(name)[1].lower() not in STATIC_TYPES or not os.path.isfile(os.path.join(STATIC_DIR, name)):
        return None
    return STATIC_TYPES[os.path.splitext(name)[1].lower()]
PORT = 80
HTTPS_PORT = 443   # 0 = no HTTPS; both can be given on the command line: base_web.py [port] [https port]
CERT = os.path.join(core.BASE_DIR, "https.crt")   # self-signed, made by install.sh
KEY = os.path.join(core.BASE_DIR, "https.key")


def palette_json():
    """The palette as the page needs it: id, name, group, ui, ui_l; a colour token (a colour a module adds, like "Selected network") also says which
    palette colour it is right now ("follows")."""
    return [dict({"id": c["id"], "name": c["name"], "group": c["group"], "ui": c["ui"], "ui_l": c["ui_l"]}, **({"follows": c["follows"]} if c.get("follows") else {}))
            for c in core.colours()]


def api_state(have_palette=""):
    """The /api answer. The base only has the page-wide parts (PIN flag, warnings, time, the modules' colours); everything
    else is added by the enabled modules' api() hooks (each module adds its own part)."""
    warnings = ["Module %s is not loaded: %s" % (name, why) for name, why in sorted(modules.errors().items())]
    d = {"pin": security.pin_required(),     # the page asks for it before an action a module marks PROTECTED
         "colours": modules.live_colours(), "tints": modules.live_tints(), "primary": {}, "primary_key": {}, "enabled": modules.enabled_map(),
         "warnings": warnings, "now": int(time.time()),
         "notices": [],         # banners over the boxes that are not warnings: {"id", "text", "post" (dismiss: POST {"id"} there)}
         "screen": core.screen_settings(), "tile_layout": core.tile_layout(), "daylight": core.daylight(),
         "settings_pin": {"on": security.settings_locked(), "pin": security.pin_required()}}
    modules.apply_api(d, warnings)          # what the enabled modules add: each module's data
    version = core.palette_version()
    d["palette_v"] = version
    if have_palette != version:             # the palette (and its CSS) only when the page does not have this version: it changes when the user edits it
        d["palette"] = palette_json()
        d["palette_css"] = core.colours_css()
    return d


PAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "page")


BASE_PAGE_FILES = ("index.html", "page.css", "page.js", "widgets.js", "boot.js")


def _screen_reply():
    """The form widget's answer for Appearance > Max columns (the two toggles under it read S.screen from /api)."""
    cur = core.screen_settings()
    opts = [{"value": n, "label": str(n)} for n in range(1, core.MAX_COLUMNS + 1)]
    themes = [{"value": "dark", "label": "Dark"}, {"value": "light", "label": "Light"}, {"value": "auto", "label": "Like the device"},
              {"value": "time", "label": "By the time of day"}]
    sizes = [{"value": v, "label": l} for v, l in ((0.8, "Small"), (1.0, "Normal"), (1.25, "Large"), (1.5, "Larger"), (2.0, "Largest"))]
    colours = [{"value": "auto", "label": "Automatic (black on light boxes, white on dark)"}, {"value": "black", "label": "Black"}, {"value": "white", "label": "White"}] + \
              [{"value": c["id"], "label": c["name"]} for c in core.colours() if not c.get("token")]
    sounds = [{"value": "off", "label": "Off"}] + [{"value": n, "label": os.path.splitext(n)[0]} for n in core.list_sounds()]
    return {"values": {"dash_cols": cur["dash_cols"], "set_cols": cur["set_cols"], "theme": cur["theme"], "font_scale": cur["font_scale"], "font_colour": cur["font_colour"],
                       "sound_name": cur["sound_name"] if cur["sound"] else "off", "sound_volume": cur["sound_volume"]},
            "options": {"cols": opts, "themes": themes, "sizes": sizes, "font_colours": colours, "sounds": sounds},
            "texts": {"theme": dict((t["value"], t["label"]) for t in themes)[cur["theme"]],
                      "font_scale": "Text size %s\u00d7" % ("%g" % cur["font_scale"]),
                      "sound_name": (os.path.splitext(cur["sound_name"])[0] + " \u00b7 volume %d%%" % round(cur["sound_volume"] * 100)) if cur["sound"] else "Off",
                      "font_colour": "Automatic" if cur["font_colour"] == "auto" else dict((c["value"], c["label"]) for c in colours).get(cur["font_colour"], "Automatic"),
                      "dash_cols": "Up to %d" % cur["dash_cols"] + (" column" if cur["dash_cols"] == 1 else " columns"),
                      "set_cols": "Up to %d" % cur["set_cols"] + (" column" if cur["set_cols"] == 1 else " columns")}}


def _palette_reply(extra=None):
    """The colour palette editor (Settings > Appearance > Colour palette): the palette in its order, with what the editor needs. The modules' own
    colours (Selected network) are not in it. What another module shows for a colour is that module's."""
    out = []
    for c in core.colours():
        if c.get("token"):
            continue
        shipped = [s for s in core.PALETTE if s[0] == c["id"]]
        out.append({"id": c["id"], "name": c["name"], "ui": c["ui"], "ui_l": c["ui_l"], "ui_default": c["ui_default"],
                    "fixed": c["id"] in core.FIXED_COLOURS, "custom": not shipped,
                    "changed": bool(shipped) and (c["ui"] != c["ui_default"] or c["name"] != shipped[0][1])})
    body = {"colours": out, "can_add": len([c for c in out if c["custom"]]) < core.MAX_CUSTOM_COLOURS}
    body.update(extra or {})
    return body


def _timezone_reply():
    """The form widget's answer for the common time zone (Settings > About)."""
    import base_tz as tz
    zone = core.time_zone()
    return {"values": {"zone": zone}, "options": {"zones": tz.zone_options()}, "texts": {"zone": tz.zone_text(zone)}}


def _layout_script():
    """window.LAYOUT: the boxes, data sources, colours and backgrounds of the enabled modules (base_modules.layout()),
    plus the palette. Put in a <script> tag, so a "</" inside a text is escaped."""
    lay = modules.layout()
    lay["palette"] = palette_json()
    return "window.LAYOUT=" + json.dumps(lay).replace("</", "<\\/") + ";"


def build_page():
    """The page is one document: page/index.html with page/page.css, page/widgets.js, page/page.js and page/boot.js put in where
    it says @@CSS@@ and @@JS@@ (one request, kept in memory as PAGE_BYTES). Edit those files, not this module. The
    enabled modules add themselves (base_modules.page_parts()): their layout (window.LAYOUT, drawn by the engine in
    widgets.js), their styles after page.css and their script after the base script (custom widgets, hooks, a background)."""
    def part(name):
        with io.open(os.path.join(PAGE_DIR, name), encoding="utf-8", newline="") as f:
            return f.read()
    mine = core.screen_id()
    core.set_screen("")                    # the page is the same for every screen: it starts from the shared settings
    try:
        return _build_page(part)
    finally:
        core.set_screen(mine)


def _build_page(part):
    extra = modules.page_parts()
    js = _layout_script() + "\n" + part("page.js") + "\n" + part("widgets.js") + "\n" + extra["js"] + "\n" + part("boot.js")
    html = part("index.html").replace("@@TITLE@@", core.PROJECT.get("title", "Dashboard")).replace("@@ICON@@", core.PROJECT.get("icon", "")).replace("@@TOUCH@@", core.PROJECT.get("touch_icon", core.PROJECT.get("icon", ""))).replace("@@THEME@@", core.screen_settings()["theme"]).replace("@@CSS@@", core.colours_css() + part("page.css") + "\n" + extra["css"]).replace("@@JS@@", js)
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
    sig = [PAGE_DIR, json.dumps(modules.live_colours(), sort_keys=True)]    # the colours are built into the page
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
    """A picture of static/ (see _static_type()), kept in memory."""
    if _static_type(name) is None:
        return None
    if name not in _static_cache:
        try:
            with open(os.path.join(STATIC_DIR, name), "rb") as f:
                _static_cache[name] = f.read()
        except (IOError, OSError):
            return None
    return _static_cache[name]


def _colour_reply():
    return {"palette": core.colours(), "modules": modules.live_colours()}


class Handler(BaseHTTPRequestHandler):
    timeout = 20          # a client that stops talking can't hold a thread forever
    protocol_version = "HTTP/1.1"   # keep-alive: the page asks /api every second, a new TLS handshake each time is heavy on a computer
    _body_read = 0

    def send(self, body, ctype, cache=None, status=200, fixed=False):
        """cache: seconds the browser may keep it (None = always ask again).
        fixed: the body never changes (page, static files), so its gzipped
        form is kept in memory instead of compressed for every request."""
        if not isinstance(body, bytes):
            body = body.encode("utf-8")
        gz = len(body) > 2000 and "gzip" in (self.headers.get("Accept-Encoding") or "") and not ctype.startswith("image/")      # pictures are packed already
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
        logged (journalctl -u <the service>) instead of dropping the
        connection."""
        try:
            handler()
        except (socket.timeout, IOError, OSError) as e:
            if getattr(e, "errno", None) not in (32, 104, None) and not isinstance(e, socket.timeout):
                sys.stderr.write("request %s failed: %s\n" % (self.path, e))
        except Exception:
            sys.stderr.write("request %s failed:\n%s" % (self.path, traceback.format_exc()))
            try:
                self.send("Internal error, see journalctl -u " + core.PROJECT.get("service", "app") + "\n",
                          "text/plain; charset=utf-8", status=500)
            except Exception:
                pass

    def _refuse(self, status, message):
        self.send(message + "\n", "text/plain; charset=utf-8", status=status)

    def do_GET(self):
        core.set_screen(self.headers.get("X-Screen"))       # the screen this request comes from (the page sends its id), "" for a plain browser
        if self.headers.get("Content-Length") not in (None, "0"):
            self.close_connection = True      # a GET with a body: don't try to parse the body as the next request
        if not security.host_allowed(self.headers.get("Host")):
            return self._refuse(421, "Unknown host name: use the machine's IP address or its .local name "
                                     "(or list the name in " + core.ALLOWED_HOSTS + ")")
        self._safely(self._get)

    def do_POST(self):
        core.set_screen(self.headers.get("X-Screen"))
        self._body_read = 0
        try:
            if not security.host_allowed(self.headers.get("Host")):
                return self._refuse(421, "Unknown host name")
            self._safely(self._post)
        finally:
            try:
                sent = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                sent = -1
            if sent != self._body_read:               # a refused request's body would be taken for the next request: skip it
                if 0 < sent - self._body_read <= 1 << 20:
                    try:
                        self.rfile.read(sent - self._body_read)
                    except (socket.timeout, IOError, OSError):
                        self.close_connection = True
                else:
                    self.close_connection = True

    def _body(self, limit):
        """The request body, at most `limit` bytes (a negative or bad Content-Length counts as none)."""
        try:
            length = max(0, min(int(self.headers.get("Content-Length") or 0), limit))
        except ValueError:
            length = 0
        data = self.rfile.read(length) if length else b""
        self._body_read += len(data)
        return data

    def _get(self):
        refresh_page()          # follows added / removed / switched modules and edited page files
        path = self.path.split("?")[0]
        if path == "/ping":
            self.send("ok\n", "text/plain")
        elif path == "/api":
            query = dict(p.split("=", 1) for p in (self.path.split("?", 1)[1] if "?" in self.path else "").split("&") if "=" in p)
            self.send(json.dumps(api_state(query.get("pv", "")[:16])), "application/json")
        elif path.startswith("/static/"):
            name = path[len("/static/"):]
            body = _static(name)
            if body is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send(body, _static_type(name), cache=86400, fixed=True)
        elif path.startswith("/sounds/"):          # a button sound of SOUNDS_DIR (copy more files in by hand)
            from urllib.parse import unquote
            name = unquote(path[len("/sounds/"):])
            file = core.sound_path(name)
            if file is None:
                return self._refuse(404, "No such sound")
            with open(file, "rb") as f:
                self.send(f.read(), core.SOUND_TYPES[os.path.splitext(name)[1].lower()], cache=3600)
        elif path == "/modules":
            self.send(json.dumps({"modules": modules.listing()}), "application/json")
        elif path == "/colours":
            self.send(json.dumps(_colour_reply()), "application/json")
        elif path == "/timezone":
            self.send(json.dumps(_timezone_reply()), "application/json")
        elif path == "/palette/list":
            self.send(json.dumps(_palette_reply()), "application/json")
        elif path == "/screen":
            self.send(json.dumps(_screen_reply()), "application/json")
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
        # (not another site's form or script), and the paths a module marks PROTECTED (the PROTECTED ones
        # connect) also need the PIN when one is set.
        # With Settings locked (Appearance > Ask for the PIN) every POST that is not a dashboard action (a module's OPEN list) needs it too.
        need_pin = modules.protected(path) or path in ("/pin", "/pin/check") or (security.settings_locked() and not modules.open_post(path))
        if not security.post_allowed(self.headers, strict=need_pin):
            return self._refuse(403, "Refused: this request did not come from the page")
        if need_pin:
            ok, message = security.check_pin(self.headers.get("X-Pin") or "")
            if not ok:
                core.log("web page: %s refused (%s)" % (path, message))
                self.send(json.dumps({"started": False, "message": message}), "application/json",
                          status=429 if message.startswith("Too many") else 401)
                return
        if path == "/pin/check":
            return self.send(json.dumps({"ok": True}), "application/json")        # got here: the PIN was right (or none is set)
        if path == "/pin":
            return self._post_pin()
        if path == "/settings-pin":
            return self._post_settings_pin()
        if path == "/modules":
            return self._post_modules()
        if path == "/modules/dashboard-layout":
            return self._post_dashboard_layout()
        if path == "/modules/order":
            return self._post_module_order()
        if path == "/modules/dashboard-order":
            return self._post_dashboard_order()
        if path == "/colour":
            return self._post_colour()
        if path == "/timezone":
            return self._post_timezone()
        if path in ("/screen", "/screen/stretch", "/screen/scale", "/screen/fit", "/screen/drag", "/screen/noscroll", "/screen/autohide", "/screen/locations", "/screen/sound"):
            return self._post_screen(path)
        if path == "/palette":
            return self._post_palette()
        if path.startswith("/palette/") and path[len("/palette/"):] in ("edit", "add", "delete", "order", "reset"):
            return self._post_palette_edit(path[len("/palette/"):])
        if modules.route("POST", path):
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
        core.log("web page: module %s switched %s" % (name, "on" if on else "off"))
        refresh_page(force=True)
        self.send(json.dumps({"modules": modules.listing()}), "application/json")

    def _post_dashboard_order(self):
        """The tiles of the main screen were moved: {"order": [module names, in the order of their tiles]}."""
        try:
            order = core.save_dashboard_order(json.loads(self._body(4096).decode("utf-8")).get("order"))
        except (ValueError, AttributeError, IOError, OSError) as e:
            return self.send("Bad request: %s" % e, "text/plain; charset=utf-8", status=400)
        if order is None:
            return self.send("Bad request: order must be a list of module names", "text/plain; charset=utf-8", status=400)
        core.log("web page: main screen tiles moved, modules now %s" % ", ".join(order))
        refresh_page(force=True)
        self.send(json.dumps({"modules": modules.listing()}), "application/json")

    def _post_dashboard_layout(self):
        """The tiles of the main screen were moved: {"cols": n, "columns": [[box ids] for each of the n columns]}; the places are kept per number of columns."""
        try:
            body = json.loads(self._body(16384).decode("utf-8"))
            saved = core.save_tile_layout(body.get("cols"), body.get("columns"))
        except (ValueError, AttributeError, IOError, OSError) as e:
            return self.send("Bad request: %s" % e, "text/plain; charset=utf-8", status=400)
        if saved is None:
            return self.send("Bad request: cols and a list of that many lists of tile ids needed", "text/plain; charset=utf-8", status=400)
        self.send(json.dumps({"tile_layout": saved}), "application/json")

    def _post_module_order(self):
        """The module picker: {"order": [name, ...]}, first = highest priority."""
        try:
            order = core.save_module_order(json.loads(self._body(4096).decode("utf-8")).get("order"))
            if order is None:
                raise ValueError("order must be a list of module names")
        except (ValueError, AttributeError, IOError, OSError) as e:
            return self.send("Bad request: %s" % e, "text/plain; charset=utf-8", status=400)
        core.log("web page: module order %s" % ", ".join(order))
        refresh_page(force=True)
        self.send(json.dumps({"modules": modules.listing()}), "application/json")

    def _post_colour(self):
        """A module's own colour setting: {"module": name, "key": its colour key, "colour": palette id}."""
        try:
            data = json.loads(self._body(1024).decode("utf-8"))
            got = None
            if "colour" in data:
                got = core.set_module_colour(data.get("module"), data.get("key"), data.get("colour"))
                if got is None:
                    raise ValueError("unknown module, colour key or colour")
            if "tint" in data:
                if core.set_module_tint(data.get("module"), data.get("key"), data.get("tint")) is None:
                    raise ValueError("unknown module or colour key, or tint is not true or false")
                got = got or core.module_colours(data.get("module"))
        except (ValueError, AttributeError, IOError, OSError) as e:
            return self.send("Bad request: %s" % e, "text/plain; charset=utf-8", status=400)
        refresh_page(force=True)       # the colours are built into the page
        core.log("web page: %s colours %s" % (data["module"], json.dumps(got, sort_keys=True)))
        self.send(json.dumps({"module": data["module"], "colours": got, "tints": core.module_tints(data["module"])}), "application/json")

    def _post_palette(self):
        """The Global main colour picker: {"id": palette id, "ui": "#rrggbb"} changes how a palette colour looks on the page."""
        try:
            data = json.loads(self._body(1024).decode("utf-8"))
            if not core.set_palette_colour(data.get("id"), ui=data.get("ui")):
                raise ValueError("not a palette colour that can be changed, or not #rrggbb")
        except (ValueError, AttributeError, IOError, OSError) as e:
            return self.send("Bad request: %s" % e, "text/plain; charset=utf-8", status=400)
        refresh_page(force=True)       # the palette is built into the page
        self.send(json.dumps({"palette": core.colours()}), "application/json")

    def _post_palette_edit(self, what):
        """Settings > Appearance > Colour palette: edit {"id", "name"?, "ui"?} | add {"name", "ui"} | delete {"id"} | order {"order": [ids]} | reset {} or {"id"}.
        Every answer is the palette again (an add also says the new id)."""
        try:
            d = json.loads(self._body(4096).decode("utf-8"))
            d = d if isinstance(d, dict) else {}
        except ValueError:
            d = {}
        extra = None
        if what == "edit":
            ok = core.palette_edit(d.get("id"), d.get("name"), d.get("ui"))
        elif what == "add":
            ident = core.palette_add(d.get("name"), d.get("ui"))
            ok, extra = ident is not None, {"id": ident}
        elif what == "delete":
            ok = core.palette_delete(d.get("id"))
        elif what == "order":
            ok = core.palette_order(d.get("order"))
        else:
            ok = core.palette_reset(d.get("id") or None)
        if not ok:
            return self.send("Not possible (an unknown colour, not #rrggbb, one that cannot be deleted, or the palette is full)", "text/plain; charset=utf-8", status=400)
        self.send(json.dumps(_palette_reply(extra)), "application/json")

    def _post_pin(self):
        """Set, change or remove the PIN: {"pin": "1234"} (4 to 64 characters) or {"pin": ""} (remove it, and with it the lock on Settings).
        The PIN in use (when there is one) was checked before this: the page sends it in X-Pin."""
        try:
            pin = json.loads(self._body(1024).decode("utf-8")).get("pin")
            if not isinstance(pin, type(u"")):
                raise ValueError("pin needed")
            if pin:
                security.set_pin(pin)
            else:
                security.clear_pin()
                core.save_settings_pin(False)
        except (ValueError, AttributeError, IOError, OSError) as e:
            return self.send("Bad request: %s" % e, "text/plain; charset=utf-8", status=400)
        core.log("web page: the PIN was %s" % ("set" if pin else "removed"))
        self.send(json.dumps({"pin": security.pin_required()}), "application/json")

    def _post_settings_pin(self):
        """Appearance > Ask for the PIN: {"value": true | false}. Needs a PIN to exist."""
        try:
            want = json.loads(self._body(1024).decode("utf-8")).get("value")
            if not isinstance(want, bool):
                raise ValueError("value must be true or false")
        except (ValueError, AttributeError, IOError, OSError) as e:
            return self.send("Bad request: %s" % e, "text/plain; charset=utf-8", status=400)
        if want and not security.pin_required():
            return self.send("Set a PIN first", "text/plain; charset=utf-8", status=409)
        core.save_settings_pin(want)
        self.send(json.dumps({"on": security.settings_locked()}), "application/json")

    def _post_screen(self, path):
        """Settings > Appearance: /screen = {"values": {"dash_cols", "set_cols"}} (the form widget); /screen/stretch and /screen/scale =
        {"value": true | false} (the toggles)."""
        try:
            data = json.loads(self._body(1024).decode("utf-8"))
            if path == "/screen":
                vals = dict((k, (data.get("values") or {}).get(k)) for k in ("dash_cols", "set_cols", "theme", "font_scale", "font_colour", "sound_name", "sound_volume") if k in (data.get("values") or {}))
                if vals.get("sound_name") == "off":          # "Off" in the sound list switches the button sounds off (the file name is kept)
                    vals.pop("sound_name")
                    vals["sound"] = False
                elif "sound_name" in vals:
                    vals["sound"] = True
                core.save_screen_settings(vals)
                refresh_page(force=True)                # the page is built with the theme it starts in (no flash of the other one)
            else:
                core.save_screen_settings({path.rsplit("/", 1)[1]: data.get("value")})
        except (ValueError, AttributeError, IOError, OSError) as e:
            return self.send("Bad request: %s" % e, "text/plain; charset=utf-8", status=400)
        self.send(json.dumps(_screen_reply()), "application/json")

    def _post_timezone(self):
        """Settings > About > Time zone: {"values": {"zone": "" | IANA name}} (the form widget's format)."""
        try:
            values = json.loads(self._body(1024).decode("utf-8")).get("values") or {}
            core.save_time_zone(values.get("zone"))
        except (ValueError, AttributeError, IOError, OSError) as e:
            return self.send("Bad request: %s" % e, "text/plain; charset=utf-8", status=400)
        self.send(json.dumps(_timezone_reply()), "application/json")

    def log_message(self, *args):
        pass


class Server(ThreadingMixIn, HTTPServer):
    """One thread per request, so a slow client never blocks the page.
    Listens on IPv6 and IPv4 when it can: phones often try the IPv6 address
    of the machine's .local name first, and an IPv4-only server makes them wait."""
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
        return core.PROJECT.get("hostname", "localhost")

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
    for target in (watchdog,):
        t = threading.Thread(target=target)
        t.daemon = True
        t.start()
    start_https()
    refresh_page()
    modules.start_background()           # modules' own background work (an update check, a service ...)
    Server(("", PORT), Handler).serve_forever()
