"""The SD card image: creation (MBR + one FAT32 partition) and file access
through mtools, without mounting anything."""
import os
import struct
import subprocess
import tempfile

SECTOR = 512
PART_START = 2048                     # 1 MiB alignment, like real cards


class FatError(Exception):
    pass


def _env():
    env = dict(os.environ)
    env["MTOOLS_SKIP_CHECK"] = "1"     # do not complain about odd geometry
    env["MTOOLSRC"] = "/dev/null"      # ignore any system drive config
    return env


def create_image(path, size_mb=128, label="DCSAVES"):
    """Create a sparse image with an MBR and a single FAT32 partition."""
    if os.path.exists(path):
        raise FatError("%s already exists" % path)
    if size_mb < 64 or size_mb % 1 != 0 or size_mb != int(size_mb):
        raise FatError("size must be at least 64 MiB")
    total = size_mb * 1024 * 1024
    part_sectors = total // SECTOR - PART_START

    d = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(d):
        os.makedirs(d)
    fd, fs_path = tempfile.mkstemp(prefix=".dcfs-", dir=d)
    os.close(fd)
    try:
        with open(fs_path, "r+b") as f:
            f.truncate(part_sectors * SECTOR)
        subprocess.check_call(["mkfs.fat", "-F", "32", "-n", label, fs_path],
                              stdout=subprocess.DEVNULL)
        mbr = bytearray(SECTOR)
        # status, CHS first (dummy), type 0x0C FAT32 LBA, CHS last (dummy), LBA start, sectors
        mbr[446:462] = struct.pack("<B3sB3sII", 0x00, b"\x00\x02\x00", 0x0C, b"\xff\xff\xff",
                                   PART_START, part_sectors)
        mbr[510:512] = b"\x55\xAA"
        with open(path, "wb") as out, open(fs_path, "rb") as src:
            out.truncate(total)
            out.write(mbr)
            out.seek(PART_START * SECTOR)
            zero = bytes(65536)
            while True:
                chunk = src.read(65536)
                if not chunk:
                    break
                if chunk == zero[:len(chunk)]:
                    out.seek(len(chunk), os.SEEK_CUR)      # keep it sparse
                else:
                    out.write(chunk)
    finally:
        os.unlink(fs_path)
    fat = FatImage(path)
    fat.makedirs("/OPENMENU/SAVES")
    return fat


def partition_offset(path):
    with open(path, "rb") as f:
        mbr = f.read(SECTOR)
    if len(mbr) < SECTOR or mbr[510:512] != b"\x55\xAA":
        raise FatError("%s has no MBR" % path)
    start = struct.unpack_from("<I", mbr, 446 + 8)[0]
    if not start:
        raise FatError("%s: partition 1 is empty" % path)
    return start * SECTOR


class FatImage(object):
    """Thin wrapper around mtools for the first partition of the image."""

    def __init__(self, path):
        self.path = path
        self.spec = "%s@@%d" % (path, partition_offset(path))

    def _run(self, args, check=True):
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_env())
        out, err = p.communicate()
        if check and p.returncode != 0:
            raise FatError("%s failed: %s" % (" ".join(args[:1] + args[3:]), err.decode("utf-8", "replace").strip()))
        return p.returncode, out

    @staticmethod
    def _m(path):
        return "::" + path

    def walk(self, root):
        """All paths below root. Directories end with '/'."""
        rc, out = self._run(["mdir", "-i", self.spec, "-b", "-/", self._m(root)], check=False)
        if rc != 0:
            return []
        paths = []
        for line in out.decode("utf-8", "replace").splitlines():
            line = line.strip()
            if line.startswith("::"):
                paths.append(line[2:])
        return paths

    def exists(self, path):
        rc, _ = self._run(["mdir", "-i", self.spec, "-b", self._m(path)], check=False)
        return rc == 0

    def read(self, path):
        rc, out = self._run(["mcopy", "-n", "-i", self.spec, self._m(path), "-"], check=False)
        return out if rc == 0 else None

    def makedirs(self, path):
        cur = ""
        for part in [p for p in path.split("/") if p]:
            cur += "/" + part
            if not self.exists(cur):
                self._run(["mmd", "-i", self.spec, self._m(cur)])

    def write(self, path, data):
        self.makedirs(os.path.dirname(path))
        fd, tmp = tempfile.mkstemp(prefix=".dcput-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            self._run(["mcopy", "-o", "-D", "o", "-i", self.spec, tmp, self._m(path)])
        finally:
            os.unlink(tmp)

    def delete(self, path):
        if self.exists(path):
            self._run(["mdel", "-i", self.spec, self._m(path)])
