# Check-in add-on - update check and "Update now".
# Asks GitHub whether the installed add-on commit is behind its branch. The page shows the result in Settings >
# System with a manual update guide; "Update now" fast-forwards the checkout that
# install.sh recorded (src_dir) and re-runs its installer, detached so the
# restart of this web service doesn't kill it. Python 3.
import glob
import json
import os
import re
import subprocess
import threading
import time

from urllib.request import urlopen, Request

import base_core as core

# the update module's files
ADDON_COMMIT = os.path.join(core.BASE_DIR, "version_commit")  # full commit hash of the checkout that was installed (install.sh)
ADDON_SRC = os.path.join(core.BASE_DIR, "src_dir")            # that checkout's folder, used by the web update
INSTALL_PORTS = os.path.join(core.BASE_DIR, "install_ports")  # "<http port> <https port>", so an update keeps them
UPDATE_ORIGIN = os.path.join(core.BASE_DIR, "update_origin")  # the checkout's git origin URL when installed; "Update now" refuses another one
VERSION_FILE = os.path.join(core.BASE_DIR, "version")         # written by install.sh: date and commit of the installed checkout
UPDATE_STATUS = core.TMP_PREFIX + ".update"                   # running / ok / failed, written by the update script
UPDATE_LOG = core.TMP_PREFIX + ".update.log"

DEFAULT_REPO = "blaskkaffe/DreamPiAutoToggle"
DEFAULT_BRANCH = "main"
TIMEOUT = 10

_lock = threading.Lock()
_info = {"time": 0, "started": 0, "checking": False, "addon": None, "error": None}


def fetch(url):
    """Body of a URL as text. Replaced by the tests."""
    req = Request(url, headers={"User-Agent": "checkin-board", "Accept": "application/vnd.github+json"})
    return urlopen(req, timeout=TIMEOUT).read().decode("utf-8", "replace")


def _git(args):
    src = core.read_file(ADDON_SRC)
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
    src = (core.read_file(ADDON_SRC) or "").strip() or None
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
# modules/ ...). "Install from USB" copies it to the data folder (so the stick can be pulled out) and runs its install.sh as root, like the GitHub update.
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


def usb_script(folder, http_port, https_port, version):
    """The shell script that installs from a USB folder (built from validated values only: it runs as root): copy the folder to the data folder, then run
    its install.sh from the copy with NS_KEEP_SRC (the recorded checkout stays) and NS_VERSION (what the page shows as the version)."""
    work = os.path.join(core.BASE_DIR, "usb_src")
    ok_path = re.compile(r"^[A-Za-z0-9._/ +@=:-]+$")
    for p in (folder, work):
        if not os.path.isabs(p) or not ok_path.match(p) or ".." in p.split("/"):
            raise ValueError("unsafe update folder")
    if not re.match(r"^[A-Za-z0-9 :.()_-]{1,60}$", version):
        raise ValueError("unsafe version text")
    ports = ["%d" % int(http_port), "--https-port=%d" % int(https_port)]
    return (
        "S=%s; D=%s; L=%s; ST=%s\n"
        "rm -f \"$L\" \"$ST\"; set -C                      # never write through a link someone left in /tmp\n"
        "exec >\"$L\" 2>&1\n"
        "echo running > \"$ST\"\n"
        "echo \"Copying the update from $S\"\n"
        "rm -rf \"$D.new\" && cp -r \"$S\" \"$D.new\" && [ -f \"$D.new/install.sh\" ] && rm -rf \"$D\" && mv \"$D.new\" \"$D\" && cd \"$D\" "
        "&& NS_KEEP_SRC=1 NS_VERSION=%s sh \"$D/install.sh\" %s && echo ok >| \"$ST\" || echo failed >| \"$ST\"\n"
    ) % ("'%s'" % folder, "'%s'" % work, "'%s'" % UPDATE_LOG, "'%s'" % UPDATE_STATUS, "'%s'" % version, " ".join(ports))


def can_update():
    _repo, _branch, src = source()
    return bool(src and os.path.exists(os.path.join(src, "install.sh")) and _git(["rev-parse", "HEAD"]))


def status():
    """What the page shows. Never starts a check: updates are only looked for when the user presses "Check now"."""
    repo, branch, src = source()
    with _lock:
        out = dict(_info)
    out.update({"state": update_state(), "log": _log_tail() if update_state() != "idle" else [],
                "can_update": can_update(), "usb": usb_candidates(), "src": src, "repo": repo, "branch": branch,
                "version_file": (core.read_file(VERSION_FILE) or "unknown").strip()})
    return out


def _ports():
    try:
        http, https = (core.read_file(INSTALL_PORTS) or "80 443").split()[:2]
        return int(http), int(https)
    except ValueError:
        return 80, 443


# Where the update may come from: GitHub over https (or ssh with the checkout owner's own key).
ORIGIN_RE = re.compile(r"^(https://github\.com/|git@github\.com:|ssh://git@github\.com/)[\w.-]+/[\w.-]+?(\.git)?/?$")


def origin_url():
    return _git(["config", "--get", "remote.origin.url"])


def origin_problem():
    """Why the checkout's git origin can't be trusted for an update, or None. The update runs the
    checkout's install.sh as root, so it must come from GitHub and be the origin that was there
    when the add-on was installed (anything that can edit the checkout's .git/config could
    otherwise point it elsewhere). An install from before this check has no recorded origin; it
    is accepted when it is a GitHub address and gets recorded by the update's own install."""
    url = origin_url()
    if not url or not ORIGIN_RE.match(url):
        return "the checkout's git origin isn't a GitHub address"
    recorded = (core.read_file(UPDATE_ORIGIN) or "").strip()
    if recorded and recorded != url:
        return "the checkout's git origin changed since the add-on was installed (run install.sh by hand to accept it)"
    return None


def update_script(src, branch, http_port, https_port, url=None):
    """The shell script that updates and re-installs. Built from validated
    values only (it runs as root). With `url` (already checked by origin_problem) the fetch uses that
    address and only https/ssh transports; otherwise the checkout's own 'origin'."""
    if url is not None and not ORIGIN_RE.match(url):
        raise ValueError("unsafe update address")
    if (not re.match(r"^[A-Za-z0-9._/][A-Za-z0-9._/-]*$", branch) or ".." in branch or branch.endswith("/")
            or not os.path.isabs(src) or not re.match(r"^[A-Za-z0-9._/ +@=-]+$", src)):
        raise ValueError("unsafe update settings")
    ports = ["%d" % int(http_port), "--https-port=%d" % int(https_port)]
    return (
        "S=%s; B=%s; L=%s; ST=%s; U=%s\n"
        "rm -f \"$L\" \"$ST\"; set -C                      # never write through a link someone left in /tmp\n"
        "exec >\"$L\" 2>&1\n"
        "echo running > \"$ST\"\n"
        "echo \"Updating $S from origin/$B\"\n"
        "OWNER=$(stat -c %%U \"$S\")\n"
        "P=; [ \"$U\" != origin ] && P='env GIT_ALLOW_PROTOCOL=https:ssh'\n"
        "if [ \"$(id -u)\" = 0 ] && [ \"$OWNER\" != root ]; then G=\"runuser -u $OWNER -- $P git\"; else G=\"$P git\"; fi\n"
        "cd \"$S\" && $G fetch \"$U\" \"$B\" && $G merge --ff-only FETCH_HEAD && sh \"$S/install.sh\" %s && echo ok >| \"$ST\" || echo failed >| \"$ST\"\n"
    ) % ("'%s'" % src, "'%s'" % branch, "'%s'" % UPDATE_LOG, "'%s'" % UPDATE_STATUS,
                                                          "'%s'" % (url or "origin"), " ".join(ports))


def _write_status(text):
    """Write the status file without following a link that someone left at its (predictable) /tmp path."""
    try:
        if os.path.islink(UPDATE_STATUS):
            os.remove(UPDATE_STATUS)
    except OSError:
        pass
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(UPDATE_STATUS, flags, 0o644)
    with os.fdopen(fd, "w") as f:
        f.write(text)


def _spawn(cmd):
    """Run cmd detached from this service (it is restarted by the installer).
    Replaced by the tests."""
    if os.path.exists("/run/systemd/system"):   # outside this service's cgroup: survives its restart
        subprocess.Popen(["systemd-run", "--unit=checkin-board-update-%d" % int(time.time()), "--no-block",
                          "--collect"] + cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        subprocess.Popen(["setsid"] + cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


_start_lock = threading.Lock()


def start_usb_update():
    """Begin an update from the first USB stick that has an update folder; returns (started, message). One update at a time."""
    with _start_lock:
        if update_state() == "running":
            return False, "An update is already running"
        found = usb_candidates()
        if not found:
            return False, "No USB stick with an update folder was found"
        pick = found[0]
        http, https = _ports()
        label = "USB update %s" % time.strftime("%Y-%m-%d %H:%M", time.localtime(pick["time"]))
        try:
            script = usb_script(pick["path"], http, https, label)
        except ValueError as e:
            return False, "Update refused: %s" % e
        try:
            _write_status("running")
            _spawn(["sh", "-c", script])
        except OSError as e:
            try:
                _write_status("failed")
            except OSError:
                pass
            return False, "Could not start the update (%s)" % e
    core.log("web page: update from USB started (%s)" % pick["path"])
    return True, "Update started"


def start_update():
    """Begin the update; returns (started, message). One at a time."""
    with _start_lock:
        if update_state() == "running":
            return False, "An update is already running"
        repo, branch, src = source()
        if not can_update():
            return False, "This install can't update itself (no git checkout recorded): use the update guide"
        problem = origin_problem()
        if problem:
            core.log("web page: update refused (%s)" % problem)
            return False, "Update refused: %s" % problem
        http, https = _ports()
        try:
            script = update_script(src, branch, http, https, origin_url())
        except ValueError as e:
            return False, "Update refused: %s" % e
        try:
            _write_status("running")
            _spawn(["sh", "-c", script])
        except OSError as e:
            try:
                _write_status("failed")
            except OSError:
                pass
            return False, "Could not start the update (%s)" % e
    core.log("web page: update started (%s, branch %s)" % (src, branch))
    return True, "Update started"
