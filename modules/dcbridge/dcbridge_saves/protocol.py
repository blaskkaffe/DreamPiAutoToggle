"""Frame format shared with firmware/src/sd_link.h.

    D5 C3 <type> 00 <len u16 le> <payload>
"""
import struct

SYNC = b"\xD5\xC3"
HDR = 6
SECTOR = 512

HELLO, SESSION, READ, WRITE = 0x01, 0x02, 0x03, 0x04
READY, DATA, WACK = 0x81, 0x82, 0x83

FLAG_INVALIDATE = 1


def frame(ftype, payload=b""):
    return SYNC + struct.pack("<BBH", ftype, 0, len(payload)) + payload


def ready(session, sectors, flags):
    return frame(READY, struct.pack("<III", session, sectors, flags))


def data(lba, sector):
    return frame(DATA, struct.pack("<I", lba) + sector)


def wack(lba):
    return frame(WACK, struct.pack("<I", lba))


class FrameReader(object):
    """Incremental parser. feed() bytes, iterate frames as (type, payload)."""

    MAX_LEN = 4 + SECTOR + 16

    def __init__(self):
        self.buf = bytearray()
        self.resyncs = 0

    def feed(self, chunk):
        self.buf.extend(chunk)
        out = []
        while True:
            i = self.buf.find(SYNC)
            if i < 0:
                if self.buf:
                    self.resyncs += 1
                # keep a trailing D5 that may start the next sync
                self.buf = self.buf[-1:] if self.buf[-1:] == b"\xD5" else bytearray()
                return out
            if i > 0:
                self.resyncs += 1
                del self.buf[:i]
            if len(self.buf) < HDR:
                return out
            ftype, _, length = struct.unpack_from("<BBH", self.buf, 2)
            if length > self.MAX_LEN:
                self.resyncs += 1
                del self.buf[:2]
                continue
            if len(self.buf) < HDR + length:
                return out
            out.append((ftype, bytes(self.buf[HDR:HDR + length])))
            del self.buf[:HDR + length]
