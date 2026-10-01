"""Shared helpers for the tests: import the add-on modules from the repo root
and point every file path they use at a throw-away directory, so tests never
touch /opt/dreampi-netswitch or /tmp/dreampi-netswitch.*."""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_argv, sys.argv = sys.argv, sys.argv[:1]   # netswitch_web reads the ports from sys.argv at import
import netswitch_core as core  # noqa: E402
import netswitch_probes as probes  # noqa: E402
import netswitch_web as web  # noqa: E402
sys.argv = _argv


def sandbox(*modules):
    modules = (core, probes, web) + tuple(m for m in modules if m not in (core, probes, web))
    """Redirect every path constant of web (and the given modules, which
    usually re-export or copy some) into a fresh temp dir. Returns the dir;
    the caller removes it with shutil.rmtree."""
    tmp = tempfile.mkdtemp(prefix="dpns-test-")
    base = core.BASE_DIR
    for mod in modules:
        for name in dir(mod):
            val = getattr(mod, name)
            if not isinstance(val, str) or name.startswith("__") or name == "STATIC_DIR":
                continue
            if val.startswith(base + "/") or val == base:
                setattr(mod, name, tmp + val[len(base):])
            elif val.startswith("/tmp/dreampi-netswitch"):
                setattr(mod, name, os.path.join(tmp, os.path.basename(val)))
    return tmp


def cleanup(tmp):
    shutil.rmtree(tmp, ignore_errors=True)
