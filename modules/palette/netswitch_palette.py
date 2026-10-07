# DreamPi Netswitch add-on - OPTIONAL "Colour palette" module, web side: the editor of the palette every colour pick, box and LED row draws from.
#   GET  /palette/list     {"colours": [{"id", "name", "ui", "ui_l", "led", "ui_default", "led_default", "fixed", "custom", "changed"}, ...]} in the palette's order
#   POST /palette/edit     {"id", "name"?, "ui"?, "led"?}   rename a colour and / or change its colour on screen / on the LED ("#rrggbb")
#   POST /palette/add      {"name", "ui", "led"?}           a new colour at the end (answers with its id too)
#   POST /palette/delete   {"id"}                           (not Global main, Selected network or orange; what used it falls back to its default)
#   POST /palette/order    {"order": [ids]}
#   POST /palette/reset    {} = the palette the add-on ships (all colours, names, order and changes), or {"id"} = one shipped colour
# The logic is the base's (core.palette_*); the list is kept in palette_custom.json (core.PALETTE_CUSTOM) and only counts while this module is on. Every answer is the
# list again. The page follows at once: /api carries the palette whenever it changed (see applyPalette() in page.js). Works on Python 3 and 2.7.
import json

import netswitch_core as core


def _list():
    out = []
    for c in core.colours():
        shipped = [s for s in core.PALETTE if s[0] == c["id"]]
        name_default = shipped[0][1] if shipped else c["name"]
        out.append({"id": c["id"], "name": c["name"], "ui": c["ui"], "ui_l": c["ui_l"], "led": c["led"], "ui_default": c["ui_default"], "led_default": c["led_default"],
                    "fixed": c["id"] in core.FIXED_COLOURS, "custom": not shipped,
                    "changed": bool(shipped) and (c["ui"] != c["ui_default"] or c["led"] != c["led_default"] or c["name"] != name_default)})
    return out


def _reply(h, extra=None):
    body = {"colours": _list(), "can_add": len([c for c in _list() if c["custom"]]) < core.MAX_CUSTOM_COLOURS}
    body.update(extra or {})
    h.send(json.dumps(body), "application/json")
    return True


def _body(h):
    try:
        data = json.loads(h._body(4096).decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _get_list(h):
    _reply(h)


def _bad(h, text):
    h.send(text, "text/plain; charset=utf-8", status=400)
    return True


def _post_edit(h):
    d = _body(h)
    if not core.palette_edit(d.get("id"), d.get("name"), d.get("ui"), d.get("led")):
        return _bad(h, "Not a colour of the palette, or not #rrggbb")
    return _reply(h)


def _post_add(h):
    d = _body(h)
    ident = core.palette_add(d.get("name"), d.get("ui"), d.get("led"))
    if ident is None:
        return _bad(h, "Not a colour (#rrggbb), or the palette is full")
    return _reply(h, {"id": ident})


def _post_delete(h):
    if not core.palette_delete(_body(h).get("id")):
        return _bad(h, "That colour cannot be deleted")
    return _reply(h)


def _post_order(h):
    if not core.palette_order(_body(h).get("order")):
        return _bad(h, "order must be a list of colour ids")
    return _reply(h)


def _post_reset(h):
    ident = _body(h).get("id")
    if not core.palette_reset(ident if ident else None):
        return _bad(h, "Not one of the colours the add-on ships")
    return _reply(h)


GET = {"/palette/list": _get_list}
POST = {"/palette/edit": _post_edit, "/palette/add": _post_add, "/palette/delete": _post_delete, "/palette/order": _post_order, "/palette/reset": _post_reset}
