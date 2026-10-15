# DreamPi Netswitch add-on - Reboot and Update module, web side:
#   GET  /update          the cached update check (netswitch_update.status())
#   POST /update/check    run a check now
#   POST /update/start    fetch and install the new version (needs the PIN when one is set)
#   POST /reboot          reboot the Pi (needs the PIN when one is set)
#   POST /autoupdates/allow    back up and remove /boot/noautoupdates.txt: DreamPi may update its scripts and write netlink_config.ini again
#   POST /autoupdates/restore  put the backed-up file back (needs the PIN when one is set)
# GET /update also carries the texts the page's widgets show (view() below), so the page needs no code of its own to draw them.
# The update logic is in netswitch_update.py next to this file. Without the module the page has no update or
# reboot controls and these paths answer 404.
import json
import os
import re
import shutil
import subprocess
import time

import base_core as core
import netswitch_update as updater

REBOOT_MARK = core.TMP_PREFIX + ".reboot"        # the unix time a reboot was asked for (the LEDs show "about to reboot")
STATUS = core.TMP_PREFIX + ".active"             # DreamPi's hook: "active pid=N" while it runs (written by the network switcher's hook)
STATE = core.TMP_PREFIX + ".state"               # "<starting|ready|call dcnow|call dcnet> <unix time>" (the same hook)

NOAUTO = "/boot/noautoupdates.txt"                              # DreamPi's own switch: while it exists DreamPi neither updates its scripts nor writes netlink_config.ini
NOAUTO_BACKUP = os.path.join(core.BASE_DIR, "noautoupdates.backup")   # the copy taken when it was removed here (exists = a copy to restore)

PROTECTED = ("/reboot", "/update/start", "/autoupdates/allow", "/autoupdates/restore")      # run as root: the PIN is asked for when one is set


def _spawn_reboot():
    """Reboot the Pi a couple of seconds from now, so the HTTP answer gets out first. Detached from this service
    (which the reboot stops). Replaced by the tests."""
    subprocess.Popen(["sh", "-c", "sleep 2; systemctl reboot || reboot"],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def in_call():
    """DreamPi is in a call now (the state file says so and DreamPi is still running)."""
    m = re.search(r"pid=(\d+)", core.read_file(STATUS) or "")
    if m and not os.path.exists("/proc/" + m.group(1)):          # DreamPi is not running any more
        return False
    return (core.read_file(STATE) or "").startswith("call ")


def mark_reboot():
    try:
        with open(REBOOT_MARK, "w") as f:
            f.write("%f" % time.time())
    except (IOError, OSError):
        pass


def start_reboot():
    """Reboot the whole Raspberry Pi (DreamPi starts again with it). Returns (started, message)."""
    called = in_call()
    try:
        _spawn_reboot()
    except OSError as e:
        return False, "Could not reboot (%s)" % e
    mark_reboot()                                    # the LEDs say so while the Pi goes down
    core.debug_log("web page: reboot requested%s" % (" (a call was in progress)" if called else ""))
    return True, "Rebooting"


def auto_state():
    """DreamPi's /boot/noautoupdates.txt: off = it exists (DreamPi does not update itself and does not write netlink_config.ini), backup = this module has
    a copy of it that can be put back (only offered while the file is missing)."""
    here = os.path.exists(NOAUTO)
    return {"off": here, "backup": os.path.exists(NOAUTO_BACKUP) and not here}


def _root(cmd, done):
    """Run cmd outside this service (it may not write to /boot: the unit is sandboxed; a transient unit is not) and wait a few seconds for done()."""
    updater._spawn(cmd)
    end = time.time() + 5
    while time.time() < end:
        if done():
            return True
        time.sleep(0.2)
    return done()


def auto_allow():
    """Back /boot/noautoupdates.txt up and remove it, so DreamPi updates its scripts and writes a fresh netlink_config.ini the next time it
    starts (restart DreamPi or reboot). Returns (done, message)."""
    if not os.path.exists(NOAUTO):
        return False, "DreamPi's self-updates are already on (/boot/noautoupdates.txt is not there)."
    try:
        shutil.copyfile(NOAUTO, NOAUTO_BACKUP)             # the copy first: nothing is removed that could not be restored
    except (IOError, OSError) as e:
        return False, "Could not back the file up, so nothing was removed (%s)." % e
    if not _root(["rm", "-f", NOAUTO], lambda: not os.path.exists(NOAUTO)):
        return False, "Could not remove /boot/noautoupdates.txt (the backup is kept)."
    core.debug_log("web page: /boot/noautoupdates.txt backed up and removed")
    return True, "Done. DreamPi updates its scripts and writes netlink_config.ini the next time it starts: restart DreamPi or reboot. The old file is backed up and can be restored here."


def auto_restore():
    """Put the backed-up /boot/noautoupdates.txt back: DreamPi stops updating itself and leaves netlink_config.ini alone again. Returns (done, message)."""
    if os.path.exists(NOAUTO):
        return False, "/boot/noautoupdates.txt is already there."
    if not os.path.exists(NOAUTO_BACKUP):
        return False, "There is no backup of it to restore."
    if not _root(["cp", NOAUTO_BACKUP, NOAUTO], lambda: os.path.exists(NOAUTO)):
        return False, "Could not write /boot/noautoupdates.txt (the backup is kept)."
    core.debug_log("web page: /boot/noautoupdates.txt restored from its backup")
    return True, "Restored: DreamPi does not update itself and leaves netlink_config.ini alone."


def view(r):
    """The status of the update check as the widgets in layout.json show it: text, dreampi_text, show_update, do_sub,
    check_disabled, busy (the page asks again soon while it is true)."""
    a, d, state = r.get("addon"), r.get("dreampi"), r.get("state")
    running = state == "running"
    if running:
        msg = "Updating... the page is unavailable for a few seconds while the services restart."
    elif state == "ok":
        msg = "The add-on was updated."
    elif state == "failed":
        msg = "The update failed. Details below."
    elif r.get("checking"):
        msg = "Checking..."
    elif not r.get("time"):
        msg = "Not checked yet"
    elif r.get("error"):
        msg = r["error"]
    elif a and a.get("available"):
        behind = a.get("behind")
        msg = "A newer add-on version is available: %s%s%s. You have %s." % (
            a.get("latest"), " (%s)" % a["latest_date"][:10] if a.get("latest_date") else "",
            ", %d new change%s" % (behind, "s" if behind > 1 else "") if behind else "", a.get("current"))
    elif a and a.get("available") is False:
        msg = "Up to date (%s)." % a.get("current")
    else:
        msg = (a and a.get("note")) or "Couldn't tell if the add-on is current."
    if a and a.get("note") and a.get("available") is not None and not running and state == "idle":
        msg += " " + a["note"]
    dp = ""
    if d and d.get("newer") and state == "idle":
        dp = "DreamPi has newer scripts: " + ", ".join("%s %s \u2192 %s" % (f["name"], f["current"], f["latest"]) for f in d["files"] if f.get("newer")) + (
            ". It updates itself when the Pi restarts with internet." if d.get("auto_updates") else ". Automatic updates are off (/boot/noautoupdates.txt exists).")
    return {"text": msg, "dreampi_text": dp,
            "show_update": bool(a and a.get("available") and r.get("can_update") and state == "idle"),
            "do_sub": "Fetches the new version from GitHub and installs it (%s branch). Settings are kept." % (r.get("branch") or "main"),
            "check_disabled": bool(r.get("checking") or running), "busy": bool(r.get("checking") or running), "auto": auto_state()}


def _get_update(h):
    out = updater.status()
    out.update(view(out))
    h.send(json.dumps(out), "application/json")


def _post_auto(h):
    """POST /autoupdates/allow and /autoupdates/restore: {"started": bool, "message": text} like the reboot and the update."""
    done, message = auto_allow() if h.path.split("?")[0].endswith("/allow") else auto_restore()
    h.send(json.dumps({"started": done, "message": message, "auto": auto_state()}), "application/json")
    return True


def _post_reboot(h):
    started, message = start_reboot()
    h.send(json.dumps({"started": started, "message": message}), "application/json")
    return True


def _post_update(h):
    if not h.headers.get("X-Requested-With"):   # the check is harmless but still only for the page
        h._refuse(403, "Refused: this request did not come from the page")
        return True
    started, message = True, ""
    if h.path.split("?")[0] == "/update/check":
        updater.check_in_background()
    else:
        started, message = updater.start_update()
    status = updater.status()
    status.update(view(status))
    h.send(json.dumps({"message": message, "started": started, "status": status}), "application/json")
    return True


def api(d, warnings):
    """The text the Reboot button asks to confirm (it says so when a call is in progress)."""
    called = in_call()
    d["reboot"] = {"confirm": ("A call is in progress and will be cut. " if called else "") + "Reboot the Raspberry Pi now? It is back in about a minute."}


GET = {"/update": _get_update}
POST = {"/autoupdates/allow": _post_auto, "/autoupdates/restore": _post_auto, "/reboot": _post_reboot, "/update/check": _post_update, "/update/start": _post_update}
