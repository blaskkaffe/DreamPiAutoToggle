"""What the network boot server knows and says: the computers that have booted (by serial number / MAC address), the images it can boot,
which computer is set to which image, and the iPXE script a computer gets when it asks "what do I boot?". Standard library only.

A computer is named by its serial number (the BIOS's system serial) - or, when that is empty or a placeholder like "To Be Filled By O.E.M.",
by its MAC address ("mac-aabbccddeeff"). The same name is the screen id the check-in page keeps the layout under (see base_core.set_screen)."""
import json
import os
import re
import threading
import time
from urllib.parse import quote

JUNK_SERIALS = ("", "0", "none", "null", "n/a", "na", "unknown", "default string", "to be filled by o.e.m.", "system serial number",
                "not specified", "not applicable", "serial number", "123456789", "0123456789", "xxxxxxxx", "chassis serial number",
                "to be filled by oem", "default", "type2 - board serial number")
_MAC = re.compile(r"^[0-9a-f]{2}([-:][0-9a-f]{2}){5}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_MACHINES = 5000
GRANT_SECONDS = 1800          # an approved computer may fetch the images from its address this long after it asked for its boot script
_lock = threading.Lock()
_EXTRA_ARGS = re.compile(r"^[A-Za-z0-9_.=,:/+%@-]+( [A-Za-z0-9_.=,:/+%@-]+)*$")


def clean_mac(text):
    t = (text or "").strip().lower()
    return t.replace(":", "-") if _MAC.match(t) else ""


def machine_id(serial, mac):
    """The name of a computer: its serial number made safe (lower case, other characters to _), else "mac-<mac>"; "" when it gives neither."""
    s = (serial or "").strip()
    if s.lower() not in JUNK_SERIALS and not re.match(r"^(.)\1*$", s):          # not "00000000" / "FFFFFFFF" either
        ident = re.sub(r"[^a-z0-9_-]", "_", s.lower()).strip("_-")[:64]
        if _ID.match(ident):
            return ident
    m = clean_mac(mac)
    return "mac-" + m.replace("-", "") if m else ""


def valid_id(ident):
    return bool(_ID.match(ident or ""))


def _read(path, default):
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, type(default)) else default
    except (IOError, OSError, ValueError):
        return default


def _write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    os.rename(tmp, path)


def access_key(text):
    """What the admin typed in a whitelist: a MAC address (any separator) or a serial number / computer name, normalised; "" when unusable."""
    t = (text or "").strip().lower()
    return clean_mac(t) or (t if _ID.match(t) else "")


class Store(object):
    """In the data folder: registry.json ({id: machine}: every computer that has asked to boot), assignments.json ({id: its boot settings}:
    image, location, board_url, args) and access.json ({"mode": "whitelist" | "open", "allow": [...], "block": [...]}: the entries are computer
    names (serial numbers) or MAC addresses; a computer is allowed when its name or its MAC is on the allow list)."""

    def __init__(self, data_dir):
        self.dir = data_dir
        self.registry_file = os.path.join(data_dir, "registry.json")
        self.assignments_file = os.path.join(data_dir, "assignments.json")
        self.access_file = os.path.join(data_dir, "access.json")
        self._grants = {}

    def access(self):
        a = _read(self.access_file, {})
        return {"mode": "open" if a.get("mode") == "open" else "whitelist",
                "allow": [x for x in a.get("allow", []) if isinstance(x, str)], "block": [x for x in a.get("block", []) if isinstance(x, str)]}

    def status(self, ident, mac=""):
        """"allowed", "blocked" or "pending" (not on any list: it is in the "has connected" list until the admin decides). A block wins."""
        a = self.access()
        keys = set(k for k in (ident, clean_mac(mac)) if k)
        if keys & set(a["block"]):
            return "blocked"
        if a["mode"] == "open" or keys & set(a["allow"]):
            return "allowed"
        return "pending"

    def _set_access(self, key, where):
        k = access_key(key)
        if not k:
            return False
        with _lock:
            a = self.access()
            for name in ("allow", "block"):
                a[name] = [x for x in a[name] if x != k]
            if where:
                a[where].append(k)
                a[where].sort()
            _write(self.access_file, a)
        return True

    def allow(self, key):
        return self._set_access(key, "allow")

    def block(self, key):
        return self._set_access(key, "block")

    def clear_access(self, key):
        return self._set_access(key, None)

    def set_mode(self, mode):
        with _lock:
            a = self.access()
            a["mode"] = "open" if mode == "open" else "whitelist"
            _write(self.access_file, a)

    def grant(self, ip):
        """An approved computer was told its boot script: its address may fetch the images for a while."""
        with _lock:
            now = time.time()
            self._grants = dict((k, v) for k, v in self._grants.items() if v > now)
            self._grants[ip] = now + GRANT_SECONDS

    def granted(self, ip):
        return self._grants.get(ip, 0) > time.time() or self.access()["mode"] == "open"

    def registry(self):
        return _read(self.registry_file, {})

    def assignments(self):
        return _read(self.assignments_file, {})

    def register(self, ident, serial, mac, ip="", product=""):
        """A computer asked what to boot: remember it. Returns its record."""
        with _lock:
            reg = self.registry()
            now = int(time.time())
            rec = reg.get(ident) or {"first_seen": now, "boots": 0, "installed": False}
            if ident not in reg and len(reg) >= MAX_MACHINES:
                return rec
            rec.update({"serial": (serial or "")[:64], "mac": clean_mac(mac), "ip": (ip or "")[:45], "product": (product or "")[:80], "last_seen": now})
            rec["boots"] = int(rec.get("boots", 0)) + 1
            reg[ident] = rec
            _write(self.registry_file, reg)
            return rec

    def set_installed(self, ident, installed=True):
        with _lock:
            reg = self.registry()
            if ident not in reg:
                return False
            reg[ident]["installed"] = bool(installed)
            _write(self.registry_file, reg)
            return True

    def assign(self, ident, image, location="", board_url="", args=""):
        """Boot settings for one computer: the image it boots without the menu, the buildings it shows, another board address, extra kernel arguments."""
        with _lock:
            data = self.assignments()
            data[ident] = {"image": image, "location": location or "", "board_url": board_url or "", "args": args or ""}
            _write(self.assignments_file, data)

    def unassign(self, ident):
        with _lock:
            data = self.assignments()
            found = data.pop(ident, None) is not None
            _write(self.assignments_file, data)
            return found

    def forget(self, ident):
        with _lock:
            reg = self.registry()
            found = reg.pop(ident, None) is not None
            _write(self.registry_file, reg)
            return found


def load_images(www):
    """{id: manifest} for every folder in www/images/ that has an image.json with a name, a kernel and an initrd (the folder name is the id).
    Manifest: name, kernel, initrd (file names in the folder), args (kernel command line), install_args (if the image can be installed on the local
    disk: the command line that starts its installer), shell_args (a command line that opens a shell), order (lower first, default 100).
    In the command lines {base} (this image's folder on the server), {board}, {screen}, {location} and {server} are filled in."""
    out = {}
    root = os.path.join(www, "images")
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for name in names:
        if not valid_id(name):
            continue
        m = _read(os.path.join(root, name, "image.json"), {})
        if not isinstance(m.get("name"), str) or not isinstance(m.get("kernel"), str) or not isinstance(m.get("initrd"), str):
            continue
        if not all(re.match(r"^[A-Za-z0-9._-]+$", m[k]) for k in ("kernel", "initrd")):
            continue
        item = {"id": name, "name": m["name"][:60].replace("\n", " "), "kernel": m["kernel"], "initrd": m["initrd"],
                "args": str(m.get("args", "")), "install_args": str(m.get("install_args", "")), "shell_args": str(m.get("shell_args", "")),
                "order": m.get("order") if isinstance(m.get("order"), int) else 100}
        out[name] = item
    return out


def ordered(images):
    return sorted(images.values(), key=lambda i: (i["order"], i["id"]))


def encode_location(text):
    """Buildings as they go in an address: spaces as +, other characters percent-encoded, a comma between several."""
    return ",".join(quote(p.strip(), safe="").replace("%20", "+") for p in (text or "").split(",") if p.strip())


def _one_line(text):
    return re.sub(r"[\r\n]+", " ", str(text))


def command_line(template, image, server, board, screen, location, extra=""):
    base = "%s/images/%s" % (server, image["id"])
    out = template
    for key, val in (("{base}", base), ("{board}", board), ("{screen}", screen), ("{location}", encode_location(location)), ("{server}", server)):
        out = out.replace(key, val)
    if extra and _EXTRA_ARGS.match(extra):
        out += " " + extra
    return _one_line(out).strip()


def _boot_lines(label, image, args, server, title):
    base = "%s/images/%s" % (server, image["id"])
    return ["", ":%s" % label, "echo %s" % _one_line(title),
            "kernel %s/%s %s || goto failed" % (base, image["kernel"], args),
            "initrd %s/%s || goto failed" % (base, image["initrd"]),
            "boot || goto failed"]


def refusal_script(ident, serial, mac, status):
    """What a computer that is not on the whitelist sees: why, and the numbers the admin needs. Then it boots its own disk."""
    why = "has been blocked" if status == "blocked" else "is not approved yet"
    return "\n".join(["#!ipxe", "echo", "echo This computer %s for network boot." % why,
                       "echo   Serial number: %s" % (_one_line(serial) or "-"), "echo   MAC address:   %s" % (_one_line(mac) or "-"),
                       "echo   Name:          %s" % ident,
                       "echo" if status == "blocked" else "echo Ask the administrator to approve it (checkin-pxe allow %s)." % ident,
                       "sleep 15", "exit", ""])


def boot_script(ident, serial, mac, machine, images, assignment, server, board):
    """The iPXE script for a computer. images: load_images(); assignment: {"image", "location"} or None; machine: its registry record.
    - set to an image: boots it after a short pause (press I there for the local install, if the image has one);
    - installed on its own disk: boots the disk unless N is pressed (then the menu);
    - otherwise a menu: each image, "install on the local disk" and "shell" for those that have them, the iPXE shell, the local disk."""
    lst = ordered(images)
    location = (assignment or {}).get("location", "")
    board = (assignment or {}).get("board_url") or board
    extra = (assignment or {}).get("args", "")
    chosen = images.get((assignment or {}).get("image", ""))
    lines = ["#!ipxe", "echo Connected to the check-in boot server: approved (%s, serial %s, MAC %s)" % (ident, _one_line(serial) or "-", _one_line(mac) or "-")]

    def args_for(image, template):
        return command_line(template, image, server, board, ident, location, extra)

    if machine.get("installed") and not chosen:
        lines += ["prompt --key 0x6e --timeout 3000 Booting from the local disk. Press N for the network boot menu || exit"]
    if chosen:
        if chosen["install_args"]:
            lines += ["prompt --key 0x69 --timeout 3000 Booting %s. Press I to install it on the local disk... || goto assigned" % _one_line(chosen["name"]),
                      "goto install-%s" % chosen["id"]]
        lines += [":assigned", "goto boot-%s" % chosen["id"]]
    lines += ["", ":menu", "menu Check-in screen %s" % ident]
    first = lst[0] if lst else None
    for n, im in enumerate(lst):
        lines.append("item %sboot-%s %s" % ("--key %d " % (n + 1) if n < 9 else "", im["id"], im["name"]))
    for im in lst:
        if im["install_args"]:
            lines.append("item %sinstall-%s Install %s on the local disk" % ("--key i " if im is first else "", im["id"], im["name"]))
    for im in lst:
        if im["shell_args"]:
            lines.append("item %sshell-%s Linux shell (%s)" % ("--key s " if im is first else "", im["id"], im["name"]))
    lines += ["item --gap --", "item ipxeshell iPXE shell", "item local Boot from the local disk"]
    if first:
        lines += ["choose --default boot-%s --timeout 20000 target || goto menu" % first["id"], "goto ${target}"]
    else:
        lines += ["choose --default ipxeshell target || goto menu", "goto ${target}"]
    for im in lst:
        lines += _boot_lines("boot-%s" % im["id"], im, args_for(im, im["args"]), server, "Booting %s" % im["name"])
        if im["install_args"]:
            lines += _boot_lines("install-%s" % im["id"], im, args_for(im, im["install_args"]), server, "Installing %s on the local disk" % im["name"])
        if im["shell_args"]:
            lines += _boot_lines("shell-%s" % im["id"], im, args_for(im, im["shell_args"]), server, "Opening a shell in %s" % im["name"])
    lines += ["", ":ipxeshell", "shell", "goto menu", "", ":local", "exit", "",
              ":failed", "echo Boot failed", "sleep 5", "goto menu", ""]
    return "\n".join(lines)
