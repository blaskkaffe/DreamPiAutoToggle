# DreamPi Netswitch add-on - Dreamcast background module, web side: serves the module's own script files to the page.
# The scene (dc-background.js) is Robert Dale Smith's, three.min.js is Three.js; licences in LICENSES.txt next to them.
import os

import netswitch_core as core

_FILES = {"/background/three.min.js": ("three.min.js", "application/javascript; charset=utf-8"),
          "/background/dc-background.js": ("dc-background.js", "application/javascript; charset=utf-8"),
          "/background/LICENSES.txt": ("LICENSES.txt", "text/plain; charset=utf-8")}
_cache = {}


def _serve(path):
    def handler(h):
        name, ctype = _FILES[path]
        if name not in _cache:
            try:
                with open(os.path.join(core.MODULES_DIR, "background", name), "rb") as f:
                    _cache[name] = f.read()
            except (IOError, OSError):
                h.send("", "text/plain; charset=utf-8", status=404)
                return
        h.send(_cache[name], ctype, cache=86400, fixed=True)
    return handler


GET = dict((path, _serve(path)) for path in _FILES)
