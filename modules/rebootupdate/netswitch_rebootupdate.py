# DreamPi Netswitch add-on - Reboot and Update module, web side:
#   GET  /update          the cached update check (netswitch_update.status())
#   POST /update/check    run a check now
#   POST /update/start    fetch and install the new version (needs the PIN when one is set)
#   POST /reboot          reboot the Pi (needs the PIN when one is set)
# The update logic is in netswitch_update.py next to this file. Without the module the page has no update or
# reboot controls and these paths answer 404.
import json
import subprocess

import netswitch_core as core
import netswitch_update as updater

PROTECTED = ("/reboot", "/update/start")      # run as root: the PIN is asked for when one is set


def _spawn_reboot():
    """Reboot the Pi a couple of seconds from now, so the HTTP answer gets out first. Detached from this service
    (which the reboot stops). Replaced by the tests."""
    subprocess.Popen(["sh", "-c", "sleep 2; systemctl reboot || reboot"],
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def start_reboot():
    """Reboot the whole Raspberry Pi (DreamPi starts again with it). Returns (started, message)."""
    in_call = core.dreampi_state()[0].startswith("call")
    try:
        _spawn_reboot()
    except OSError as e:
        return False, "Could not reboot (%s)" % e
    core.debug_log("web page: reboot requested%s" % (" (a call was in progress)" if in_call else ""))
    return True, "Rebooting"


def _get_update(h):
    h.send(json.dumps(updater.status()), "application/json")


def _post_reboot(h):
    started, message = start_reboot()
    h.send(json.dumps({"started": started, "message": message}), "application/json")
    return True


def _post_update(h):
    if not h.headers.get("X-Requested-With"):   # the check is harmless but still only for the page
        h._refuse(403, "Refused: this request did not come from the page")
        return True
    message = ""
    if h.path.split("?")[0] == "/update/check":
        updater.check_in_background()
    else:
        started, message = updater.start_update()
    h.send(json.dumps({"message": message, "status": updater.status()}), "application/json")
    return True


GET = {"/update": _get_update}
POST = {"/reboot": _post_reboot, "/update/check": _post_update, "/update/start": _post_update}
