# Check-in add-on - Reboot and Update module, web side:
#   GET  /update          the cached update check (rebootupdate_update.status())
#   POST /update/check    run a check now
#   POST /update/start    fetch and install the new version (needs the PIN when one is set)
#   POST /update/usb      install the update folder of a USB stick (needs the PIN when one is set)
#   POST /reboot          reboot the Pi (needs the PIN when one is set)
# GET /update also carries the texts the page's widgets show (view() below), so the page needs no code of its own to draw them.
# The update logic is in rebootupdate_update.py next to this file. Without the module the page has no update or
# reboot controls and these paths answer 404.
import json
import subprocess
import time

import base_core as core
import rebootupdate_update as updater

PROTECTED = ("/reboot", "/update/start", "/update/usb")      # run as root: the PIN is asked for when one is set


def _spawn_reboot():
    """Reboot the Pi a couple of seconds from now, so the HTTP answer gets out first. Detached from this service
    (which the reboot stops). Replaced by the tests."""
    subprocess.Popen(["sh", "-c", "sleep 2; systemctl reboot || reboot"],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def start_reboot():
    """Reboot the whole Raspberry Pi (the add-on starts again with it). Returns (started, message)."""
    try:
        _spawn_reboot()
    except OSError as e:
        return False, "Could not reboot (%s)" % e
    core.log("web page: reboot requested")
    return True, "Rebooting"


def view(r):
    """The status of the update check as the widgets in layout.json show it: text, show_update, do_sub,
    check_disabled, busy (the page asks again soon while it is true)."""
    a, state = r.get("addon"), r.get("state")
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
    usb = r.get("usb") or []
    usb_text = ""
    if usb:
        usb_text = "The update folder on the USB stick %s (%s, files from %s). Installs it and keeps the settings." % (
            usb[0].get("drive") or "", usb[0].get("path"), time.strftime("%Y-%m-%d %H:%M", time.localtime(usb[0].get("time") or 0)))
    return {"text": msg, "usb_text": usb_text, "show_usb": bool(usb and state == "idle"),
            "show_update": bool(a and a.get("available") and r.get("can_update") and state == "idle"),
            "do_sub": "Fetches the new version from GitHub and installs it (%s branch). Settings are kept." % (r.get("branch") or "main"),
            "check_disabled": bool(r.get("checking") or running), "busy": bool(r.get("checking") or running)}


def _get_update(h):
    out = updater.status()
    out.update(view(out))
    h.send(json.dumps(out), "application/json")


def _post_reboot(h):
    started, message = start_reboot()
    h.send(json.dumps({"started": started, "message": message}), "application/json")
    return True


def _post_update(h):
    if not h.headers.get("X-Requested-With"):   # the check is harmless but still only for the page
        h._refuse(403, "Refused: this request did not come from the page")
        return True
    started, message = True, ""
    path = h.path.split("?")[0]
    if path == "/update/check":
        updater.check_in_background()
    elif path == "/update/usb":
        started, message = updater.start_usb_update()
    else:
        started, message = updater.start_update()
    status = updater.status()
    status.update(view(status))
    h.send(json.dumps({"message": message, "started": started, "status": status}), "application/json")
    return True


def api(d, warnings):
    """The text the Reboot button asks to confirm."""
    d["reboot"] = {"confirm": "Reboot the Raspberry Pi now? The boards are back in about a minute."}


GET = {"/update": _get_update}
POST = {"/reboot": _post_reboot, "/update/check": _post_update, "/update/start": _post_update, "/update/usb": _post_update}
