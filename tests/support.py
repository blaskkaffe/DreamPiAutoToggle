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
BASE = os.path.join(ROOT, "base")           # the reusable framework: base_*.py (the project's own files are in modules/ and, for now, next to this folder)
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# every module's folder is importable by name, as the web service and the services do it
_MODULES = os.path.join(ROOT, "modules")
for _name in sorted(os.listdir(_MODULES)):
    if os.path.isdir(os.path.join(_MODULES, _name)) and os.path.join(_MODULES, _name) not in sys.path:
        sys.path.insert(0, os.path.join(_MODULES, _name))

import base_core as core  # noqa: E402
import netswitch_ledconfig as ledconfig  # noqa: E402
import netswitch_switcher_probes as probes  # noqa: E402
import base_web as web  # noqa: E402

# every module file is imported now, before any test redirects a path: the paths each module keeps (it makes them from core.BASE_DIR)
# are then taken from the real values, and sandbox() redirects all of them
import importlib  # noqa: E402
_ALL = []
for _name in sorted(os.listdir(_MODULES)):
    for _f in sorted(os.listdir(os.path.join(_MODULES, _name))):
        if _f.endswith(".py") and _f.startswith("netswitch_"):
            try:
                _ALL.append(importlib.import_module(_f[:-3]))
            except Exception as _e:        # a file that needs Python 2 or hardware only
                sys.stderr.write("tests/support.py: %s not imported: %s\n" % (_f, _e))

__all__ = ['ROOT', 'core', 'ledconfig', 'probes', 'web', 'sandbox', 'cleanup']


_ORIGINAL = {}   # module -> {name: original string value}, taken the first time a module is sandboxed
ORIGINAL_BASE = core.BASE_DIR


def sandbox(*modules):
    """Redirect every path constant of the add-on modules (and any extra
    module given, e.g. the hook, which keeps its own copies) into a fresh
    temp dir. Always maps from the original values, so repeated sandboxes
    never see an earlier test's deleted directory. Returns the dir; the
    caller removes it with cleanup()."""
    tmp = tempfile.mkdtemp(prefix="dpns-test-")
    base = ORIGINAL_BASE
    for mod in tuple(dict.fromkeys((core, web) + tuple(_ALL) + modules)):
        if mod not in _ORIGINAL:
            _ORIGINAL[mod] = dict((n, getattr(mod, n)) for n in dir(mod)
                                  if isinstance(getattr(mod, n), str) and not n.startswith("__") and n != "STATIC_DIR")
        for name, val in _ORIGINAL[mod].items():
            if val.startswith(base + "/") or val == base:
                setattr(mod, name, tmp + val[len(base):])
            elif val.startswith("/tmp/dreampi-netswitch"):
                setattr(mod, name, os.path.join(tmp, os.path.basename(val)))
    return tmp


def cleanup(tmp):
    shutil.rmtree(tmp, ignore_errors=True)
