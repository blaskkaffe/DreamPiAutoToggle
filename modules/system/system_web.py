# Check-in add-on - system module, web side: GET /about, the name / value rows under Settings > About (the version of the add-on,
# the address, the computer and its system, and the PIN state). Other modules add rows with an about_rows() function, collected by
# the base: modules.collect("about_rows").
import base64
import binascii
import io
import json
import os
import re
import socket
import time
import zipfile

import base_core as core
import base_modules as modules
import base_security as security

VERSION_FILE = os.path.join(core.INSTALL_DIR, "version")      # written by install.sh: date and commit of the installed checkout


def lan_ip():
    """The computer's address on the local network (the one its default route uses; no packet is sent), or None."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("192.0.2.1", 9))   # documentation address, never contacted
            ip = sock.getsockname()[0]
        finally:
            sock.close()
        return None if ip.startswith("0.") else ip
    except (socket.error, OSError):
        return None


def about():
    """[(name, value)] rows for Settings > About."""
    model = core.read_file("/proc/device-tree/model")
    osname = None
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    osname = line.split("=", 1)[1].strip().strip('"')
    except (IOError, OSError):
        pass
    return [("Add-on", core.read_file(VERSION_FILE) or "unknown"),
            ("Address", lan_ip() or "unknown"),
            ("Computer", (model or "unknown").replace("\x00", "")),
            ("System", osname or "unknown")]


def _about(h):
    rows = about() + [tuple(r) for r in modules.collect("about_rows")]
    rows.append(("PIN", "Asked before update and restart" if security.pin_required()
                 else "Off: anyone on your network can update or restart (install.sh --pin sets one)"))
    h.send(json.dumps(rows), "application/json")


# ---- Backup: one zip with the settings and the people, and the way back --------------------------------------------------------
# What is saved is every data file the add-on keeps in its folder: the *.json files (the roster, the board, the modules switched on, the palette, the screen
# settings ...), the time zone, the language, the background picture, the profile photos and the settings of single kiosk screens. Not saved: the PINs, the
# HTTPS key, the allowed host names and the update origin (they belong to this computer, and a backup is easy to pass around), and no program files.
NOT_DATA = ("project.json", "layout.json", "module.json")
BACKUP_FILES = ("time_zone", "language", "background_image")
BACKUP_DIRS = {"photos": re.compile(r"^p[0-9a-f]{1,16}\.(jpg|png)$"), "screens": re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}/[a-z_]+\.json$")}
INFO = "backup.info"
MAX_BACKUP = 40 * 1000 * 1000          # bytes of the zip, and of what it unpacks to


def _member_ok(name):
    """Is `name` (a path inside a backup zip) a file this add-on may write? Only the names it keeps itself: nothing outside its folder, no program."""
    if not name or name.startswith("/") or "\\" in name or ".." in name.split("/") or "\0" in name:
        return False
    top, _slash, rest = name.partition("/")
    if not rest:
        return (name in BACKUP_FILES or (re.match(r"^[a-z_]{1,40}\.json$", name) is not None and name not in NOT_DATA and not name.startswith("lang_")))
    return top in BACKUP_DIRS and BACKUP_DIRS[top].match(rest) is not None


def _data_files():
    """[(path inside the zip, path on disk)] of everything a backup holds."""
    out = []
    try:
        names = sorted(os.listdir(core.BASE_DIR))
    except OSError:
        return out
    for n in names:
        path = os.path.join(core.BASE_DIR, n)
        if os.path.isfile(path) and _member_ok(n):
            out.append((n, path))
        elif os.path.isdir(path) and n in BACKUP_DIRS:
            for root, _dirs, files in os.walk(path):
                for f in sorted(files):
                    rel = os.path.relpath(os.path.join(root, f), core.BASE_DIR).replace(os.sep, "/")
                    if _member_ok(rel):
                        out.append((rel, os.path.join(root, f)))
    return out


def make_backup():
    """The backup as the bytes of a zip file."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(INFO, "%s\nadd-on %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), core.read_file(VERSION_FILE) or "unknown"))
        for name, path in _data_files():
            try:
                z.write(path, name)
            except (IOError, OSError):
                pass
    return buf.getvalue()


def restore_backup(data):
    """Put a backup zip's files in place of the current ones. (ok, message). Nothing is touched unless the whole zip is good."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        infos = [i for i in z.infolist() if not i.filename.endswith("/")]
        if not any(i.filename == INFO for i in infos):
            return False, "That is not a backup made by this add-on"
        if sum(i.file_size for i in infos) > MAX_BACKUP:
            return False, "That backup is too big"
        files = {}
        for i in infos:
            if i.filename == INFO:
                continue
            if not _member_ok(i.filename):
                return False, "The backup holds a file that does not belong in it: " + i.filename[:60]
            raw = z.read(i)
            if i.filename.endswith(".json"):
                json.loads(raw.decode("utf-8"))
            files[i.filename] = raw
    except (zipfile.BadZipFile, ValueError, UnicodeDecodeError, KeyError, RuntimeError, NotImplementedError):
        return False, "That is not a readable backup file"
    for name, path in _data_files():                   # the backup's state replaces this one, so what it lacks goes away
        if name not in files:
            try:
                os.remove(path)
            except OSError:
                pass
    for name, raw in files.items():
        path = os.path.join(core.BASE_DIR, *name.split("/"))
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(raw)
        os.rename(tmp, path)
    modules.refresh(True)
    core.log("backup restored (%d files)" % len(files))
    return True, "Restored %d files" % len(files)


def _get_backup(h):
    h.send(make_backup(), "application/zip", download="backup-%s.zip" % time.strftime("%Y-%m-%d-%H%M"))


def _post_restore(h):
    try:
        body = json.loads(h._body(MAX_BACKUP * 4 // 3 + 4096).decode("utf-8"))
        data = base64.b64decode(str(body.get("backup", "")).encode("ascii"), validate=True)
    except (ValueError, UnicodeDecodeError, AttributeError, binascii.Error):
        h.send(json.dumps({"ok": False, "message": "That is not a backup file"}), "application/json", status=400)
        return True
    ok, message = restore_backup(data)
    h.send(json.dumps({"ok": ok, "message": message}), "application/json", status=200 if ok else 400)
    return True


GET = {"/about": _about, "/backup": _get_backup}
POST = {"/backup/restore": _post_restore}
PROTECTED = ("/backup/restore",)
