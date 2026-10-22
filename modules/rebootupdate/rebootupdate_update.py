# Check-in add-on - update check and "Update now".
# Asks GitHub whether the installed add-on commit is behind its branch. The page shows the result in Settings >
# System with a manual update guide. The web service is an ordinary user, so "Update now" does not run anything itself: it asks systemd to start
# checkin-board-update@git.service (or @usb), a unit that runs update-run.sh next to this file as root. That script reads everything it needs from
# the files only root can write (src_dir, update_origin, install_ports ...), fast-forwards the checkout that install.sh recorded and re-runs its
# installer, outside this service's cgroup so that its restart doesn't kill it. Python 3.
import glob
import json
import os
import re
import subprocess
import threading
import time

from urllib.request import urlopen, Request

import base_core as core

# the update module's files: the first five are written by install.sh (root) and only read here, so the web service can not point the root updater
# somewhere else; the last two are written by update-run.sh (root) into a folder of its own, readable by everyone
ADDON_COMMIT = os.path.join(core.INSTALL_DIR, "version_commit")  # full commit hash of the checkout that was installed (install.sh)
ADDON_SRC = os.path.join(core.INSTALL_DIR, "src_dir")            # that checkout's folder, used by the web update
INSTALL_PORTS = os.path.join(core.INSTALL_DIR, "install_ports")  # "<http port> <https port>", so an update keeps them
UPDATE_ORIGIN = os.path.join(core.INSTALL_DIR, "update_origin")  # the checkout's git origin URL when installed; "Update now" refuses another one
UPDATE_BRANCH = os.path.join(core.INSTALL_DIR, "update_branch")  # the checkout's branch when installed
VERSION_FILE = os.path.join(core.INSTALL_DIR, "version")         # written by install.sh: date and commit of the installed checkout
UPDATE_DIR = "/run/" + core.PROJECT.get("service", "app") + "-update"    # the updater's own run folder (RuntimeDirectory of its unit)
UPDATE_STATUS = os.path.join(UPDATE_DIR, "state.update")         # running / ok / failed, written by the update script
UPDATE_LOG = os.path.join(UPDATE_DIR, "state.update.log")
UPDATE_UNIT = core.PROJECT.get("service", "app") + "-update@%s.service"   # started with "git" or "usb"
UPDATER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "update-run.sh")

DEFAULT_REPO = "blaskkaffe/CheckinChicken"
DEFAULT_BRANCH = "main"
TIMEOUT = 10

_lock = threading.Lock()
_info = {"time": 0, "started": 0, "checking": False, "addon": None, "error": None}


def fetch(url):
    """Body of a URL as text. Replaced by the tests."""
    req = Request(url, headers={"User-Agent": "checkin-board", "Accept": "application/vnd.github+json"})
    return urlopen(req, timeout=TIMEOUT).read().decode("utf-8", "replace")


def _recorded(path):
    return (core.read_file(path) or "").strip()


def source():
    """(repo "owner/name", branch, checkout folder or None) of this install, as install.sh recorded them (the service does not read the checkout)."""
    src = _recorded(ADDON_SRC) or None
    repo, branch = DEFAULT_REPO, DEFAULT_BRANCH
    m = re.search(r"github\.com[:/]+([\w.-]+/[\w.-]+?)(?:\.git)?/?$", _recorded(UPDATE_ORIGIN))
    if m:
        repo = m.group(1)
    b = _recorded(UPDATE_BRANCH)
    if b and b != "HEAD" and re.match(r"^[A-Za-z0-9._/-]+$", b):
        branch = b
    return repo, branch, src


def local_commit():
    c = (core.read_file(ADDON_COMMIT) or "").strip()
    return c if re.match(r"^[0-9a-f]{40}$", c) else None


def check_addon():
    repo, branch, _src = source()
    commit = local_commit()
    out = {"current": (core.read_file(VERSION_FILE) or "unknown").strip(), "repo": repo, "branch": branch,
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


def _begin():
    """Mark a check as running; False when one already is. Done before the thread starts so that the page's very next
    question already says "checking" (a refresh that came in between used to show the old result: the button seemed dead)."""
    with _lock:
        if _info["checking"]:
            return False
        _info["checking"] = True
        _info["started"] = time.time()
        return True


def check():
    """Run both checks now (network). Fills the cache the page reads."""
    if _begin():
        _run()


def _run():
    result = {"time": int(time.time()), "addon": None, "error": None}
    try:
        try:
            result["addon"] = check_addon()
        except Exception as e:
            result["error"] = "Couldn't reach GitHub (%s)" % (getattr(e, "reason", None) or e)
    finally:
        with _lock:
            _info.update(result)
            _info["checking"] = False


def check_in_background():
    if _begin():
        t = threading.Thread(target=_run)
        t.daemon = True
        t.start()


def update_status():
    """running / ok / failed, or idle. A finished result is only reported for 10 minutes, so an old update isn't announced for ever."""
    text = (core.read_file(UPDATE_STATUS) or "").strip()
    if text not in ("running", "ok", "failed"):
        return "idle"
    try:
        if text != "running" and time.time() - os.path.getmtime(UPDATE_STATUS) > 600:
            return "idle"
    except OSError:
        return "idle"
    return text


def update_state():
    """running / ok / failed, or idle (a finished result is only reported for 10 minutes: update_status()). A new check
    replaces a finished result: after an update the page showed "The add-on was updated." for ten minutes whatever the user
    pressed, so checking again looked dead."""
    state = update_status()
    if state in ("ok", "failed"):
        try:
            if _info.get("started", 0) > os.path.getmtime(UPDATE_STATUS):
                return "idle"
        except OSError:
            return "idle"
    if state != "running" and time.time() - _pending[0] < 30:       # the updater was asked a moment ago and has not written its first line yet
        try:
            answered = os.path.getmtime(UPDATE_STATUS) >= _pending[0]
        except OSError:
            answered = False
        if not answered:
            return "running"
    return state


_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-_]")


def _clean_line(line):
    """One log line for the page: no colour codes, no progress-bar rewrites (text before a lone
    carriage return), no control characters, at most 300 characters."""
    line = _ANSI.sub("", line.rstrip("\r\n"))
    parts = [p for p in line.split("\r") if p.strip()]
    line = parts[-1] if parts else ""
    line = "".join(ch if ch >= " " or ch == "\t" else " " for ch in line).rstrip()
    return line[:300]


def _log_tail(n=14):
    try:
        with open(UPDATE_LOG, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 16384))
            text = f.read().decode("utf-8", "replace")
    except (IOError, OSError):
        return []
    lines = [_clean_line(l) for l in text.split("\n")]
    return [l for l in lines if l.strip()][-n:]


# ---- an update from a USB stick: a folder called "update" on a removable drive holds the add-on's files (a copy of the repository: install.sh, base/,
# modules/ ...). "Install from USB" has the root updater copy it away (so the stick can be pulled out) and run its install.sh, like the GitHub update.
USB_NAME = "update"
USB_ROOTS = ["/media/*", "/media/*/*", "/run/media/*/*", "/mnt/*", "/mnt/*/*"]      # where a stick is mounted (replaced by the tests)


def usb_candidates():
    """[{"path", "drive", "time"}]: the folders called "update" on mounted drives that look like the add-on (install.sh, base/base_web.py, modules/), newest
    first. A link is not followed."""
    out, seen = [], set()
    for pattern in USB_ROOTS:
        for root in sorted(glob.glob(pattern)):
            path = os.path.join(root, USB_NAME)
            if path in seen or os.path.islink(path) or not os.path.isdir(path):
                continue
            seen.add(path)
            installer = os.path.join(path, "install.sh")
            if not (os.path.isfile(installer) and not os.path.islink(installer) and os.path.isfile(os.path.join(path, "base", "base_web.py"))
                    and os.path.isdir(os.path.join(path, "modules"))):
                continue
            try:
                when = int(os.path.getmtime(installer))
            except OSError:
                when = 0
            out.append({"path": path, "drive": os.path.basename(root), "time": when})
    return sorted(out, key=lambda c: -c["time"])


def can_update():
    """The install recorded a checkout and an origin for it (origin_problem() says whether it is a GitHub address; the updater checks the checkout itself, as root)."""
    _repo, _branch, src = source()
    return bool(src and origin_url())


def status():
    """What the page shows. Never starts a check: updates are only looked for when the user presses "Check now"."""
    repo, branch, src = source()
    with _lock:
        out = dict(_info)
    out.update({"state": update_state(), "log": _log_tail() if update_state() != "idle" else [],
                "can_update": can_update(), "usb": usb_candidates(), "src": src, "repo": repo, "branch": branch,
                "version_file": (core.read_file(VERSION_FILE) or "unknown").strip()})
    return out


# Where the update may come from: GitHub over https (or ssh with the checkout owner's own key).
ORIGIN_RE = re.compile(r"^(https://github\.com/|git@github\.com:|ssh://git@github\.com/)[\w.-]+/[\w.-]+?(\.git)?/?$")


def origin_url():
    return _recorded(UPDATE_ORIGIN) or None


def origin_problem():
    """Why the recorded git origin can't be trusted for an update, or None. The update runs the checkout's install.sh as root, so it must come from
    GitHub. (update-run.sh also checks, as root, that the checkout's own origin is still the recorded one: anything that can edit the checkout's
    .git/config could otherwise point it elsewhere.)"""
    url = origin_url()
    if not url or not ORIGIN_RE.match(url):
        return "the checkout's git origin isn't a GitHub address"
    return None


_pending = [0.0]      # when "Update now" last asked systemd to start the updater: it says "running" itself a moment later


def reset_for_tests():
    _pending[0] = 0.0


def _spawn(mode):
    """Ask systemd to start the root-owned updater (mode "git" or "usb"). Returns False when that is refused. Replaced by the tests."""
    if os.path.exists("/run/systemd/system"):   # a unit of its own: outside this service's cgroup, so it survives the installer's restart of this service
        r = subprocess.run(["systemctl", "start", "--no-block", UPDATE_UNIT % mode], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        return r.returncode == 0
    if os.geteuid() != 0:                       # no systemd and not root (a test machine): nothing is allowed to run the updater
        return False
    subprocess.Popen(["setsid", "sh", UPDATER, mode], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return True


_start_lock = threading.Lock()


def _start(mode, what):
    _pending[0] = time.time()
    try:
        ok = _spawn(mode)
    except (OSError, subprocess.SubprocessError) as e:
        ok, why = False, str(e)
    else:
        why = "the computer did not allow this service to start it: is polkit installed? see docs/web.md"
    if ok is False:
        _pending[0] = 0.0
        core.log("web page: update could not be started (%s)" % why)
        return False, "Could not start the update (%s)" % why
    core.log("web page: %s started" % what)
    return True, "Update started"


def start_usb_update():
    """Begin an update from the first USB stick that has an update folder; returns (started, message). One update at a time. The root updater
    looks for the stick itself: this only checks that there is one to tell the user early."""
    with _start_lock:
        if update_state() == "running":
            return False, "An update is already running"
        if not usb_candidates():
            return False, "No USB stick with an update folder was found"
        return _start("usb", "update from USB")


def start_update():
    """Begin the update; returns (started, message). One at a time."""
    with _start_lock:
        if update_state() == "running":
            return False, "An update is already running"
        if not can_update():
            return False, "This install can't update itself (no git checkout recorded): use the update guide"
        problem = origin_problem()
        if problem:
            core.log("web page: update refused (%s)" % problem)
            return False, "Update refused: %s" % problem
        return _start("git", "update (%s)" % (source()[2],))
