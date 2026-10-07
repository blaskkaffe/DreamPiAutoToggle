# Check-in add-on - OPTIONAL "Background image" module, web side: a picture that the user uploads is the page's background.
#   GET  /imagebg           the form reply of Settings > Background image (fit, darken)
#   POST /imagebg           {"values": {"fit": "cover", "dim": 25}}
#   POST /imagebg/upload    the picture itself as the body (PNG, JPEG, GIF or WebP, at most 8 MB; the page shrinks big ones first)
#   POST /imagebg/remove    deletes the picture
#   GET  /imagebg/image     the picture (the page asks for /imagebg/image?v=<version>, so a new one is fetched when it changes)
# /api has "imagebg": {"has", "fit", "dim", "version"}; the page (page.js) draws the background from it. The picture is checked by its first
# bytes, never by what the browser says it is, and is only ever served as an image. Works on Python 3 and 2.7.
import json
import os
import time

import netswitch_core as core

MAX_BYTES = 8000000
FITS = [("cover", "Cover the screen"), ("contain", "Show it whole"), ("stretch", "Stretch"), ("tile", "Tile")]
DIMS = [0, 25, 50, 75]
DEFAULT = {"fit": "cover", "dim": 25, "type": "", "version": 0}


def sniff(data):
    """The picture type from its first bytes, or None for anything that is not a PNG, JPEG, GIF or WebP picture."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def config():
    out = dict(DEFAULT)
    try:
        with open(core.IMAGEBG_CONFIG) as f:
            data = json.load(f)
    except (IOError, OSError, ValueError):
        data = {}
    if isinstance(data, dict):
        if data.get("fit") in [f[0] for f in FITS]:
            out["fit"] = data["fit"]
        if data.get("dim") in DIMS:
            out["dim"] = data["dim"]
        if data.get("type") in ("image/png", "image/jpeg", "image/gif", "image/webp") and os.path.exists(core.IMAGEBG_FILE):
            out["type"] = data["type"]
            if isinstance(data.get("version"), int):
                out["version"] = data["version"]
    return out


def save_config(cfg):
    tmp = core.IMAGEBG_CONFIG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, sort_keys=True)
    os.rename(tmp, core.IMAGEBG_CONFIG)


def view():
    cfg = config()
    return {"has": bool(cfg["type"]), "fit": cfg["fit"], "dim": cfg["dim"], "version": cfg["version"]}


def api(d, warnings):
    d["imagebg"] = view()


def _form_reply():
    cfg = config()
    fit = dict(FITS)[cfg["fit"]]
    return {"values": {"fit": cfg["fit"], "dim": cfg["dim"]},
            "options": {"fits": [{"value": k, "label": v} for k, v in FITS], "dims": [{"value": n, "label": "Off" if n == 0 else "%d %%" % n} for n in DIMS]},
            "texts": {"fit": fit, "dim": "Not darkened" if not cfg["dim"] else "%d %% darker, for the text's sake" % cfg["dim"]}}


def _get_form(h):
    h.send(json.dumps(_form_reply()), "application/json")


def _post_form(h):
    try:
        values = json.loads(h._body(1024).decode("utf-8")).get("values") or {}
    except (ValueError, AttributeError):
        h.send("Bad request", "text/plain; charset=utf-8", status=400)
        return True
    cfg = config()
    if values.get("fit") in [f[0] for f in FITS]:
        cfg["fit"] = values["fit"]
    try:
        if int(values.get("dim")) in DIMS:
            cfg["dim"] = int(values["dim"])
    except (TypeError, ValueError):
        pass
    save_config(cfg)
    h.send(json.dumps(_form_reply()), "application/json")
    return True


def _get_image(h):
    cfg = config()
    if not cfg["type"]:
        h.send("", "text/plain; charset=utf-8", status=404)
        return
    try:
        with open(core.IMAGEBG_FILE, "rb") as f:
            body = f.read()
    except (IOError, OSError):
        h.send("", "text/plain; charset=utf-8", status=404)
        return
    h.send(body, cfg["type"], cache=86400)


def _post_upload(h):
    try:
        length = int(h.headers.get("Content-Length") or 0)
    except ValueError:
        length = 0
    if length > MAX_BYTES:
        h.send("The picture is too big (%d MB at most)" % (MAX_BYTES // 1000000), "text/plain; charset=utf-8", status=413)
        return True
    data = h._body(MAX_BYTES)
    kind = sniff(data)
    if not data or kind is None:
        h.send("Not a PNG, JPEG, GIF or WebP picture", "text/plain; charset=utf-8", status=400)
        return True
    tmp = core.IMAGEBG_FILE + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.rename(tmp, core.IMAGEBG_FILE)
    cfg = config()
    cfg.update(type=kind, version=int(time.time() * 1000))
    save_config(cfg)
    core.log("Background image: %d KB %s uploaded" % (len(data) // 1000, kind))
    h.send(json.dumps(view()), "application/json")
    return True


def _post_remove(h):
    try:
        os.remove(core.IMAGEBG_FILE)
    except OSError:
        pass
    cfg = config()
    cfg.update(type="", version=int(time.time() * 1000))
    save_config(cfg)
    h.send(json.dumps(view()), "application/json")
    return True


GET = {"/imagebg": _get_form, "/imagebg/image": _get_image}
POST = {"/imagebg": _post_form, "/imagebg/upload": _post_upload, "/imagebg/remove": _post_remove}
