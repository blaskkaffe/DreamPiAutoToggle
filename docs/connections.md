# Connections between modules (jacks and cables)

Think LEGO bricks or a modular synthesizer. Modules never call each other. A module has **jacks**: *outputs* (something it
tells: a number was dialed, DCNET is selected) and *inputs* (something it can do: select DCNET, show a notice). Every jack is a
simple **on / off** value. The user plugs **cables** from an output to an input. Every module works on its own: an output with no
cable does nothing, an input with no cable stays off, and a cable to a module that is not there (or switched off) is skipped.
Back to [CLAUDE.md](../CLAUDE.md); the code is `netswitch_bus.py` (base, Python 2 and 3).

## The rules

- An **input is off by default.** It is on while **any** cable from an output that is on reaches it (the cables are OR'ed), or while
  another module holds it on through the API (`bus.set_input(...)`, below).
- A module is told **once per change**: `on` when the input goes from off to on, `off` when it goes back. Most inputs only act on
  the edge to on (select DCNET, show a notice, start Wi-Fi setup); some are plain levels that something else reads while they
  are on (the LED alerts, "make a box stand out").
- A cable can be **inverted**: it then carries the opposite (the input is on while the output is off).
- Some inputs have **knobs**: settings of the input itself (the text and seconds of a notice, which box to highlight). They belong
  to the input, not to a cable, and are saved with the cables in `links.json` under `"knobs"`.
- An **output** is either *stored* (the module sets it with `bus.set_output(id, on)` or `bus.pulse(id, seconds)`) or *computed* (the
  io file has a function in `OUTPUTS` that tells the fact: which network is selected, is the modem plugged in). Computed outputs
  are read by the web service about once a second and right away after `bus.refresh(id)`.
- A **pulse** is an output that is on for a moment (default 1 s: a number was dialed). Pulsing twice quickly counts twice (the
  output goes low and high again, a new edge). After a reboot every jack is off.

## What a module declares

In its `module.json`:

```json
"io": "netswitch_switcher_io",
"outputs": [{"id": "dcnet_selected", "label": "DCNET is selected"}],
"inputs":  [{"id": "select_dcnet", "label": "Select DCNET"},
            {"id": "notice_a", "label": "Show notice A",
             "params": [{"key": "text", "label": "Text", "type": "text", "default": "Hello"}]}]
```

- `id`: lower case letters, digits and `_`. The full name is `module.id` (`switcher.select_dcnet`).
- `label`: what the lists on the page show; say what is *true* for an output ("Call number A was dialed") and what *happens* for an
  input ("Select DCNET").
- `params` (inputs only, the knobs): `type` is `select` (with `options`: `[value, label]` pairs), `text` or `number`; `default` is
  optional. Values are checked against this when they are saved.
- `io`: the file in the module's folder with the code behind the jacks.

## The io file (the rule that makes it work in any process)

```python
import netswitch_bus as bus
import netswitch_core as core

def select_dcnet(on, knobs, ctx):       # on: True/False, knobs: the input's settings, ctx: who asks
    if on:
        ...                              # does the thing; may call bus.refresh("switcher.dcnet_selected", ctx)
INPUTS = {"select_dcnet": select_dcnet}   # a level input that something else reads: "alert_a": None
OUTPUTS = {"dcnet_selected": lambda: os.path.exists(core.FLAG)}      # computed outputs (a fact)
```

**An io file imports only the base (`netswitch_core`, `netswitch_bus`) and works through files.** Nothing else, so the web page, the
DreamPi hook (Python 2.7, inside DreamPi), the buttons service and any other process can run it directly, with no server in between.
It is kept Python 2 and 3 compatible (a test checks the syntax) and must load on its own (a test imports each one in a bare
process). A handler that raises is logged and the other inputs carry on. Every id in `INPUTS` / `OUTPUTS` must be declared in the
`module.json` (a test checks).

## The API for modules

| Call | What |
|---|---|
| `bus.set_input(iid, on, source)` | Hold another module's input on (or let go): `source` says who asks; an input is on while any source holds it. Returns the inputs that were switched on by it. |
| `bus.set_output(oid, on, ctx, until)` | Turn one of your stored outputs on or off (`until`: a time after which it is off again). |
| `bus.pulse(oid, seconds, ctx)` | An output that is on for a moment. Returns the inputs it switched on. |
| `bus.refresh(oid)` | A computed output may have changed: tell the cables. |
| `bus.input_level(iid)` / `bus.output_level(oid)` | Read a level (the LED reads its alerts this way). |
| `bus.poll()` | About once a second (the web service does it): runs out pulses and timers, reads computed outputs, tells modules that came back. |

## The cables

`links.json` in `/opt/dreampi-netswitch`: `{"links": [{"from": "numbers.call_dcnow", "to": "switcher.select_dcnow", "invert": false}],
"knobs": {"app.notice_a": {"text": "Hi", "seconds": 30}}}`. Until the user changes anything the app uses the **standard cables** of
`profile.json` (next to the code, ships with the add-on; the same file can say which modules start on: `"modules": {"clock": false}`,
the user's own choice in the module picker still wins). Saving writes `links.json`, even with no cables; **Restore standard**
deletes it. After a change the bus makes every input agree with the cables at once (`bus.resync()`).

Settings > System > **Connections** > Edit: each cable is *From* (an output) and *To* (an input), with **Inverted** and the settings
of the input; **Add cable**, **Remove**, **Restore standard**. A small "on now / off now" shows the live level of both ends. A cable to a
module that is off stays (it shows as "Not loaded") and the module is told about its input when it comes back. `GET /bus` (outputs,
inputs, cables, standard cables, knobs, levels), `POST /bus/links` `{"links": [...], "knobs": {...}}`, `POST /bus/reset`, `POST /bus/dismiss`
`{"id"}` (a notice).

State between processes lives in files in `/tmp/dreampi-netswitch.signals/`: `out.<id>` (an output is on; the content is the time it
ends, or empty), `in.<id>.<source>` (one file per holder of an input), `ih.<id>` (the module was told "on").

## The base's own brick: `app`

| Jack | Kind | What |
|---|---|---|
| `app.on` | output | Always on (a constant: connect it to an input that should always be on). |
| `app.started` | output | A 3 second pulse when the add-on's web service starts. |
| `app.notice_a` / `_b` / `_c` | input | A banner on the page when it turns on (knobs `text`, `seconds`; dismiss with ✕). |
| `app.highlight_a` / `_b` / `_c` | input | The box stands out while it is on (knobs `box`, `why`; the look is Settings > Appearance > Notification highlight). |
| `app.colour_a` / `_b` / `_c` | input | When it turns on, a module's colour gets a palette colour (knobs `target` = `module.key`, `colour`). |
| `app.timer1_start` / `timer2_start` | input | Start a timer (knob `seconds`). |
| `app.timer1_running` / `timer2_running` | output | On while the timer runs: a number can light an LED alert for 30 seconds through two cables. |

## Who is connected today

| Module | Outputs | Inputs |
|---|---|---|
| `numbers` | Hang-up number A / B was dialed, Call number A / B was dialed (pulses; the hook pulses them before it routes the call) | none |
| `switcher` | DCNow! / DCNET is selected, DreamPi is ready, a call is in progress, network / internet OK, modem plugged in | Select DCNow!, Select DCNET, Toggle the network |
| `led` | none | Alert A / B / C on (put the LED message of the same name in a colour row of Settings > Status LED) |
| `wifi` | Setup running / connected / failed | Start, stop, toggle the Wi-Fi setup |
| `players` | A game was played, a friend came online | none |
| `events` | An event reminder is due | none |
| `rebootupdate` | An add-on / DreamPi update is available, an update is running / failed, the Pi is rebooting | none |

The standard cables are what the add-on did before: the four number lists select DCNow! or DCNET (hang-up lists also leave the call
unanswered, call lists connect it through the network that is selected after the cables ran). The hook knows no other module: it
pulses `numbers.<list>` and the bus does the rest. Without the bus files, or without the numbers module, the lists act as they always
did (`11111` selects DCNow!), so a damaged install still routes calls.

## Not done yet (next steps)

- The two GPIO buttons still choose from a fixed list of functions (`core.BUTTON_FUNCTIONS`); they should become outputs
  (pressed, closed, opened, held) of the switcher module with their actions as cables.
- The LED messages still read the other modules' state from core (`ledconfig.gather()`); they should become cables from the
  outputs above (a state output into an LED alert), so the message list is "everything the loaded modules can tell".
- The events module's direct clock highlight should become a cable (`events.reminder_due` into `app.highlight_a`).
- More inputs: reboot, check for updates.
