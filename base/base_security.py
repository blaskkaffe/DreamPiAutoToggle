# Base - who may talk to the web service, and the optional PIN.
# The web service runs as root (a module can restart services, reboot the machine or run an updater), so
# a request is checked before anything is done:
#   - Host header: refuse names that are not this computer's (DNS rebinding: a web page on the
#     internet that points its own name at the computer's address and then talks to it from the browser);
#   - Origin / Referer: a browser's POST from another site is refused (CSRF);
#   - the custom X-Requested-With header (a page of another site can't add it) for the actions
#     a module marks PROTECTED;
#   - an optional PIN (set with install.sh --pin, never from the page) for those same actions,
#     with a lock-out after repeated wrong tries.
# Python 3 (imports only core).
import binascii
import hashlib
import hmac
import os
import socket
import threading
import time

try:
    from urllib.parse import urlparse
except ImportError:   # Python 2.7
    from urlparse import urlparse

import base_core as core

PIN_MIN, PIN_MAX = 4, 64
ITERATIONS = 50000
FAIL_LIMIT = 5          # wrong PINs in a row ...
LOCKOUT = 60            # ... block every PIN-protected action for this many seconds
PRIVATE_SUFFIXES = (".local", ".lan", ".home", ".home.arpa", ".internal", ".localdomain", ".localhost",
                    ".fritz.box", ".intranet", ".private")

_lock = threading.Lock()
_fails = {"count": 0, "until": 0.0}


# ------------------------------------------------------------------ host / origin

def _host_only(value):
    """'Host: box.local:80' -> 'box.local'; '[::1]:80' -> '::1'."""
    value = (value or "").strip().lower()
    if value.startswith("["):
        return value[1:].split("]")[0]
    return value.split(":")[0].rstrip(".")


def _is_ip(host):
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            socket.inet_pton(family, host.split("%")[0])
            return True
        except (socket.error, ValueError, OSError):
            pass
    return False


def extra_hosts():
    """Names added by hand, one per line, in allowed_hosts (for a router that gives the computer a domain)."""
    text = core.read_file(core.ALLOWED_HOSTS) or ""
    return set(l.strip().lower().rstrip(".") for l in text.splitlines() if l.strip() and not l.startswith("#"))


def host_allowed(header):
    """True when the Host header names this machine: an IP address, a plain or local name, its own
    host name, or something listed in allowed_hosts. No Host header (old HTTP/1.0 clients such
    as old game consoles) is fine: a browser always sends one."""
    host = _host_only(header)
    if not host:
        return not (header or "").strip()
    if _is_ip(host) or host == "localhost" or "." not in host:
        return True
    if host.endswith(PRIVATE_SUFFIXES):
        return True
    try:
        own = socket.gethostname().lower()
    except (socket.error, OSError):
        own = ""
    if own and (host == own or host.startswith(own + ".")):
        return True
    return host in extra_hosts()


def _origin_host(value):
    if not value or value == "null":
        return None
    try:
        return (urlparse(value).netloc or "").lower() or None
    except ValueError:
        return None


def post_allowed(headers, strict):
    """May this POST be acted on? A browser sends Origin (or at least Referer) with a POST: when
    it names another site the request is refused. The page's own requests carry X-Requested-With;
    without it only a same-site form post (JavaScript off) passes, and never for `strict` actions."""
    host = (headers.get("Host") or "").strip().lower()
    origin = headers.get("Origin")
    seen = _origin_host(origin) if origin else _origin_host(headers.get("Referer"))
    if (origin or headers.get("Referer")) and seen != host:
        return False
    if headers.get("X-Requested-With"):
        return True
    return bool(seen) and not strict


# ------------------------------------------------------------------ PIN

def _hash(pin, salt, iterations):
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, iterations)


def pin_required():
    return bool(core.read_file(core.ADMIN_PIN))


def settings_locked():
    """True when Settings is locked with the PIN: the user turned it on and a PIN is set (without a PIN nothing can be locked)."""
    return pin_required() and core.settings_pin_on()


def set_pin(pin):
    """Store a PIN (called by install.sh --pin). Raises ValueError for a bad one."""
    if not (PIN_MIN <= len(pin) <= PIN_MAX):
        raise ValueError("the PIN must be %d to %d characters" % (PIN_MIN, PIN_MAX))
    salt = os.urandom(16)
    line = "pbkdf2$%d$%s$%s\n" % (ITERATIONS, _hex(salt), _hex(_hash(pin, salt, ITERATIONS)))
    fd = os.open(core.ADMIN_PIN + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(line)
    os.rename(core.ADMIN_PIN + ".tmp", core.ADMIN_PIN)


def clear_pin():
    for path in (core.ADMIN_PIN, core.SETTINGS_PIN):         # no PIN, nothing left to lock Settings with
        try:
            os.remove(path)
        except OSError:
            pass


def _hex(raw):
    return binascii.hexlify(raw).decode("ascii")


def _unhex(text):
    return binascii.unhexlify(text.encode("ascii"))


def _pin_matches(pin):
    parts = (core.read_file(core.ADMIN_PIN) or "").split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2":
        return False          # a damaged file locks the protected actions rather than opening them
    try:
        iterations = int(parts[1])
        want = _unhex(parts[3])
        got = _hash(pin, _unhex(parts[2]), iterations)
    except (ValueError, TypeError, binascii.Error):
        return False
    return hmac.compare_digest(got, want)


def check_pin(pin):
    """(ok, message). ok is True without a PIN set. Five wrong tries lock the actions for a minute."""
    if not pin_required():
        return True, ""
    now = time.time()
    with _lock:
        if _fails["until"] > now:
            return False, "Too many wrong PINs, try again in %d seconds" % (int(_fails["until"] - now) + 1)
    if pin and len(pin) <= PIN_MAX and _pin_matches(pin):
        with _lock:
            _fails["count"] = 0
        return True, ""
    with _lock:
        _fails["count"] += 1
        if _fails["count"] >= FAIL_LIMIT:
            _fails.update(count=0, until=time.time() + LOCKOUT)
    return False, "Wrong PIN" if pin else "This action needs the PIN"


def reset_for_tests():
    with _lock:
        _fails.update(count=0, until=0.0)


if __name__ == "__main__":     # used by install.sh: NS_PIN=... python3 base_security.py set | clear
    import sys
    if sys.argv[1:] == ["set"]:
        try:
            set_pin(os.environ.get("NS_PIN", ""))
        except ValueError as e:
            sys.stderr.write("%s\n" % e)
            sys.exit(1)
    elif sys.argv[1:] == ["clear"]:
        clear_pin()
    else:
        sys.exit(2)
