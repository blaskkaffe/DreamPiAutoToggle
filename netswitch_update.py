# DreamPi Netswitch add-on - update check and "Update now".
# Asks GitHub whether the installed add-on commit is behind its branch, and
# whether DreamPi's own scripts (dreampi.py, netlink.py, dcnow.py) have newer
# version lines than the ones on the Pi. The page shows the result in Settings >
# About with a manual update guide; "Update now" fast-forwards the checkout that
# install.sh recorded (src_dir) and re-runs its installer, detached so the
# restart of this web service doesn't kill it. Works on Python 3 and 2.7.
import json
import os
import re
import subprocess
import threading
import time

try:
    from urllib.request import urlopen, Request
except ImportError:   # Python 2.7
    from urllib2 import urlopen, Request

import netswitch_core as core
import netswitch_probes as probes

DEFAULT_REPO = "blaskkaffe/DreamPiAutoToggle"
DEFAULT_BRANCH = "main"
DREAMPI_RAW = "https://raw.githubusercontent.com/Kazade/dreampi/master/"   # what DreamPi's own updater follows
DREAMPI_FILES = ("dreampi.py", "netlink.py", "dcnow.py")
CHECK_EVERY = 6 * 3600     # re-check at most this often; the page's button forces one
TIMEOUT = 10

_lock = threading.Lock()
_info = {"time": 0, "checking": False, "addon": None, "dreampi": None, "error": None}


def fetch(url):
    """Body of a URL as text. Replaced by the tests."""
    req = Request(url, headers={"User-Agent": "dreampi-netswitch", "Accept": "application/vnd.github+json"})
    return urlopen(req, timeout=TIMEOUT).read().decode("utf-8", "replace")


def _git(args):
    src = core.read_file(core.ADDON_SRC)
    if not src or not os.path.isdir(src.strip()):
        return None
    try:
        out = subprocess.check_output(["git", "-c", "safe.directory=" + src.strip(), "-C", src.strip()] + args,
                                      stderr=subprocess.PIPE)
        return out.decode("utf-8", "replace").strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def source():
    """(repo "owner/name", branch, checkout folder or None) of this install."""
    src = (core.read_file(core.ADDON_SRC) or "").strip() or None
    if src and not os.path.isdir(src):
        src = None
    repo, branch = DEFAULT_REPO, DEFAULT_BRANCH
    url = _git(["config", "--get", "remote.origin.url"]) if src else None
    m = re.search(r"github\.com[:/]+([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url or "")
    if m:
        repo = m.group(1)
    b = _git(["rev-parse", "--abbrev-ref", "HEAD"]) if src else None
    if b and b != "HEAD" and re.match(r"^[A-Za-z0-9._/-]+$", b):
        branch = b
    return repo, branch, src


def local_commit():
    c = (core.read_file(core.ADDON_COMMIT) or "").strip()
    return c if re.match(r"^[0-9a-f]{40}$", c) else None


def check_addon():
    repo, branch, _src = source()
    commit = local_commit()
    out = {"current": (core.read_file(probes.ADDON_VERSION) or "unknown").strip(), "repo": repo, "branch": branch,
           "available": None, "latest": None, "latest_date": None, "behind": None, "note": None}
    head = json.loads(fetch("https://api.github.com/repos/%s/commits/%s" % (repo, branch)))
    out["latest"] = head["sha"][:7]
    out["latest_date"] = ((head.get("commit") or {}).get("committer") or {}).get("date")
    if not commit:
        out["note"] = "This install doesn't know which commit it came from, so it can't tell if it is current."
    elif commit == head["sha"]:
        out["available"] = False
    else:
        try:
            cmp_ = json.loads(fetch("https://api.github.com/repos/%s/compare/%s...%s" % (repo, commit, head["sha"])))
            status = cmp_.get("status")
            out["available"] = status in ("ahead", "diverged")
            out["behind"] = cmp_.get("ahead_by")
            if status == "behind":
                out["note"] = "This install is ahead of %s on GitHub." % branch
            elif status == "diverged":
                out["note"] = "This install has changes that are not on GitHub as well as missing updates."
        except Exception:
            out["note"] = "This install's commit isn't on GitHub (local changes), so it can't be compared."
    return out


def _raw_version(text):
    m = re.search(r"_version=(\d{12})", text or "")
    return m.group(1) if m else None


def _pretty(v):
    return "%s-%s-%s %s:%s" % (v[:4], v[4:6], v[6:8], v[8:10], v[10:12]) if v and len(v) == 12 else (v or "not found")


def check_dreampi():
    files, newer = [], False
    for name in DREAMPI_FILES:
        local = None
        try:
            with open(os.path.join(probes.DREAMPI_DIR, name), "rb") as f:
                local = _raw_version(f.read(4096).decode("utf-8", "replace"))
        except (IOError, OSError):
            pass
        try:
            latest = _raw_version(fetch(DREAMPI_RAW + name)[:4096])
        except Exception:
            latest = None
        is_newer = bool(local and latest and latest > local)
        newer = newer or is_newer
        files.append({"name": name, "current": _pretty(local), "latest": _pretty(latest) if latest else None, "newer": is_newer})
    return {"files": files, "newer": newer, "auto_updates": not os.path.exists("/boot/noautoupdates.txt")}


def check():
    """Run both checks now (network). Fills the cache the page reads."""
    with _lock:
        if _info["checking"]:
            return
        _info["checking"] = True
    result = {"time": int(time.time()), "addon": None, "dreampi": None, "error": None}
    try:
        try:
            result["addon"] = check_addon()
        except Exception as e:
            result["error"] = "Couldn't reach GitHub (%s)" % (getattr(e, "reason", None) or e)
        try:
            result["dreampi"] = check_dreampi()
        except Exception:
            pass
    finally:
        with _lock:
            _info.update(result)
            _info["checking"] = False


def check_in_background():
    t = threading.Thread(target=check)
    t.daemon = True
    t.start()


def update_state():
    """running / ok / failed, or idle. A finished result is only reported for
    10 minutes, so the page doesn't announce an old update every time."""
    text = (core.read_file(core.UPDATE_STATUS) or "").strip()
    if text not in ("running", "ok", "failed"):
        return "idle"
    try:
        if text != "running" and time.time() - os.path.getmtime(core.UPDATE_STATUS) > 600:
            return "idle"
    except OSError:
        return "idle"
    return text


def _log_tail(n=12):
    try:
        with open(core.UPDATE_LOG) as f:
            return [l.rstrip() for l in f.readlines()[-n:]]
    except (IOError, OSError):
        return []


def can_update():
    _repo, _branch, src = source()
    return bool(src and os.path.exists(os.path.join(src, "install.sh")) and _git(["rev-parse", "HEAD"]))


def status():
    """What the page shows. Starts a background check when there is none yet
    or the last one is old."""
    with _lock:
        stale = time.time() - _info["time"] > CHECK_EVERY and not _info["checking"]
    if stale:
        check_in_background()
    repo, branch, src = source()
    with _lock:
        out = dict(_info)
    out.update({"state": update_state(), "log": _log_tail() if update_state() != "idle" else [],
                "can_update": can_update(), "src": src, "repo": repo, "branch": branch,
                "version_file": (core.read_file(probes.ADDON_VERSION) or "unknown").strip()})
    return out


def _ports():
    try:
        http, https = (core.read_file(core.INSTALL_PORTS) or "80 443").split()[:2]
        return int(http), int(https)
    except ValueError:
        return 80, 443


def update_script(src, branch, http_port, https_port):
    """The shell script that updates and re-installs. Built from validated
    values only (it runs as root)."""
    if not re.match(r"^[A-Za-z0-9._/-]+$", branch) or not os.path.isabs(src) or "'" in src or "\n" in src:
        raise ValueError("unsafe update settings")
    ports = ["%d" % int(http_port), "--https-port=%d" % int(https_port)]
    return (
        "S=%s; B=%s; L=%s; ST=%s\n"
        "exec >\"$L\" 2>&1\n"
        "echo running > \"$ST\"\n"
        "echo \"Updating $S from origin/$B\"\n"
        "OWNER=$(stat -c %%U \"$S\")\n"
        "if [ \"$(id -u)\" = 0 ] && [ \"$OWNER\" != root ]; then G=\"runuser -u $OWNER -- git\"; else G=git; fi\n"
        "cd \"$S\" && $G fetch origin \"$B\" && $G merge --ff-only FETCH_HEAD && sh \"$S/install.sh\" %s && echo ok > \"$ST\" || echo failed > \"$ST\"\n"
    ) % ("'%s'" % src, "'%s'" % branch, "'%s'" % core.UPDATE_LOG, "'%s'" % core.UPDATE_STATUS, " ".join(ports))


def _spawn(cmd):
    """Run cmd detached from this service (it is restarted by the installer).
    Replaced by the tests."""
    if os.path.exists("/run/systemd/system"):   # outside this service's cgroup: survives its restart
        subprocess.Popen(["systemd-run", "--unit=dreampi-netswitch-update-%d" % int(time.time()), "--no-block",
                          "--collect"] + cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        subprocess.Popen(["setsid"] + cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def start_update():
    """Begin the update; returns (started, message)."""
    if update_state() == "running":
        return False, "An update is already running"
    repo, branch, src = source()
    if not can_update():
        return False, "This install can't update itself (no git checkout recorded): use the update guide"
    http, https = _ports()
    script = update_script(src, branch, http, https)
    with open(core.UPDATE_STATUS, "w") as f:
        f.write("running")
    try:
        _spawn(["sh", "-c", script])
    except OSError as e:
        with open(core.UPDATE_STATUS, "w") as f:
            f.write("failed")
        return False, "Could not start the update (%s)" % e
    core.debug_log("web page: update started (%s, branch %s)" % (src, branch))
    return True, "Update started"
