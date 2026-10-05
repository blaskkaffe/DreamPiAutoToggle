# Triggers and actions between modules: design proposal

**Status: a proposal for approval. Nothing in "What changes" is built yet.** It builds on what `development` already has (the
numbers rows, `actions` in `module.json`, the `triggers` widget, the LED rows). Back to [CLAUDE.md](../CLAUDE.md).

## 1. What exists today

| Piece | Where | What it does |
|---|---|---|
| `actions` | `module.json` of the switcher | Announces `toggle`, `dcnow`, `dcnet` (id, label, sub-label). `core.module_actions()` lists the actions of the enabled modules as `<module>.<id>`. |
| `hook` | the module's hook file, loaded by `netswitch_hook.py` | `ACTIONS = {"dcnow": fn}`; `fn(call)` runs **inside DreamPi** and gets `.raw`, `.number`, `.base_dir`, `.log`. Python 2/3, works through files. |
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
- The base never imports module code: it calls the source's web entry through the loader (`netswitch_modules.py`), as it does for every `api()`.

## 4. Variables and placeholders

An announced action may declare variables:

```json
"actions": [
  {"id": "notice", "label": "Show a notice", "sub": "A banner on the page",
   "params": [{"key": "text", "label": "Text", "type": "text", "required": true},
              {"key": "seconds", "label": "Seconds", "type": "number", "default": 30}]}
]
```

- `type` is `text`, `number` or `choice` (with `options`). `required` or optional (`default`).
- The row editor draws the fields under the action. A row missing a required variable is marked *incomplete* and skipped
  (logged), never half-run.
- A source can offer **placeholders** to text variables: `{number}` (phone numbers), `{event}` (events), `{player}` / `{game}`
  (players). *"Reminder: {event}"* becomes the event's name.
- Variables belong to the **row** (numbers) or the **binding** (buttons, events), so the same action can appear twice with different
  texts. In the action's view they are groups: *"Show a notice 'Hi'"* with its chips.

## 5. Running an action from any process

Today only the DreamPi hook runs actions. The buttons service and the web service need to as well.

- A small base file, `netswitch_actions.py` (Python 2/3, imports only `netswitch_core`), takes over `_module_part()` / `_action()`
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
| **Buttons** (new module, owns the pins, takes them out of the switcher's GPIO form) | yes | `Button 1 · closed`, `Button 1 · opened`, `Button 1 · held 3 s`, `Buttons 1+2 · held` | the button's type (see 8) | no |
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

A button has a pin and a **type**:

- **Toggle** (a switch that stays in its position): events **Closed** and **Opened**; its current position is applied once when the
  service starts (as the "On = DCNET" functions do today).
- **Momentary** (a push button): events **Short press** (fires on release, unless the press became a hold) and **Held** (3 s). A
  setting *contact: normally open / normally closed* says which level is the rest position, so a normally-closed button works.

Plus the trigger *Buttons 1 and 2 held together* (replaces the Wi-Fi button assignment). Debounce and hold timing stay hard-wired
in the service. Every event is a chip with an action, shown in the owning module like any other chip. Clearing an event removes its
chip from both views. The old `button*_function` and `wifi_button` settings are converted once, on update.

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

## 11. Decisions needed (my recommendation first)

1. **Momentary buttons**: *Short press + Held* with a normally-open/closed setting (recommended: it matches how the buttons work
   today and a hold doesn't also fire a press), or *Closed + Opened + Held* for both types (a hold would also fire Closed).
2. **Buttons as a module of their own** (recommended: the switcher then only announces actions), or keep them in the switcher.
3. **Events**: OK that dismissing the banner no longer ends the highlight (each ends after its own seconds)?
4. **Placeholders** (`{number}`, `{event}`, `{player}`, `{game}`) in text variables: yes?
5. **Adding from the action's side** (section 3, rule 2): should it be allowed, or view and remove only? Allowed is what you described.
