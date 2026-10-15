#!/usr/bin/env python3
"""End-to-end: real daemon (dcbridge_saves) <-> pty <-> test_e2e (KOS sd.c port
+ firmware sd_emu/sd_link). Usage: python3 e2e.py <path-to-test_e2e-binary>"""
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "..", "..", "modules", "dcbridge"))

from dcbridge_saves import VMU_SIZE                      # noqa: E402
from dcbridge_saves.fatimage import create_image          # noqa: E402
from dcbridge_saves.store import SaveStore                # noqa: E402
from dcbridge_saves.daemon import Service                 # noqa: E402

logging.basicConfig(level=logging.INFO, format="  daemon: %(message)s")


def vmu(seed):
    return bytes((i * 13 + seed) & 0xFF for i in range(VMU_SIZE))


def main():
    exe = sys.argv[1]
    tmp = tempfile.mkdtemp()
    try:
        img = os.path.join(tmp, "sd.img")
        fat = create_image(img, 64)
        fat.write("/OPENMENU/SAVES/T-36802N/SLOT1.VMU", vmu(1))
        fat.write("/OPENMENU/SAVES/T-36802N/TITLE.TXT", b"Sonic Adventure 2")
        fat.write("/OPENMENU/LASTDISC.TXT", b"T-36802N-1")
        store = SaveStore(os.path.join(tmp, "state"))
        store.queue_put("T-36802N", 2, vmu(2))          # uploaded from the web page

        master, slave = os.openpty()
        svc = Service(img, store, os.ttyname(slave))
        svc.start()
        time.sleep(0.5)
        rc = subprocess.call([exe, str(master), img], pass_fds=[master])
        assert rc == 0, "C side failed (%d)" % rc

        assert store.pending_list() == [], "edit not applied"
        assert fat.read("/OPENMENU/SAVES/T-36802N/SLOT2.VMU") == vmu(2), "upload missing on card"
        time.sleep(5)                                     # quiet period -> snapshot
        hist = store.history_list("T-36802N", 2)
        print("history for slot 2:", [h["reason"] for h in hist])
        assert hist and hist[0]["reason"] == "upload"
        print("status:", {k: svc.status[k] for k in ("sessions", "reads", "writes", "edits_applied")})
        print("E2E PYTHON CHECKS OK")
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
