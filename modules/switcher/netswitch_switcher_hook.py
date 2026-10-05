# DreamPi Netswitch add-on - network switcher module, the part that runs inside DreamPi.
# netswitch_hook.py loads this file (module.json "hook") and calls ACTIONS[<id>](call) when a phone number row names
# "switcher.<id>" (the actions are announced in module.json "actions"). "call" has .raw (what was dialed), .number (the number
# it matched), .base_dir (the add-on's folder) and .log(text). An action returns a short text of what it did.
# Runs in DreamPi, so it must stay Python 2.7 and 3 compatible: no f-strings, no type hints.
import os


def _flag(call):
    return os.path.join(call.base_dir, "dcnet_mode")        # exists = DCNET is selected


def _select(call, dcnet):
    flag = _flag(call)
    if dcnet:
        open(flag, "w").close()
    elif os.path.exists(flag):
        os.remove(flag)
    return "DCNET selected" if dcnet else "DCNow! selected"


def dcnow(call):
    return _select(call, False)


def dcnet(call):
    return _select(call, True)


def toggle(call):
    return _select(call, not os.path.exists(_flag(call)))


ACTIONS = {"toggle": toggle, "dcnow": dcnow, "dcnet": dcnet}
