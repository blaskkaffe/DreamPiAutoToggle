#!/usr/bin/env python3
"""checkin-pxe: who may network-boot, and what each computer boots.

Every computer that asks to boot is remembered (serial number and MAC address) in the "has connected" list, but only one on the whitelist
gets a boot script; the others see a message with their numbers. Approve them here.

  checkin-pxe list                           the computers that have connected: status (allowed / PENDING / blocked), MAC, address, last seen, settings
  checkin-pxe pending                        only the ones waiting for a decision
  checkin-pxe allow <serial or MAC> ...      put on the whitelist (also before it has ever connected)
  checkin-pxe block <serial or MAC> ...      never boots (a block wins over the whitelist)
  checkin-pxe clear <serial or MAC> ...      off both lists (it is pending again)
  checkin-pxe mode whitelist | open          whitelist (the default): only approved computers boot; open: everybody boots (no checks)
  checkin-pxe images                         the images the menu offers
  checkin-pxe assign <serial> <image> [--location "Område A,Område B"] [--board-url http://..] [--args "kernel arguments"]
                                             boot settings for that computer: it skips the menu and boots the image (I during the boot = install)
  checkin-pxe unassign <serial>              it gets the menu again
  checkin-pxe reinstall <serial>             a computer that was installed on its own disk boots from the network again
  checkin-pxe forget <serial>                remove it from the has-connected list

<serial> is the id in the list (the serial number in lower case; "mac-<mac without dashes>" for a computer with no usable serial number).
A whitelist entry matches a computer by its name OR by its MAC address."""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import pxe_boot  # noqa: E402

ROOT = os.environ.get("CHECKIN_PXE_DIR", "/opt/checkin-board-pxe")


def main(argv):
    store = pxe_boot.Store(os.path.join(ROOT, "data"))
    cmd = argv[0] if argv else ""
    images = pxe_boot.load_images(os.path.join(ROOT, "www"))
    if cmd in ("list", "pending"):
        reg, ass = store.registry(), store.assignments()
        acc = store.access()
        print("Mode: %s%s" % (acc["mode"], "" if acc["mode"] == "whitelist" else "  (everybody boots; checkin-pxe mode whitelist to check)"))
        print("%-9s %-24s %-17s %-15s %-16s %s" % ("STATUS", "ID", "MAC", "ADDRESS", "LAST SEEN", "BOOTS"))
        for ident in sorted(set(reg) | set(ass) | set(k for k in acc["allow"] + acc["block"] if k not in reg)):
            r = reg.get(ident, {})
            st = store.status(ident, r.get("mac", ""))
            if st == "pending" and acc["mode"] == "whitelist":
                st = "PENDING"
            if cmd == "pending" and st != "PENDING":
                continue
            a = ass.get(ident)
            seen = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["last_seen"])) if r.get("last_seen") else "never"
            to = "menu"
            if a:
                to = a["image"] + "".join("  %s=%s" % (k, a[k]) for k in ("location", "board_url", "args") if a.get(k))
            if r.get("installed"):
                to += "  [installed on its own disk]"
            print("%-9s %-24s %-17s %-15s %-16s %s" % (st, ident, r.get("mac", "-"), r.get("ip", "-"), seen, to))
        return 0
    if cmd in ("allow", "block", "clear") and len(argv) >= 2:
        fn = {"allow": store.allow, "block": store.block, "clear": store.clear_access}[cmd]
        bad = [k for k in argv[1:] if not fn(k)]
        for k in bad:
            print("Not a serial number or MAC address: %s" % k, file=sys.stderr)
        print("done" if not bad else "some entries were not usable")
        return 1 if bad else 0
    if cmd == "mode" and len(argv) == 2 and argv[1] in ("whitelist", "open"):
        store.set_mode(argv[1])
        print("mode: %s" % argv[1])
        return 0
    if cmd == "images":
        for im in pxe_boot.ordered(images):
            print("%-16s %s%s" % (im["id"], im["name"], "  (can be installed)" if im["install_args"] else ""))
        return 0
    if cmd == "assign" and len(argv) >= 3:
        ident, image = argv[1].lower(), argv[2]
        def option(name):
            return argv[argv.index(name) + 1] if name in argv[3:] and argv.index(name) + 1 < len(argv) else ""
        location, board_url, extra = option("--location"), option("--board-url"), option("--args")
        if board_url and not re.match(r"^https?://[A-Za-z0-9._:/-]+$", board_url):
            print("Not a usable board address: %s" % board_url, file=sys.stderr)
            return 1
        if extra and not pxe_boot._EXTRA_ARGS.match(extra):
            print("Not usable as kernel arguments: %s" % extra, file=sys.stderr)
            return 1
        if not pxe_boot.valid_id(ident):
            print("Not a usable id: %s" % ident, file=sys.stderr)
            return 1
        if image not in images:
            print("No such image: %s (checkin-pxe images)" % image, file=sys.stderr)
            return 1
        store.assign(ident, image, location, board_url, extra)
        print("%s boots %s" % (ident, image))
        return 0
    if cmd in ("unassign", "reinstall", "forget") and len(argv) == 2:
        ident = argv[1].lower()
        ok = {"unassign": lambda: store.unassign(ident), "reinstall": lambda: store.set_installed(ident, False), "forget": lambda: store.forget(ident)}[cmd]()
        print("done" if ok else "no such computer: %s" % ident)
        return 0 if ok else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
