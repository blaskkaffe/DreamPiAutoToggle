# DreamPi Netswitch add-on - LED module: what the LED messages are made from. Every other module keeps its state in a file and
# documents it (docs/*.md); this module reads those files itself, so it imports no other module and the base knows none of them.
# Each reader here follows the format its owner writes: the network switcher (DreamPi's state, the selected network, the
# measurements), the Wi-Fi setup, the update and reboot module, the players and the events modules. Works on Python 3 and 2.7.
import json
import os
import re
import time

import base_core as core

BASE_DIR, TMP = core.BASE_DIR, core.TMP_PREFIX

# the network switcher's files
FLAG = os.path.join(BASE_DIR, "dcnet_mode")        # exists = DCNET is selected
STATUS = TMP + ".active"                           # "active pid=N" while DreamPi runs the hook, or why it does not
STATE = TMP + ".state"                             # "<starting|ready|call dcnow|call dcnet> <unix time>", written by the hook
NET_STATE = TMP + ".net"                           # JSON of the checker (links, internet, Pi health, modem ...), written every few seconds
NET_STALE = 20                                     # ignore NET_STATE when older than this (the web service is down)
# the Wi-Fi module's
WIFI_STATE = TMP + ".wifi"                         # {"state": idle|scanning|hosting|connecting|ok|failed, "time"}
WIFI_STALE = 30                                    # ignore it when older than this (the service is down)
# the update module's and the reboot's
UPDATE_STATUS = TMP + ".update"                    # running / ok / failed
UPDATE_INFO = TMP + ".updateinfo"                  # {"addon": bool|None, "dreampi": bool, "time"}: the latest manual check
REBOOT_MARK = TMP + ".reboot"                      # the unix time a reboot was asked for
# the players module's
PLAYERS_WATCH = TMP + ".players"                   # {"time", "games": [...], "friends": [...]}
PLAYERS_WATCH_STALE = 300                          # ignore it when older than this
# the events module's
EVENT_REMINDERS = os.path.join(BASE_DIR, "event_reminders.json")


def state_paths():
    """The files whose change the LED service should look at quickly (they are written in one go, by a rename)."""
    return (STATE, STATUS, NET_STATE, WIFI_STATE, UPDATE_STATUS, UPDATE_INFO, REBOOT_MARK, PLAYERS_WATCH, EVENT_REMINDERS)


def selected():
    """The selected network: "dcnet" or "dcnow"."""
    return "dcnet" if os.path.exists(FLAG) else "dcnow"


def _hook_problem():
    """None when DreamPi is running with the add-on's hook loaded, else a reason."""
    status = core.read_file(STATUS)
    if status is None:
        return "not loaded"
    if not status.startswith("active"):
        return status
    m = re.search(r"pid=(\d+)", status)
    if m and not os.path.exists("/proc/" + m.group(1)):
        return "DreamPi is not running"
    return None


def dreampi_state():
    """What DreamPi is doing: "off", "unknown", "busy" (starting), "ok" (ready), "call-dcnow", "call-dcnet" or "call"."""
    if _hook_problem() == "DreamPi is not running":
        return "off"
    parts = (core.read_file(STATE) or "").split()
    if len(parts) < 2:
        return "unknown"
    state = " ".join(parts[:-1])
    if state == "starting":
        return "busy"
    if state == "ready":
        return "ok"
    if state.startswith("call "):
        kind = state[5:]
        return "call-" + kind if kind in ("dcnow", "dcnet") else "call"
    return "unknown"


def network_state():
    """The checker's latest link + internet state, or None."""
    try:
        with open(NET_STATE) as f:
            data = json.load(f)
        if time.time() - data.get("time", 0) > NET_STALE:
            return None
        return data
    except (IOError, OSError, ValueError):
        return None


def wifi_state():
    """The Wi-Fi setup's state text: idle / scanning / hosting / connecting / ok / failed (idle when it is down)."""
    try:
        with open(WIFI_STATE) as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        return "idle"
    if data.get("state", "idle") != "idle" and time.time() - data.get("time", 0) > WIFI_STALE:
        return "idle"
    return data.get("state", "idle")


def update_status():
    """running / ok / failed, or idle (a finished result is only reported for 10 minutes)."""
    text = (core.read_file(UPDATE_STATUS) or "").strip()
    if text not in ("running", "ok", "failed"):
        return "idle"
    try:
        if text != "running" and time.time() - os.path.getmtime(UPDATE_STATUS) > 600:
            return "idle"
    except OSError:
        return "idle"
    return text


def update_info():
    """{"addon": bool|None, "dreampi": bool} from the latest manual check, {} when there is none."""
    try:
        with open(UPDATE_INFO) as f:
            return json.load(f)
    except (IOError, OSError, ValueError, AttributeError):
        return {}


def reboot_pending():
    """True for a minute after a reboot was asked for."""
    try:
        return time.time() - float(core.read_file(REBOOT_MARK) or "0") < 60
    except ValueError:
        return False


def players_watch():
    """{"games": [...], "friends": [...]} of favourites that are online now; empty when stale."""
    try:
        with open(PLAYERS_WATCH) as f:
            data = json.load(f)
        if time.time() - data.get("time", 0) > PLAYERS_WATCH_STALE:
            return {"games": [], "friends": []}
        return {"games": list(data.get("games") or []), "friends": list(data.get("friends") or [])}
    except (IOError, OSError, ValueError, AttributeError, TypeError):
        return {"games": [], "friends": []}


def event_reminder(now=None):
    """The reminded event that is due now, or None: {"id", "title", "start"}. The events module writes EVENT_REMINDERS
    ({"lead": minutes before, "after": minutes after the start, "items": [{"id", "title", "start"}], "dismissed": [ids]})."""
    now = time.time() if now is None else now
    try:
        with open(EVENT_REMINDERS) as f:
            data = json.load(f)
        lead, after = float(data.get("lead", 15)) * 60, float(data.get("after", 10)) * 60
        gone = set(data.get("dismissed") or [])
        due = [i for i in data.get("items") or [] if i.get("id") not in gone and i["start"] - lead <= now < i["start"] + after]
    except (IOError, OSError, ValueError, AttributeError, KeyError, TypeError):
        return None
    return min(due, key=lambda i: i["start"]) if due else None


def gather(live=True):
    """What the messages are made from: {"state", "selected", "net", "players", "wifi", "update", "update_info", "reboot",
    "dcnet_problem", "event"}. live=False is only what DreamPi is doing and which network is selected (the status dot's preview)."""
    ctx = {"state": dreampi_state(), "selected": selected(),
           "net": {}, "players": {}, "wifi": "idle", "update": "idle", "update_info": {}, "reboot": False, "dcnet_problem": False, "event": None}
    if live:
        net = network_state() or {}
        ctx.update(net=net, wifi=wifi_state(), update=update_status(), update_info=update_info(), reboot=reboot_pending(),
                   players=players_watch(), dcnet_problem=bool(net.get("dcnet_problem")), event=event_reminder())
    return ctx
