"""The disk server: answers the RP2040's sector requests from the image file,
applies queued edits at safe moments, and triggers history snapshots after the
Dreamcast has finished writing."""
import errno
import logging
import os
import select
import struct
import termios
import threading
import time
import tty

from . import protocol as P
from .fatimage import FatImage

log = logging.getLogger("dcbridge-saves")

COLD_SESSION_MS = 5000      # bus silence before CMD0 that means "fresh boot, FAT not mounted"
QUIET_S = 4.0               # no writes for this long => openMenu is done, snapshot
LOCK_WAIT_S = 1.5           # KOS polls ACMD41 for ~3 s at init speed; stay well inside


class Service(object):
    """Owns the image, the store and the disk server thread."""

    def __init__(self, image, store, tty_path):
        self.image = image
        self.store = store
        self.tty_path = tty_path
        self.fat = FatImage(image)
        self.fat_lock = threading.RLock()       # serialises every mtools call
        self.sectors = os.path.getsize(image) // P.SECTOR
        self.status = {
            "connected": False, "daemon_started": time.time(), "last_session": None,
            "last_session_cold": None, "last_write": None, "last_read": None,
            "sessions": 0, "reads": 0, "writes": 0, "edits_applied": 0, "last_scan": None,
            "scan_running": False, "recent": [],
        }
        self._session_reads = 0
        self._dirty = False
        self._scan_now = threading.Event()
        self._stop = threading.Event()

    # ---------------------------------------------------------- lifecycle
    def start(self):
        threading.Thread(target=self._scanner, name="scanner", daemon=True).start()
        self._scan_now.set()                                 # initial scan
        if self.tty_path:
            threading.Thread(target=self._disk_loop, name="disk", daemon=True).start()

    def stop(self):
        self._stop.set()
        self._scan_now.set()

    def request_scan(self):
        self._scan_now.set()

    # ---------------------------------------------------------- scanning
    def _scanner(self):
        while not self._stop.is_set():
            self._scan_now.wait(1.0)
            due = self._dirty and self.status["last_write"] and time.time() - self.status["last_write"] >= QUIET_S
            if not (self._scan_now.is_set() or due):
                continue
            self._scan_now.clear()
            self._dirty = False
            self.status["scan_running"] = True
            try:
                changes = self.store.rescan(self.fat, self.fat_lock)
                self.status["last_scan"] = time.time()
                for serial, slot in changes:
                    log.info("new save version: %s slot %d", serial, slot)
            except Exception:
                log.exception("scan failed")
            finally:
                self.status["scan_running"] = False

    # ---------------------------------------------------------- disk server
    def _disk_loop(self):
        img_fd = os.open(self.image, os.O_RDWR)
        while not self._stop.is_set():
            try:
                fd = os.open(self.tty_path, os.O_RDWR | os.O_NOCTTY)
            except OSError as e:
                if e.errno not in (errno.ENOENT, errno.ENODEV, errno.EACCES, errno.EBUSY):
                    log.warning("open %s: %s", self.tty_path, e)
                time.sleep(2)
                continue
            try:
                try:
                    tty.setraw(fd)
                    attrs = termios.tcgetattr(fd)
                    attrs[2] |= termios.CLOCAL       # no modem-control hangups
                    termios.tcsetattr(fd, termios.TCSANOW, attrs)
                except termios.error:
                    pass                              # a pipe/pty in tests
                log.info("connected to %s", self.tty_path)
                self.status["connected"] = True
                self._serve(fd, img_fd)
            except OSError as e:
                log.warning("disk link lost: %s", e)
            finally:
                self.status["connected"] = False
                try:
                    os.close(fd)
                except OSError:
                    pass
            time.sleep(0.5)

    def _send(self, fd, b):
        view = memoryview(b)
        while view:
            n = os.write(fd, view)
            view = view[n:]

    def _serve(self, fd, img_fd):
        reader = P.FrameReader()
        while not self._stop.is_set():
            r, _, _ = select.select([fd], [], [], 0.5)
            if not r:
                if self._dirty and time.time() - self.status["last_write"] >= QUIET_S:
                    os.fsync(img_fd)
                    self._scan_now.set()
                continue
            chunk = os.read(fd, 8192)
            if not chunk:
                raise OSError(errno.EIO, "device closed")
            out = []
            for ftype, payload in reader.feed(chunk):
                out.append(self.handle(ftype, payload, img_fd))
            if out:
                self._send(fd, b"".join(x for x in out if x))

    def _note(self, kind, lba, count):
        """What the Dreamcast asked the Pi for (reads the RP2040 could answer from its own cache never get here): the last few in
        /api/status "recent", and the first ones after each card start in the log, to see how far openMenu gets."""
        recent = self.status["recent"]
        recent.append("%s %d x%d" % (kind, lba, count))
        del recent[:-16]
        self._session_reads += 1
        if self._session_reads <= 12:
            log.info("%s lba %d x%d", kind, lba, count)

    def handle(self, ftype, payload, img_fd):
        """One request from the RP2040 -> reply bytes. Separate for testing."""
        if ftype == P.READ and len(payload) >= 6:
            lba, count = struct.unpack_from("<IH", payload)
            self.status["reads"] += 1
            self.status["last_read"] = time.time()
            self._note("read", lba, count)
            parts = []
            for i in range(min(count, 64)):
                n = lba + i
                if n >= self.sectors:
                    break
                sec = os.pread(img_fd, P.SECTOR, n * P.SECTOR)
                parts.append(P.data(n, sec.ljust(P.SECTOR, b"\0")))
            return b"".join(parts)

        if ftype == P.WRITE and len(payload) == 4 + P.SECTOR:
            lba = struct.unpack_from("<I", payload)[0]
            self._note("write", lba, 1)
            if lba < self.sectors:
                os.pwrite(img_fd, payload[4:], lba * P.SECTOR)
            self.status["writes"] += 1
            self.status["last_write"] = time.time()
            self._dirty = True
            return P.wack(lba)

        if ftype == P.SESSION and len(payload) >= 8:
            session, idle_ms = struct.unpack_from("<II", payload)
            cold = idle_ms >= COLD_SESSION_MS
            flags = 0
            self.status["sessions"] += 1
            self._session_reads = 0
            self.status["last_session"] = time.time()
            self.status["last_session_cold"] = cold
            if cold and self.store.pending_list():
                os.fsync(img_fd)
                if self.fat_lock.acquire(timeout=LOCK_WAIT_S):
                    try:
                        n = self.store.apply_pending(self.fat)
                        if n:
                            flags |= P.FLAG_INVALIDATE
                            self.status["edits_applied"] += n
                            log.info("applied %d queued edit(s) at card start", n)
                    except Exception:
                        flags |= P.FLAG_INVALIDATE   # may be half-applied: drop RP2040 cache
                        log.exception("applying edits failed")
                    finally:
                        self.fat_lock.release()
                    self._scan_now.set()
                else:
                    log.warning("card start while busy scanning: edits stay queued")
            log.info("card start (%s, bus idle %d ms)", "cold" if cold else "re-init", idle_ms)
            return P.ready(session, self.sectors, flags)

        if ftype == P.HELLO:
            log.info("RP2040 says hello (%s)", payload.hex() if hasattr(payload, "hex") else "")
            return b""
        return b""
