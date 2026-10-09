#!/usr/bin/env python3
"""The network boot server's web side (port 8069 by default): the kernels and images as plain files, and what a booting computer asks.

    pxe_server.py --ip 192.168.1.20 --port 8069 --dir /opt/checkin-board-pxe --board-url http://192.168.1.20/

  GET /boot?serial=..&mac=..&product=..&ip=..   the iPXE script for that computer. It is always remembered (serial number and MAC address,
                                                the "has connected" list); only a computer on the whitelist gets a boot script, the others a message
  GET /installed?id=<id>                        an approved computer says it now has the system on its own disk (it boots that from now on)
  GET /images/<id>/<file>                       the image files, only for the address of a computer that was just approved (no folder listings)

Everything is read from <dir>/data (registry.json, assignments.json) and <dir>/www/images/<id>/image.json at the moment of the request, so
the admin tool (checkin-pxe) and a new image folder take effect at the next boot. Only this server's own LAN should reach it."""
import argparse
import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pxe_boot  # noqa: E402


class Handler(SimpleHTTPRequestHandler):
    server_version = "checkin-pxe"

    def __init__(self, *args, store, server_url, board_url, **kw):
        self.store, self.server_url, self.board_url = store, server_url, board_url
        super().__init__(*args, **kw)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.client_address[0], fmt % args))

    def list_directory(self, path):
        self.send_error(404)
        return None

    def reply(self, text, status=200):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        q = dict((k, v[0]) for k, v in parse_qs(url.query).items())
        if url.path == "/boot":
            return self.reply(self.boot(q, self.client_address[0]))
        if url.path == "/installed":
            ident = q.get("id", "")
            if not self.store.granted(self.client_address[0]):
                return self.reply("not approved\n", 403)
            if not pxe_boot.valid_id(ident) or not self.store.set_installed(ident):
                return self.reply("unknown computer\n", 404)
            return self.reply("ok\n")
        if url.path.startswith("/images/") and not self.store.granted(self.client_address[0]):
            return self.reply("not approved\n", 403)
        return super().do_GET()

    def boot(self, q, peer):
        serial, mac = q.get("serial", ""), pxe_boot.clean_mac(q.get("mac", ""))
        ident = pxe_boot.machine_id(serial, mac)
        if not ident:                                  # it told neither a serial number nor a MAC address: nothing to remember, and not on any list
            ident = "unknown"
            machine = {}
        else:
            machine = self.store.register(ident, serial, mac, q.get("ip") or peer, q.get("product", ""))
        status = self.store.status(ident, mac)
        if status != "allowed":
            return pxe_boot.refusal_script(ident, serial, mac, status)
        self.store.grant(peer)
        images = pxe_boot.load_images(self.directory)
        return pxe_boot.boot_script(ident, serial, mac, machine, images, self.store.assignments().get(ident), self.server_url, self.board_url)


def make_server(ip, port, root, board_url):
    store = pxe_boot.Store(os.path.join(root, "data"))
    os.makedirs(store.dir, exist_ok=True)
    handler = partial(Handler, directory=os.path.join(root, "www"), store=store, server_url="http://%s:%d" % (ip, port), board_url=board_url)
    server = ThreadingHTTPServer((ip, port), handler)
    server.store = store
    return server


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ip", required=True)
    ap.add_argument("--port", type=int, default=8069)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--board-url", required=True)
    a = ap.parse_args()
    make_server(a.ip, a.port, a.dir, a.board_url).serve_forever()


if __name__ == "__main__":
    main()
