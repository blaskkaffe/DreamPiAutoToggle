"""Command line: python3 -m dcbridge_saves <command> ...

  serve                      run the disk server + web page (what systemd starts)
  create-image [--size MB]   make a new, empty card image
  list                       games and slots on the card
  download SERIAL SLOT FILE  copy a save out of the card
  upload SERIAL SLOT FILE    queue a save to be written to the card
  label SERIAL SLOT TEXT     queue a slot label ("" removes it)
  delete SERIAL SLOT         queue removal of a slot (old copy kept in history)
  history SERIAL SLOT        list stored versions
  restore SERIAL SLOT ID     queue an old version
  pending                    queued edits
  bridge                     RP2040 mode and network link state
  cancel ID                  drop a queued edit
"""
import argparse
import json
import logging
import os
import socketserver
import sys
import time
from wsgiref.simple_server import WSGIServer, WSGIRequestHandler, make_server

from . import __version__
from .daemon import Service
from .fatimage import FatImage, create_image
from .store import SaveStore, StoreError, slot_path

DEFAULT_IMAGE = "/var/lib/dcbridge/sdcard.img"
DEFAULT_STATE = "/var/lib/dcbridge/saves"
DEFAULT_TTY = "/dev/dcbridge-disk"


class ThreadingWSGIServer(socketserver.ThreadingMixIn, WSGIServer):
    daemon_threads = True


class QuietHandler(WSGIRequestHandler):
    def log_message(self, fmt, *args):
        logging.getLogger("dcbridge-saves.http").debug(fmt, *args)


def _ts(t):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "-"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dcbridge-saves", description="dcbridge virtual SD card + save manager")
    ap.add_argument("--image", default=os.environ.get("DCB_IMAGE", DEFAULT_IMAGE))
    ap.add_argument("--state", default=os.environ.get("DCB_STATE", DEFAULT_STATE))
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("serve")
    p.add_argument("--tty", default=os.environ.get("DCB_TTY", DEFAULT_TTY))
    p.add_argument("--host", default=os.environ.get("DCB_HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.environ.get("DCB_PORT", "8085")))
    p.add_argument("--ctl", default=os.environ.get("DCB_CTL", "/dev/dcbridge-ctl"),
                   help="RP2040 status port ('' to disable)")
    p.add_argument("--no-web", action="store_true")
    p.add_argument("--size", type=int, default=128, help="image size in MiB if it has to be created")
    p.add_argument("-v", "--verbose", action="store_true")

    p = sub.add_parser("create-image")
    p.add_argument("--size", type=int, default=128)
    sub.add_parser("list")
    for name in ("download", "upload"):
        p = sub.add_parser(name)
        p.add_argument("serial"); p.add_argument("slot", type=int); p.add_argument("file")
        if name == "upload":
            p.add_argument("--title")
    p = sub.add_parser("label"); p.add_argument("serial"); p.add_argument("slot", type=int); p.add_argument("text")
    p = sub.add_parser("delete"); p.add_argument("serial"); p.add_argument("slot", type=int)
    p = sub.add_parser("history"); p.add_argument("serial"); p.add_argument("slot", type=int)
    p = sub.add_parser("restore"); p.add_argument("serial"); p.add_argument("slot", type=int); p.add_argument("id")
    sub.add_parser("pending")
    p = sub.add_parser("bridge", help="RP2040 mode and network link state (JSON)")
    p.add_argument("--ctl", default="", help="read one status line from this port too")
    p = sub.add_parser("cancel"); p.add_argument("id")

    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2

    if a.cmd == "create-image":
        create_image(a.image, a.size)
        print("created %s (%d MiB)" % (a.image, a.size))
        return 0

    store = SaveStore(a.state)

    try:
        if a.cmd == "serve":
            logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                                format="%(asctime)s %(levelname)s %(message)s")
            if not os.path.exists(a.image):
                create_image(a.image, a.size)
                logging.info("created empty card image %s (%d MiB)", a.image, a.size)
            svc = Service(a.image, store, a.tty)
            svc.start()
            from .bridge import BridgeStatus
            bridge = BridgeStatus(a.ctl or None)
            bridge.start()
            if a.no_web:
                while True:
                    time.sleep(3600)
            from .web import make_app
            httpd = make_server(a.host, a.port, make_app(svc, bridge), server_class=ThreadingWSGIServer,
                                handler_class=QuietHandler)
            logging.info("save manager on http://%s:%d/", a.host, a.port)
            httpd.serve_forever()
            return 0

        if a.cmd == "bridge":
            from .bridge import BridgeStatus
            b = BridgeStatus(a.ctl or None)
            b.start()
            if a.ctl:
                time.sleep(2.5)
            print(json.dumps(b.snapshot(), indent=2))
            return 0
        if a.cmd == "pending":
            for e in store.pending_list():
                print("%s  %-6s %s slot %s %s" % (e["id"], e["action"], e["serial"], e["slot"],
                                                 json.dumps(e.get("label") or e.get("title") or "")))
            return 0
        if a.cmd == "cancel":
            store.pending_cancel(a.id)
            return 0
        if a.cmd == "history":
            for v in store.history_list(a.serial, a.slot):
                print("%s  %s  %-9s %s" % (v["id"], _ts(v["time"]), v["reason"], v["sha1"]))
            return 0
        if a.cmd in ("upload", "label", "delete", "restore"):
            if a.cmd == "upload":
                with open(a.file, "rb") as f:
                    e = store.queue_put(a.serial, a.slot, f.read(), title=a.title)
            elif a.cmd == "label":
                e = store.queue_label(a.serial, a.slot, a.text)
            elif a.cmd == "delete":
                e = store.queue_delete(a.serial, a.slot)
            else:
                e = store.queue_restore(a.serial, a.slot, a.id)
            print("queued %s: it is written to the card the next time openMenu boots" % e["id"])
            return 0

        fat = FatImage(a.image)
        if a.cmd == "list":
            store.rescan(fat)
            for g in store.summary()["games"]:
                print("%s  %s" % (g["serial"], g["title"] or ""))
                for s in g["slots"]:
                    flags = (" [last played]" if s["lastdisc"] else "") + \
                            "".join(" [%s queued]" % x["action"] for x in s["pending"])
                    state = ("ok" if s["valid"] else "WRONG SIZE") if s["on_card"] else "not on card"
                    print("   slot %d  %-11s %-28s %d version(s)%s" % (s["slot"], state, s["label"] or "",
                                                                       s["history"], flags))
            return 0
        if a.cmd == "download":
            data = fat.read(slot_path(a.serial, a.slot))
            if data is None:
                print("no save in that slot", file=sys.stderr)
                return 1
            with open(a.file, "wb") as f:
                f.write(data)
            return 0
    except StoreError as e:
        print("error: %s" % e, file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
