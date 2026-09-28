# -*- coding: utf-8 -*-
"""
DreamPi Netswitch add-on - routing hook.

Loaded automatically by Python (through a .pth file) but does nothing unless
the running program imports DreamPi's netlink.py from /home/pi/dreampi.
It then wraps Netlink.check_number() with these rules:

  1111111  openMenu's number. Always DC Now. If the reset toggle is on,
           it also switches the selected network back to DC Now.
  2222222  Selects DC Now and connects through DC Now.
  3333333  Selects DCNet and connects through DCNet.
  others   Go to whichever network is selected (website or 2222222/3333333).
           Only calls DreamPi would send to its normal PPP are redirected;
           Netlink/XBAND codes and the built-in *69 prefix are untouched.

The selection is the file dcnet_mode, the reset toggle is the file autoreset.
No DreamPi file is modified. Written for both Python 2.7 and 3.
"""
import os
import sys

BASE_DIR = "/opt/dreampi-netswitch"
FLAG = os.path.join(BASE_DIR, "dcnet_mode")
AUTORESET = os.path.join(BASE_DIR, "autoreset")
STATUS = "/tmp/dreampi-netswitch.active"
NETLINK_DIR = "/home/pi/dreampi"

NUM_OPENMENU = "1111111"
NUM_DCNOW = "2222222"
NUM_DCNET = "3333333"

# __builtin__ first: on Python 2 the "future" package can provide a fake
# "builtins" module, and patching that would do nothing.
try:
    import __builtin__ as _builtins  # Python 2
except ImportError:
    import builtins as _builtins  # Python 3

_original_import = _builtins.__import__
_done = [False]


def _log(obj, text):
    try:
        obj.logger.info("netswitch: " + text)
    except Exception:
        pass


def _write_status(text):
    try:
        with open(STATUS, "w") as f:
            f.write(text + "\n")
    except Exception:
        pass


def _select_dcnet(on):
    if on:
        open(FLAG, "w").close()
    elif os.path.exists(FLAG):
        os.remove(FLAG)


def _special(raw_string):
    """Which special number was dialed, matched on the last seven digits.
    DreamPi often hears an extra leading digit (e.g. 13333333), and ISP
    settings may add a prefix or area code, so exact matching is unreliable."""
    for number in (NUM_OPENMENU, NUM_DCNOW, NUM_DCNET):
        if raw_string.endswith(number):
            return number
    return None


def _patch(module):
    cls = getattr(module, "Netlink", None)
    original = getattr(cls, "check_number", None) if cls is not None else None
    if original is None:
        _write_status("error: Netlink.check_number not found, add-on inactive")
        return
    if getattr(original, "_netswitch", False):
        return

    def check_number(self, raw_string):
        special = _special(raw_string)
        # Special numbers: remember the choice before DreamPi routes the call
        try:
            if special == NUM_DCNOW:
                _select_dcnet(False)
                _log(self, "%s dialed, DC Now selected" % raw_string)
            elif special == NUM_DCNET:
                _select_dcnet(True)
                _log(self, "%s dialed, DCNet selected" % raw_string)
            elif special == NUM_OPENMENU and os.path.exists(AUTORESET) and os.path.exists(FLAG):
                _select_dcnet(False)
                _log(self, "%s dialed with reset on, back to DC Now" % raw_string)
        except Exception as e:
            _log(self, "could not update selection: %s" % e)

        result = original(self, raw_string)

        try:
            if not (isinstance(result, dict) and result.get("client") == "PPP"):
                return result  # Netlink, XBAND, *69 and idle are left alone
            if special in (NUM_OPENMENU, NUM_DCNOW):
                return result  # always DC Now
            if os.path.exists(FLAG):
                if getattr(self, "dcnet", False):
                    self.mode = "dcnet"
                    self.dial_string = raw_string
                    _log(self, "routing %s to DCNet" % raw_string)
                    return {"client": "dcnet", "dial_string": raw_string}
                _log(self, "DCNet selected but not enabled in netlink_config.ini, using DC Now")
        except Exception:
            pass
        return result

    check_number._netswitch = True
    cls.check_number = check_number
    _write_status("active pid=%d" % os.getpid())


def _import_hook(name, *args, **kwargs):
    module = _original_import(name, *args, **kwargs)
    if not _done[0] and name == "netlink":
        try:
            mod = sys.modules.get("netlink")
            path = os.path.realpath(getattr(mod, "__file__", "") or "")
            if mod is not None and path.startswith(os.path.realpath(NETLINK_DIR)):
                _done[0] = True
                _patch(mod)
                _builtins.__import__ = _original_import
        except Exception as e:
            _write_status("error: %s" % e)
    return module


def _is_dreampi_process():
    # sys.argv does not exist yet when Python 2 processes .pth files, so the
    # command line is read from /proc instead. If that fails, hook anyway:
    # the hook only reacts to netlink.py from /home/pi/dreampi.
    try:
        with open("/proc/self/cmdline", "rb") as f:
            return b"dreampi" in f.read()
    except Exception:
        return True


try:
    if _is_dreampi_process():
        _builtins.__import__ = _import_hook
except Exception:
    pass
