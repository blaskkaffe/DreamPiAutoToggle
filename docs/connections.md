# Connections between modules

Modules do not call each other. A module says what it can **tell** (its *outputs*) and what it can **do** (its *inputs*), and the
user makes **links**: "when this output happens, run that input". Every module works without the others: an output with no link
does nothing, and a link to a module that is not there (or switched off) is skipped. Back to [CLAUDE.md](../CLAUDE.md);
the code is `netswitch_bus.py` (base, Python 2 and 3).

## What a module declares

In its `module.json`:

```json
"io": "netswitch_switcher_io",
"outputs": [{"id": "network_selected", "label": "The selected network changed"}],
"inputs":  [{"id": "select_network", "label": "Select a network", "summary": "Select {network}",
             "params": [{"key": "network", "label": "Network", "type": "select", "options": [["dcnow", "DCNow!"], ["dcnet", "DCNET"]]}]}]
```

- `id`: lower case letters, digits and `_`. The full name is `module.id` (`switcher.select_network`).
- `label`: what the page's lists show. `summary` (inputs): the short name of the input with its settings (`{key}` = the value picked),
  used where a list says what something does ("Select DCNow! and hang up").
- `params`: `type` is `select` (with `options`: `[value, label]` pairs), `text` or `number`; `default` is optional (a select's is its
  first option). Values are checked against this when links are saved.
- `io`: the file in the module's folder with the **handlers** of its inputs.

## The io file (the rule that makes it work in any process)

```python
import netswitch_bus as bus
import netswitch_core as core

def select_network(params, ctx):            # params: the link's settings (with {texts} filled in), ctx: who asks
    ...                                      # does the thing; may call bus.emit("switcher.network_selected", {...}, ctx)
INPUTS = {"select_network": select_network}
```

**An io file imports only the base (`netswitch_core`, `netswitch_bus`) and works through files.** Nothing else, so the web page, the
DreamPi hook (Python 2.7, inside DreamPi), the buttons service and any other process can run it directly, with no server in between.
It is kept Python 2 and 3 compatible (a test checks the syntax) and must load on its own (a test imports each one in a bare process).
It raises an exception for a bad request; the bus catches it, logs it and carries on with the other links.
A module makes something happen by calling `bus.emit("mymodule.output", data, ctx)` (data fills `{texts}` in the settings of the links).

## The links

`links.json` in `/opt/dreampi-netswitch`: `{"links": [{"from": "numbers.call_dcnow", "to": "switcher.select_network", "params": {"network": "dcnow"}}]}`.
Until the user changes anything the app uses the **standard links** of `profile.json` (it sits next to the code and ships with the
add-on; the same file can say which modules start on: `"modules": {"clock": false}`, the user's own choice in the module picker
still wins). Saving writes `links.json`, even an empty list; **Restore standard** deletes it.

Settings > System > **Connections** > Edit: each link is "When [output]" / "Do [input]" with the input's settings; Add connection,
Remove, Restore standard. The lists show what the loaded modules offer; a link to a module that is off stays (and shows as "Not
loaded") until it comes back. `GET /bus` (outputs, inputs, links, standard links), `POST /bus/links` `{"links": [...]}`,
`POST /bus/reset`, `POST /bus/dismiss` `{"id"}` (a notice).

## What the base offers every module

| Name | Kind | What |
|---|---|---|
| `app.notice` | input | A banner on the page for N seconds (`text`, `seconds`; stored in `/tmp/dreampi-netswitch.notices`, dismiss with ✕) |
| `app.colour` | input | Give a colour of a loaded module a palette colour (`target` = `module.key`, `colour`), the same as its colour pick in Appearance |
| `app.started` | output | The add-on's web service started |

## Who is connected today

| From | To (standard) | Notes |
|---|---|---|
| `numbers.toggle_dcnow` / `toggle_dcnet` (a "hang-up" number was dialed) | `switcher.select_network` DCNow! / DCNET | The hook also leaves the call unanswered and plays a busy tone: that is what a hang-up list *is*. |
| `numbers.call_dcnow` / `call_dcnet` (a "call" number was dialed) | `switcher.select_network` DCNow! / DCNET | The call connects, through the network that is selected after the links ran. |
| `switcher.network_selected` | (nothing) | Told by every way of switching: the page, a number, a link. |

The hook is the only part that knows no modules: dialing a number emits `numbers.<list>` and the bus does the rest. Without the
bus files, or without the numbers module, the lists act as they always did (`11111` selects DCNow!), so a damaged install still
routes calls.

## Not done yet (next steps)

- The two GPIO buttons still choose from a fixed list of functions (`core.BUTTON_FUNCTIONS`); they should become outputs
  (pressed, closed, opened, held) of the switcher module with their actions as links.
- The LED messages still read the other modules' state from core (`ledconfig.gather()`); they should become *state* outputs that
  any module can publish, so the LED message list is "everything the loaded modules can tell".
- More inputs: highlight a box, show an LED look for a while, reboot, check for updates.
