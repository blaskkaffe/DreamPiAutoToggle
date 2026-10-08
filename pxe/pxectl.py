#!/usr/bin/env python3
"""checkin-pxe: tells the network boot server which screens boot what.

  checkin-pxe list                           the computers that have booted (serial number, MAC, address, last time) and what they are set to
  checkin-pxe images                         the images the menu offers
  checkin-pxe assign <serial> <image> [--location "Område A,Område B"]
                                             that computer skips the menu and boots the image straight away (I during the boot = install)
  checkin-pxe unassign <serial>              it gets the menu again
  checkin-pxe reinstall <serial>             a computer that was installed on its own disk boots from the network again
  checkin-pxe forget <serial>                remove it from the list

<serial> is the id in the list (the serial number in lower case; "mac-<mac>" for a computer with no usable serial number)."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import pxe_boot  # noqa: E402

ROOT = os.environ.get("CHECKIN_PXE_DIR", "/opt/checkin-board-pxe")


def main(argv):
    store = pxe_boot.Store(os.path.join(ROOT, "data"))
    cmd = argv[0] if argv else ""
    images = pxe_boot.load_images(os.path.join(ROOT, "www"))
    if cmd == "list":
        reg, ass = store.registry(), store.assignments()
        print("%-24s %-17s %-15s %-16s %s" % ("ID", "MAC", "ADDRESS", "LAST SEEN", "SET TO"))
        for ident in sorted(set(reg) | set(ass)):
            r = reg.get(ident, {})
            a = ass.get(ident)
            seen = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["last_seen"])) if r.get("last_seen") else "-"
            to = ("%s%s" % (a["image"], " (%s)" % a["location"] if a.get("location") else "")) if a else "menu"
            if r.get("installed"):
                to += "  [installed on its own disk]"
            print("%-24s %-17s %-15s %-16s %s" % (ident, r.get("mac", "-"), r.get("ip", "-"), seen, to))
        return 0
    if cmd == "images":
        for im in pxe_boot.ordered(images):
            print("%-16s %s%s" % (im["id"], im["name"], "  (can be installed)" if im["install_args"] else ""))
        return 0
    if cmd == "assign" and len(argv) >= 3:
        ident, image = argv[1].lower(), argv[2]
        location = argv[argv.index("--location") + 1] if "--location" in argv[3:] and argv.index("--location") + 1 < len(argv) else ""
        if not pxe_boot.valid_id(ident):
            print("Not a usable id: %s" % ident, file=sys.stderr)
            return 1
        if image not in images:
            print("No such image: %s (checkin-pxe images)" % image, file=sys.stderr)
            return 1
        store.assign(ident, image, location)
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
