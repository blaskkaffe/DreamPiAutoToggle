# Triggers and actions between modules: design proposal

**Status: a proposal for approval. Nothing in "What changes" is built yet.** It builds on what `development` already has (the
numbers rows, `actions` in `module.json`, the `triggers` widget, the LED rows). Back to [CLAUDE.md](../CLAUDE.md).

## 1. What exists today

| Piece | Where | What it does |
|---|---|---|
| `actions` | `module.json` of the switcher | Announces `toggle`, `dcnow`, `dcnet` (id, label, sub-label). `core.module_actions()` lists the actions of the enabled modules as `<module>.<id>`. |
| `hook` | the module's hook file, loaded by `netswitch_dreampi.py` | `ACTIONS = {"dcnow": fn}`; `fn(call)` runs **inside DreamPi** and gets `.raw`, `.number`, `.base_dir`, `.log`. Python 2/3, works through files. |
| Rows | `numbers.json` `{"rows": [{id, action, items, opts: {hangup}}]}` | A row = one action + the numbers that trigger it + "hang up". Default row: `switcher.dcnow` with `11111`. A number may be in several rows. |
| Widget | `triggers` in `page/widgets.js`, answered by `GET`/`POST /numbers` | Edit rows, number chips, Add row, Restore, (i) help. |
| LED rows | `GET`/`POST /ledrows`, `led_messages` in `module.json` | A row = colour + the LED messages (announced by every module) that trigger it; row order is priority. |
| Buttons | `button1_function`, `button2_function`, `wifi_button`; `core.BUTTON_FUNCTIONS` | **Still a fixed list**, run by the buttons service. Not part of the rows. |
| Events, players, updates | each module's own code | Banner, highlight and LED messages are hard-wired. |

What is missing for the whole idea: variables for actions, actions that run outside DreamPi, triggers other than a dialed
number, and the **shared view** of a trigger (section 3).

## 2. Words

- **Action**: something a module can do. Announced in `module.json`, done by that module's hook file.
- **Trigger source**: a module that detects something and has rows (numbers, buttons, events, players).
- **Trigger value**: the thing that fires, shown as a **chip**: a phone number (`11111`), a button event (`Button 1 · closed`),
  "a reminded event is due".
- **Binding**: one trigger value tied to one action, with the source's options (hang up) and the action's variables.
  A binding is **one record**, stored in the source module's own file (numbers keep `numbers.json`).
- One action per row (a second action is a second row). Actions never start triggers, so there can be no loops.

## 3. The shared chip (the new part)

A binding is one record that **two modules show**:

| In the trigger source (numbers) | In the module that owns the action (network switcher) |
|---|---|
| Row "DCNow!" with the chips `11111`, `5550001` | Under **DCNow!** the chips `11111 · Phone numbers`, `5550001 · Phone numbers` |
| Remove a chip: it is gone | It is gone here too |
| Add a number | The chip appears here at once |

Rules:

1. **One record, two views.** Neither module keeps a copy, so they can't disagree. Removing a chip from either side deletes the
   record, and it disappears everywhere it was shown.
2. **Adding from the action's side** asks which source (only sources that are on) and shows that source's own form: a number
   field and the "Hang up" switch for numbers, a button and an event for buttons. It then writes into the source's file through
   the source's own code. The number is appended to a matching row (same action, same options, same variables) or a new row is made.
3. **Where a trigger comes from is always visible.** In the action's view every chip carries a small source mark (the module's
   name, in its colour) and tapping it says *"From Special phone numbers: hang up, then Select DCNow!"*. In the source's view
   every row names the action and the module that owns it (*"Network switcher: Select DCNow!"*).
4. **A source that is off or removed:** its chips stay in the action's view, greyed, with *"Special phone numbers is off"*, and
   they can't be edited until it is back. An action whose module is off keeps its row in the source's view marked *"module is off"*
   (this exists today).
5. **A number in two rows** (allowed today, both run) is two bindings, so two chips under the action. Removing one removes only that one.
6. **Removing the last chip of a row** leaves the row in the source's view (you made it); it just has no numbers.

### How the two views are built

- Each source announces itself in `module.json`: `"triggers": {"label": "Phone numbers", "colour": "...", "source": "/numbers"}`.
- The source's web entry answers a small, fixed interface (its rows, in the shape the `triggers` widget already knows) and takes
  `add` / `remove` for one binding. The base asks every source and merges: `GET /triggers?action=switcher.dcnow` and
  `POST /triggers {op, source, action, value, opts, args}`.
- A standard widget, **`triggered_by`**, draws the chips under an action in the owning module's Settings (the switcher gets a box
  "Network triggers", wifi "Wi-Fi triggers"). Modules only name the action; no module code draws a chip.
- The base never imports module code: it calls the source's web entry through the loader (`base_modules.py`), as it does for every `api()`.

## 4. Variables and placeholders

An announced action may declare variables:

```json
"actions": [
  {"id": "notice", "label": "Show a notice", "sub": "A banner on the page",
   "params": [{"key": "text", "label": "Text", "type": "text", "required": true},
              {"key": "seconds", "label": "Seconds", "type": "number", "default": 30}]}
]
```

- `type` is `text`, `number`, `choice` (with `options`) or `duration`. `required` or optional (`default`). A `duration` is a choice from
  one shared list, so every action that lasts a while (a notice, a highlight, an LED alert) offers the same times; see section 11, point 3.
- The row editor draws the fields under the action. A row missing a required variable is marked *incomplete* and skipped
  (logged), never half-run.
- **Placeholders** are announced by the module that can supply them, in its `module.json`, and any text variable of any action can
  use the placeholders of the modules that are loaded. The editor lists them as chips to tap, grouped by module. With no optional
  module loaded only the base's own are offered: the system (`{time}`, `{date}`, `{hostname}`) and the add-on (`{version}`).
  A module that is off or removed takes its placeholders with it. A placeholder that is still in a saved text but no longer
  announced is shown as written and the row says *"{event}: its module is off"*.
- Two kinds, both announced the same way:
  - **state** placeholders are always available while the module is on (the network switcher: `{network}`, the selected network);
  - **trigger** placeholders only have a value when that module's trigger fired the action (numbers: `{number}`, the number that
    matched; events: `{event}`, `{event_time}`; players: `{player}`, `{game}`; buttons: `{button}`, `{button_event}`). Used in a
    row of another source they come out empty, and the editor warns *"{event} only has a value when an event fires this row"*.
```json
"placeholders": [{"id": "number", "label": "The number that was dialed", "kind": "trigger"},
                 {"id": "network", "label": "The selected network", "kind": "state"}]
```
  The module's hook file supplies the values (`PLACEHOLDERS = {"number": fn(call)}`), so they work in any process.
  A placeholder id is owned by the first module (picker order) that announces it; the base's ids are reserved. A text variable is
  filled in when the action runs, never stored filled in.
- Variables belong to the **row** (numbers) or the **binding** (buttons, events), so the same action can appear twice with different
  texts. In the action's view they are groups: *"Show a notice 'Hi'"* with its chips.

## 5. Running an action from any process

Today only the DreamPi hook runs actions. The buttons service and the web service need to as well.

- A small base file, `netswitch_actions.py` (Python 2/3, imports only `base_core`), takes over `_module_part()` / `_action()`
  from the hook: `run(action_id, args, ctx)` finds the module's hook file, checks the module is on and the required variables
  are there, calls the function `ACTIONS[id]` with the call, catches and logs errors, and returns the short text of what happened.
- `call` keeps what the switcher's functions use today (`.base_dir`, `.log`, `.raw`, `.number`) and gains `.args` (the variables),
  `.source` (which module and value fired it) and `.value`. Existing hook files keep working unchanged.
- The hook, the web service and the buttons service all call `run()`. Actions work through **files** (as the hook files do today),
  so it doesn't matter which process runs them.

### Actions announced first

| Module | Actions |
|---|---|
| Network switcher | Toggle network, Select DCNow!, Select DCNET (exist) |
| Wi-Fi setup | Start, Stop, Toggle setup |
| Status LEDs | Show LED alert (A, B or C required; seconds optional) |
| Add-on (the base) | Show a notice (text required, seconds optional); Make a box stand out (box required, seconds and a note optional); Change a colour (which and to-what required) |
| Reboot and Update | Check for updates |

Kept out of the first version: Reboot, Start update, Hang up the call, module on/off. A number or a button anyone can use shouldn't
do these yet.

## 6. Every module

| Module | Source of triggers? | Chips look like | Options of its rows | Announces actions? |
|---|---|---|---|---|
| **Special phone numbers** | yes (exists) | `11111` | Hang up | no |
| **Buttons** (new module, owns the pins, takes them out of the switcher's GPIO form) | yes | `Button 1 · short press`, `Button 1 · held 3 s`, `Button 2 · switched on`, `Buttons 1+2 · held` | the button's type and a *Normally closed* checkbox (see 8) | no |
| **DC99 events** | yes | `Event reminder due` | none | no |
| **Online players** | yes | `Favourite game played`, `Favourite player online` | none | no |
| **Reboot and Update** | yes | `Update available`, `Update failed` | none | Check for updates |
| **Network switcher** | no | | | Toggle, DCNow!, DCNET |
| **Wi-Fi setup** | no | | | Start, Stop, Toggle |
| **Status LEDs** | no. Its rows are the other direction (LED messages trigger a look); chips there name the module of the message | | colour, effect, speed, level | Show LED alert |
| **Clock** | not now (a future "at 21:00 on weekdays" fits the same model) | | | no |
| **Debug log, Dreamcast background, About** | no | | | no |

## 7. Defaults (what the install ships)

| Source | Standard bindings | Same as today? |
|---|---|---|
| Phone numbers | `11111` → Select DCNow! (connect) | yes (exists) |
| Buttons | Button 1 closed → Toggle network; Button 1 held 3 s → Toggle Wi-Fi setup | yes |
| Events | Reminder due → Show a notice `{event}` (10 min); → Make the Clock box stand out (10 min); → Make the Events box stand out (10 min) | yes, except that dismissing the banner no longer also ends the highlight |
| Players, Updates | none | yes (today they only light LED messages, which stay built in) |

## 8. Buttons in detail

Buttons (the physical GPIO buttons) are a module like the others: they announce their triggers, have rows, and their chips show up
under the actions in the other modules. The pins and the type are the module's own settings (taken out of the network switcher's
GPIO form). A button has a pin, a **type** and a checkbox:

| Type | Events (chips) | Checkbox |
|---|---|---|
| **Momentary** (a push button) | **Short press** (fires on release, unless the press became a hold), **Held** (3 s) | **Normally closed**: tick it for a contact that is closed at rest and opens when pressed |
| **Toggle** (a switch that stays in its position) | **Switched on**, **Switched off** (the position is applied once when the service starts, as "On = DCNET" does today) | **Inverted**: tick it when "on" is the open position |

So normally-open and normally-closed hardware are handled by one checkbox and the events keep their meaning. Plus the trigger
*Buttons 1 and 2 held together* (replaces the Wi-Fi button assignment). Debounce and hold timing stay hard-wired in the service. Every
event is a chip with an action, shown in the owning module like any other chip; clearing an event removes its chip from both views.
The old `button*_function` and `wifi_button` settings are converted once, on update. Placeholders: `{button}` (which one) and
`{button_event}`.

## 9. What stays hard-wired, and why

- **The call routing, the busy tone, DreamPi's own codes (`*70`)**: they are what the call *is*, not an action.
- **The LED status messages** (about 45 conditions): they show state ("when X is true, light this"), not "when X happens, do Y".
- **Debounce, hold timing, the pull-up repair**: hardware behaviour, not a user choice.
- **Reboot, update start, hang up, module on/off, recording the debug log**: page actions behind the PIN, not offered to triggers yet.

## 10. What changes (when approved)

| Step | Change | Files |
|---|---|---|
| 1 | `netswitch_actions.py` (run from any process); the hook uses it; `call` gets `.args`, `.source`, `.value`; the action announcement gets `params` and `required`, checked by `core.module_actions()` | base, `netswitch_hook.py`, tests |
| 2 | Source announcement (`triggers` in `module.json`), `GET`/`POST /triggers`, the `triggered_by` widget with the source mark; numbers answers the source interface | base, `page/widgets.js`, numbers, switcher `layout.json` |
| 3 | Variables in the row editor; placeholders | `page/widgets.js`, numbers |
| 4 | Actions for Wi-Fi, LED alert, notice, highlight, colour, check for updates | those modules, base |
| 5 | Buttons module (settings, rows, service reads the rows through the interface); conversion of the old settings | new module, `netswitch_buttons.py`, switcher GPIO form |
| 6 | Events, players, updates as sources; the hard-wired banner/highlight become the standard bindings | those modules |

Each step is its own commit with tests, README and `docs/` updated, and the Python 2.7 hook files syntax-checked. Everything that
runs inside DreamPi stays **unverified on hardware** until you try it on a Pi.

## 11. Decisions

Settled:

1. **Momentary buttons**: Short press and Held; a *Normally closed* checkbox (and *Inverted* for toggles) covers the hardware.
2. **Buttons are a module of their own**, working like every other module (section 8).
4. **Placeholders** are announced by the modules that can supply them; only the system and the add-on's are there without modules.
5. **Adding a trigger from the action's side** is allowed (section 3, rule 2).

Settled:

3. **Events: what ends a reminder.** Each action has its own length, so dismissing the banner closes only the banner (choice (a)
   below). Every action that lasts a while (a notice, a highlight, an LED alert) gets a **turn off automatically after** choice of
   type `duration`, from one shared list: **Never** (until dismissed or replaced) and times from 10 seconds to 12 hours (below).
   - The shared list also has the short times (agreed): **Never, 10 s, 30 s, 1 min, 5 min, 15 min, 30 min, 1 h, 3 h, 6 h, 12 h**.
     It is for how long something lasts. The events sync setting keeps its own list (15 min and up): syncing with DC99 every 10
     seconds would be rude.
   - Why it was a question: today one reminder state drives the banner, the highlight of the Clock and Events boxes and the LED message,
     all "until you dismiss it, or 10 minutes after the start". A row is "when X happens, do Y" with no "and undo it when X ends", so
     the three actions can't be switched off together. The alternatives were (b) Events keeps a reminder state that other rows can read
     ("while a reminder is active"), which needs a second kind of trigger and an automatic undo, and (c) keep the events behaviour
     hard-wired.
