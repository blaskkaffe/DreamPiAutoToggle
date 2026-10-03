# Modules: everything the page shows

Read before adding, removing or restructuring a feature. Back to [CLAUDE.md](../CLAUDE.md).

## The idea

The base is small. It **scans `modules/`**, loads what is there, owns the **theme** (the global colours and the page kit) and the
**three areas** a module can show something in, and **draws the modules' layouts**. Nothing on the page is the base's own
except the frame (header, cog, warning boxes, Settings overlay) and the **module picker** (the loader's own box). Every box,
row and button belongs to a module that says so in a `layout.json`; the base turns that JSON into HTML with its standard widgets
(`page/widgets.js`). A module needs no HTML of its own, and no JavaScript unless it has something the standard widgets can't do.

Services stay as they are for now: the hook inside DreamPi, the buttons service, the LED service and the Wi-Fi service are
base or module Python that runs on its own. Moving each service into its module's folder is planned (see CLAUDE.md, Ideas for later).

## The modules

| Module | Visible in picker | What it shows / does | Default |
|---|---|---|---|
| `switcher` (Network switcher) | no, always on | Dashboard: the Selected-network box (DreamPi, modem, internet, Pi, Hang up) and the two network buttons; Settings: **Network colours** and the **GPIO** rows for the two physical network buttons (`GET`/`POST /buttonconfig`; the buttons service itself is base); `POST /dcnow`, `/dcnet`, `/hangup`, `GET /status`; the page's primary colour follows the selected network | on |
| `system` (System) | no, always on | Settings > **About**: the versions (`GET /about`) and the GitHub link | on |
| `players` (Online players) | yes | Dashboard: the Online players box (counts, games carousel, player list, sources, links), `GET /players` | on |
| `numbers` (Special phone numbers) | yes | Settings: the phone numbers table, `GET`/`POST /numbers`, `numbers.json` (the hook only reads it while the module is on) | on |
| `led` (Status LEDs) | yes | Settings: the LED row in GPIO (count, wire order, pin: `GET`/`POST /ledhardware`) and the **Status LED** box (calibration pop-up and message table, a custom widget: `GET`/`POST /ledconfig`); the LED service | on |
| `debuglog` (Debug log) | yes | Dashboard: the Debug log bar with the live log; `GET /log`, `/dtmf`, `POST /debug`, `/clearlog`; the part inside DreamPi (`netswitch_hookdebug.py`) | **off** |
| `wifi` (Wi-Fi setup) | yes | Settings: the Wi-Fi setup row and network list in System, the hold-button row in GPIO; `POST /wifitoggle`, `/wificonnect`, `GET`/`POST /wifibutton`; its own service `dreampi-netswitch-wifi` | **off** |
| `rebootupdate` (Reboot and Update) | yes | Settings: the Updates rows (check, Update now, log) and the Reboot row, all in System; `GET /update`, `POST /update/check`, `/update/start`, `/reboot` | on |
| `background` (Dreamcast background) | yes | A fullscreen **background**: the animated scene and the translucent box styling; `GET /background/*.js` | **off** |

A module is **installed** when its folder (with a `module.json`) is there, and **enabled** when the picker has it on (`modules.json` in
`/opt/dreampi-netswitch`: `{"led": true, ...}`; a module without an entry uses `enabled` from its manifest; a module that is not
visible in the picker is always on). Not installed or not enabled = absent: no layout, no endpoints (404), no service work.
`core.module_manifest()`, `module_names()`, `module_enabled()`, `module_visible()`, `save_module_enabled()` are the one place that knows.

## A module folder

```
modules/<name>/
  module.json      {"name", "description", "enabled", "visible"}  + optional "web", "ui", "order", "colours", "colours_unique", "primary", "note"
  layout.json      what it shows (below); a module with only a web entry or only a background may differ
  netswitch_*.py   its Python: the web entry named in "web", plus anything its services use
  page.js          optional: custom widgets, hooks, a background (runs in the page's script after the base scripts)
  page.css         optional: only for what the page kit has nothing for (see the kit rules below)
  *.html           optional: markup of a custom widget (layout.json: "html_file")
  install.sh       optional, sourced by install.sh (sees $DEST $SRC $LED_COUNT $LED_GPIO $WIFI $WIFI_DEMO, ns_module_enable)
  remove.sh        optional, sourced when the folder is gone from the repo, and by uninstall.sh
```

### module.json

| Key | Meaning |
|---|---|
| `name` | the title in the picker (older files: `title`) |
| `description` | the text under it in the picker |
| `enabled` | on when first loaded; what the user sets in the picker (`modules.json`) overrides it (older files: `default`) |
| `visible` | `false` = always on (no switch in the picker, which still lists it so it can be moved) (the network switcher: it can't be removed); default `true` |
| `web` | Python module name of its web entry (routes, `api()` hook) |
| `ui` | the page kit version it was written for (now 2); a module for a newer kit is not loaded |
| `order` | where it starts out in the list until the user moves it (the picker order, `module_order.json`, replaces it) |
| `colours` | `{"dcnow": "orange", ...}`: colours the module picks from the global palette (below); `colours_unique: true` = no two keys share one |
| `primary` | the palette id (or one of its own colour keys) it uses as its primary colour; it may change it while running (below) |
| `note` | an optional second line in the picker |
| `toggle_box` | a Settings box name (`"appearance"`): the page gets a row with this module's on/off switch in that box, even while the module is off (it has no layout of its own then); the Dreamcast background uses it |

The picker is one **Modules** row at the top of the **System** box with an **Edit** button. Edit opens a pop-up (as wide as every pop-up: the card between its paddings) that lists **every** module in priority order, the always-on ones too: each row has a switch (the always-on ones say "Always on" instead, they can be moved but not switched off) and a **drag handle** (⋮⋮). **Nothing is applied while it is open**: ticking a switch or moving a row only changes the list; **Done** (or Esc, or a click outside) saves the order (`POST /modules/order`) and the switches (`POST /modules`) and builds the page again with Settings still open. To move a row, drag it by its handle (mouse, finger or pen; the other rows make room, Esc cancels, and near the edge Settings scrolls along), or focus the handle and use the up / down arrow keys (the order is stored in `module_order.json`). The drag is the standard `sortable()` in `page/widgets.js`: it uses pointer events with `touch-action: none` on the handle, and it never takes the grabbed row out of the page (the neighbours move instead), because iOS Safari ends a touch whose element is re-inserted. **The order is the priority**: the module at the top comes first inside shared boxes, names a box
first, sets the page's primary colour and wins when two backgrounds compete. Applying a change reloads the page.
A folder that is new to the picker starts at its `order` hint among the ones not yet placed.

## layout.json

```json
{ "dashboard": [ BOX, ... ],
  "settings":  [ BOX, ... ],
  "data":      { "players": {"url": "/players", "every": 60, "retry": 2, "retry_if": "retry"} } }
BOX = { "box": "gpio", "title": "GPIO", "items": [ WIDGET, ... ] }
```

or, for a **background module**, only `{"background": {"type": "fullscreen"}}` (see Backgrounds). The loader checks it
(`netswitch_modules.read_layout()`); a layout with an unknown widget, section or key keeps its module out, and the reason shows as a
warning box on the page (and in the picker).

**Areas.** `dashboard` is the main page, `settings` the Settings overlay, `background` what is drawn behind everything. **One module can make any number of boxes in both `dashboard` and `settings`**, each with any mix of widgets. The network switcher is one module: a dashboard box `network` (one expandable `infobox` widget plus two `button` widgets) and a settings box `network colours`; the LED module is one module with the `gpio` box (its LED row) and the `status led` box.

**Box names (best practice).** Not enforced by code, but use the same names for the same kind of thing, so modules land in the box the user expects and share it instead of adding a box each (a module's own feature gets a box named after it, like `special phone numbers` or `status led`):

| Box | Put here | Used by now |
|---|---|---|
| `system` | things that act on the Pi or the add-on: Wi-Fi setup, updates, reboot | wifi, rebootupdate |
| `about` | read-only information: versions, hardware, links | system |
| `gpio` | anything wired to a GPIO pin: button functions, the LED pin, hold buttons | switcher, led, wifi |
| `configuration` | a module's general settings that fit no other box; a module with only a few settings adds them here instead of making its own box | (none yet) |
| `appearance` | colours and the look of the page | switcher (the DCNow! / DCNET colour pick), background (its switch, see `toggle_box`) |
| `network` | (dashboard) the network selection and its status | switcher |

The default order puts **About** and then **System** at the very bottom of Settings (the system module starts out before wifi and rebootupdate in the list, and the module picker is a row inside System), and the Reboot row is the last row of System. Use the same title for the same box everywhere (`System`, `About`, `GPIO`, `Configuration`): the first module in picker order that gives one names it. Lower-case in `layout.json`, as the box id.

**Boxes are shared by name.** Boxes with the same `box` name (case-insensitive) in any modules are **one box**: their items follow each
other in picker order (the items of one module keep their order). The box's title is the first non-empty `title` in picker order, so a
module that only adds rows leaves it out. Boxes appear in order of first appearance. Example: `switcher`, `led` and `wifi` all
declare `gpio`; the page shows one GPIO box with Button 1/2 (the switcher's), the LED row and the Wi-Fi button row. A settings box is a titled card
(`<h2>` with a "Saved ✓" flash that any saving widget in it triggers); a dashboard box has no frame, its widgets stand directly on the page.
A box whose widgets are all hidden (the LED settings while the LED count is 0) is hidden too.

**Bindings.** A string value that starts with `@` is read from the page's state `S` and the widget follows it live:
`"@modem.text"`. `S` is the latest `/api` answer plus one entry per data source (`S.players`). Anything else is literal. Most
text-like properties accept a binding (`text`, `title`, `sub`, `label`, `confirm`, `disabled`, `show`, `hide`, `items`, `lines` ...);
`show` / `hide` on any widget bind to a truthiness. A newline in a text makes a line break.

**Colour references.** A colour in a layout is a palette id (`"orange"`), one of the module's own colour keys (`"dcnow"`) or
`"module.key"` of another module (`"switcher.dcnow"`, which the Online players box uses so its counts follow the user's choice).

**Data sources** (`"data"`): `{"url", "every" (seconds, default 60), "retry" (seconds, default 2), "retry_if" (a field of the answer; ask
again after `retry` while it is true), "when": "settings" (only while Settings is open)}`: the page GETs the url into `S.<name>`
(also after every button POST, and again after `retry` if a request fails). Names are global: the first module to ask for one keeps it.

### The standard widgets

| Type | What it is | Main properties |
|---|---|---|
| `text` | a paragraph | `text`, `muted`, `cls` |
| `row` | a Settings row: title and grey subtitle on the left, a widget on the right | `title`, `sub`, `control` (a widget), `below` (widgets under the row, full width) |
| `button` | `style` `"small"` (default round button), `"pill"` (big, in the primary colour), `"danger"` | `label`, `post` (a POST to this path), `body`, `colour` (pill: a colour reference), `confirm` (asks first), `pin` (asks for the PIN when one is set), `arm` (text shown on the first tap; a second tap within 4 s does it), `busy` + `busy_label`, `disabled`, `href` (a link instead of a POST), `aria`, `then` (`"reload"`, or `"wait"` = wait until the Pi is back, for a reboot) |
| `toggle` | a tick box | `bind` + `post` (POSTs `{"value": bool}`), or `module` (a module's own switch: follows `@enabled.<name>` and POSTs `/modules`, then the page is built again), or `local` (kept in the page only, `default`), `text` (label beside it), `look` (`"neutral"` default, `"pri"`) |
| `swatches` | a small **Colour** button in the currently chosen colour; it opens a pop-up with the 16 palette colours (two rows: normal, bright) and a pick is stored for the module (and closes it) | `key` (one of the module's `colours` keys), `label` (default "Colour"), `title` (the pop-up's heading); use it as a `row`'s `control` |
| `link` | a link that looks like a small button | `label`, `href`, `aria` |
| `form` | one **edit row** per field (title, a grey line, an **Edit** button on the right, and a list of tags under it when the field has one); the field's controls are in a pop-up that the button opens (the pop-up has a **Done** button) | `get`, `post`, `fields`: `[{"title", "sub" (a fixed line) or "sub_text": key into the reply's `texts`, "list": key into the reply's `lists`, "button" (default "Edit"), "show", "controls": [{"type": "select"/"number"/"text"/"toggle", "key", "options": name or list, "min", "max", "label" (shown in the pop-up)}]}]`; `GET` answers `{"values": {...}, "options": {name: [{"value", "label", "group"}]}, "texts": {key: "ready-made line"}, "lists": {key: [...]}}`, `POST {"values": {...}}` saves and answers the same, with the lines recomputed (so "GPIO17 toggles ..." is written in Python, not in the page). Changes save 250 ms after the last one. |
| `infobox` | the tap-to-open status box | `label`, `title` or `parts` (`[{"text", "colour"}]`), `rows`: `[{"label", "main" (always visible), "show", "value": widget}]`, `actions` (widgets shown when open), `actions_show` |
| `status` | a dot and text, for infobox rows | `dot` (a state: `ok busy warn bad off call`, or a LED look `{color, effect, speed}`), `text`, `sub`, `lines` (first line + smaller ones) |
| `expander` | a wide bar that opens a block (the Debug log) | `label`, `items` |
| `bar` | widgets side by side | `items` |
| `carousel` | one line that scrolls round, like a ticker, only when it doesn't fit; while it fits it stands still and is centred | `items` (list, joined with a bullet) or `text` |
| `picker` | a table to pick values for: one edit row per group (title, grey line, **Add** button; the items are listed as removable tags under the row once there are any), with **Restore** and an **(i)** information button (pop-up with `rules.help`) at the bottom (the phone numbers; the LED message table will follow it) | `source`: `GET` answers `{"groups": [{"key", "label", "sub", "items": [...]}], "defaults": {key: [...]}, "rules": {"min", "max", "per_group", "allowed" (characters, regex class syntax), "unique", "add_label", "add_title", "min_msg", "help", "restore"}}`, `POST {key: [...]}` saves and answers the same |
| `list` | a list from the server, each row with a button that opens a small form (the Wi-Fi networks), or compact rows with a coloured tag (the players) | `items`, `row` (`title`, `sub`, `button` or `tag` / `tag_colour` field names), `style` (`"compact"`), `empty`, `when`, `extra` (fixed rows after the list: `title`, `sub`, `button`, `item`), `popup` (`title`, `title_other`, `fields` `[{key, label, type, show_if, required, blank}]`, `submit`, `busy`, `post`, a PIN is asked for when one is set) |
| `links` | a row of text links | `items`: `[[label, url], ...]` |
| `console` | lines of text | `lines` (binding: replaces all) or `tail` (url; `GET url?from=N` answers `{"text", "size", "reset"}`), `rules` (`[[regex, "l-err"], ...]`, first match wins), `nowrap`, `height`, `follow`, `active`, `hide_empty`, `label` |
| `info` | a read-only table of name / value pairs | `rows` (binding) or `source` (a url, fetched when Settings opens, `[[name, value], ...]`) |
| `custom` | a box of the module's own | `name`, `html` or `html_file` (a file in the module folder), `cls` |

**The edit row** is the one look for a setting that has a button: `editRow()` in `page/widgets.js` (title and grey line on the left, a small button on the right, an optional tag list underneath that takes no room while it is empty). The `form` widget, the `picker` and the colour pick (`row` + `swatches`) are all made of it, so Appearance, GPIO and Special phone numbers look alike; use `form` or `picker` rather than building a row by hand.

A **custom widget** is registered by the module's `page.js`: `custom("led-messages", function(host, ctx){ ... })`. The page calls
it after the whole layout is in the document, so it can look its elements up by id; `host` is the element holding the markup,
`ctx.saved()` flashes the box's "Saved ✓", `ctx.mod` is the module name. Pop-ups inside it use `ui.popup(el)` (below). Use a custom widget only for what no standard widget does
yet; a new widget that two modules could use goes into `page/widgets.js` instead (plus `WIDGETS` in `netswitch_modules.py`; a test keeps the two lists equal).

### Backgrounds

A module with `{"background": {"type": "fullscreen" | "part", "position": "top" | "bottom"}}` is a **background module** and can have
**nothing else** (no boxes, no data): it is the only kind of module that draws behind the boxes. The page walks the enabled background modules in
picker order: the first one is drawn; if it is `fullscreen` nothing below it is (and its script isn't even sent); if it is `part` (a
taskbar-like strip or a logo that only fills an area; `position` pins it to the top or bottom, the module sets its height) the next one is drawn too.
The module's `page.js` calls `background("<module name>", function(host, spec){ ... })` and draws into `host`
(a div in the page's `#bg` layer). The Dreamcast background is the fullscreen one; it also restyles the boxes (a theme, the one place a module's CSS may restyle base classes).

### Web entry

The module named in `"web"` may define:

- `GET = {"/path": fn(handler)}` and `POST = {...}`: exact paths. `fn` answers with `handler.send(body, ctype, status=200)`; a POST function returns `True` once it has answered (else the web service sends 204 / 303). `handler._body(limit)` reads the request body.
- `api(d, warnings)`: called for every `GET /api`, in picker order; add keys to the answer dict `d` (what the module's widgets bind to: put ready-to-show texts here, not logic in the page) and lines to `warnings` (the warning boxes). A hook should not depend on another module's keys (the LED module sets `d["dreampi"]["look"]`, the switcher adds the rest with `setdefault` rules).
- `PROTECTED = ("/path", ...)`: POST paths of this module that run as root (reboot, update, joining a network): they need the PIN when one is set.

POSTs pass the same security gate as every other POST (Origin / `X-Requested-With`); only paths a module lists in `PROTECTED` need the PIN: `/reboot`, `/update/start` and `/wificonnect`. A module that is off has no protected paths at all, because it has no routes. Unknown paths answer 404.

## Colours and the theme

The base owns the theme. **One global palette of 16 named colours** (`core.PALETTE`, a terminal's 16 as 8 hues × normal / bright: red, orange, yellow, green, cyan, blue, purple, pink and `bright-` each) with a page colour, a lighter variant for borders and the LED's own tuning. The page gets them as CSS variables (`--c-<id>`, `--c-<id>-l`, `-rgb` triples) and a class `.c-<id>` that makes an element and everything inside it use that colour as its `--primary`.

- A module **never writes a colour of its own**. It names palette ids in `module.json` `"colours": {"dcnow": "orange", "dcnet": "blue"}` — defaults the user changes in the module's own settings (`swatches` widget, `POST /colour`, kept in `colours.json`; `core.module_colours(name)`, `core.set_module_colour()`; with `colours_unique` picking the other key's colour swaps the two). `/api` carries `colours` (`{module: {key: id}}`) so every device follows.
- A module also has a **primary colour**: the one used on its borders and primary buttons. It is set statically (`"primary"` in `module.json`: a palette id or one of its own colour keys) or while running through its `api()` hook (`d["primary"][name] = id`). The network switcher does the second: its primary is the selected network's colour. Each box and widget takes the primary of its own module (a `.c-<id>` class); the top module in picker order that has a primary also sets the page's. **A lower module that picks another colour only uses it for itself.**
- `core.network_colour("dcnow"|"dcnet")` is what the LED service and the status dot ask for (the switcher's picks, orange / blue without it). The LED messages for the networks store the tokens `"dcnow"` / `"dcnet"` as their colour.

## The page kit (what is left for a module's own CSS and JS)

A module does not decide how things look. The base page (`page/page.css`, the block marked "The page kit", `ui` in `page/page.js` and the widgets in `page/widgets.js`) provides the building blocks, so a change there changes every module. `ui.version` and `UI_KIT` in `netswitch_modules.py` are its version (now 2); a module's `"ui"` says which it was written for.

- Layout, rows, buttons, forms, boxes, tables, lists, consoles, colour pickers: the widgets above, nothing else needed.
- **Pop-ups** inside a custom widget: an element in a card (`<div class="t">Title</div> ... <div class="msg"></div>`; `fld` puts an input and a button on one line, `bar` / `bar end` / `bar center` lay out buttons, `big` makes it wider) and `var p = ui.popup(el)`; `button.onclick = function(e){ p.toggle(this, e) }`, `p.close()`, `p.onclose`. It moves into its card the first time it opens. Esc, a click elsewhere, opening another pop-up and closing Settings close it.
- **CSS classes** for a custom widget's markup: `srow` (+ `wrap`, `below`), `pill-s` (+ `danger`), `cbox` (+ `neutral`), `select.ord`, `tags` / `tag`, `range` (+ `grid`), `console` (+ `nowrap`; line classes `l-err l-ok l-dim l-hd l-info l-warn l-mod l-b`), `msg`, `empty`, `sub`.
- **Hooks** (`hook(name, fn)` / `fire(name, arg)` in `page/page.js`): `api` (d, every second), `settingsOpen`, `settingsClose`, `escape` (return `true` if handled), `posted` (after a button's POST), `layout` (a box changed size), `expand` / `collapse` (an expander).

Rules (`tests/test_ui_kit.py` checks them): a module's `page.css` does not style a base class on its own (`.srow{...}` would change every row; `#my-list .srow{...}` and the module's own class names are fine), does not write colours as `#hex` (except white and black), and its `page.js` does not write `.srow` markup or open pop-ups by hand. The LED message table keeps its CSS in its own `page.css` until it moves to a standard table; a theme such as the Dreamcast background restyles base classes on purpose and is the one exception. To add something new that two modules could use, add it to the kit (CSS, widget, this table, a test) instead of to a module.

## The loader (`netswitch_modules.py`)

`refresh()` runs for every request (`netswitch_web.refresh_page()`): when the signature (mtimes of the module folders, `modules.json`, `module_order.json`, `colours.json`, the base page files) changed, it checks every enabled module (`ui` version, `layout.json`), imports the web entries, collects routes and `api` hooks and the web service builds the page again: **adding or deleting a module folder, editing its files, switching or moving it in the picker takes effect on the next page load**, without restarting the web service. A module whose layout or Python is broken is skipped and reported (`errors()`: a warning box, and in the picker). `layout()` merges the layouts (`window.LAYOUT` in the page); `page_parts()` returns the modules' `page.css` / `page.js` (a background module that isn't drawn is left out); `live_colours()` feeds `/api`.

`GET /modules` lists the visible modules with `enabled`; `POST /modules {"name", "enabled"}` switches one; `POST /modules/order {"order": [names]}` moves them. Both need the page's own request header, and both reload the page.

The page itself (`page/`): `index.html` is only the frame (`#bg`, header, `#warnings`, `#dash`, the Settings overlay with `#set-boxes`); `page.js` the kit, hooks and `/api` loop; `widgets.js` the layout engine and the widgets; `boot.js` draws the layout and starts the loop last.

## Services and the installer

- The **LED service** (`dreampi-netswitch-led`, `modules/led/netswitch_led.py`) drives `ledconfig.led_count()` LEDs while the module is on and **0 (closed, dark) while it is off** (`wanted_count()`), so the picker needs no systemctl. Its unit has `ConditionPathExists=` for its files, so deleting the folder from `/opt/dreampi-netswitch` makes systemd skip it quietly.
- The **buttons service** is base and loads no module code. While the Wi-Fi module is on, a hold only touches `wifi_start` / `wifi_stop` (the same files the page's button touches). The **Wi-Fi service** (`dreampi-netswitch-wifi`, written by the module's `install.sh`, removed by its `remove.sh`) idles until a start request, runs `setup_cycle()`, and treats switching the module off mid-setup as a stop.
- `install.sh` `sync_modules`: copies every `modules/*/` that has a `module.json` to `$DEST/modules/` (replacing the old copy as a whole); a folder that was installed before but is gone from the repo gets its `remove.sh` run and is deleted. Then every installed module's `install.sh` is sourced (the LED one writes its unit and handles SPI for GPIO10; the Wi-Fi one handles `--wifi` / `--no-wifi` / `--wifi-demo`). It also copies the base page files (`index.html`, `page.css`, `page.js`, `widgets.js`, `boot.js`).
- To **remove a module for good**: delete its folder in the folder you installed from and run `sudo ./install.sh` (its service and files go; its settings files like `led.json`, `led_count`, `numbers.json` stay for when it comes back). To **add one**: put the folder in and run the installer. To only hide it: switch it off in Settings > System > Modules.

## Adding a new module

Make `modules/<name>/` with a `module.json` (`name`, `description`, `enabled`, `visible`, `ui: 2`), a `layout.json` with its boxes, and a web entry for its endpoints and `api()` texts (`"web"`). Put the texts the widgets show in `api()` (or in the reply of a data source), not in JavaScript. Add it to `NAMES` / `ENDPOINT` in `tests/test_modules.py` so the "every module can be removed or switched off alone" tests cover it, and a view test (`tests/test_module_views.py`) for what it hands to the widgets. Add an `install.sh` / `remove.sh` if it has a service. If you need a widget the base lacks, add it to `page/widgets.js` (and the kit, docs, a test) rather than a one-off in the module.

## Tests

`tests/test_module_picker.py` (manifest keys, visible, order, the picker's HTTP), `tests/test_layout.py` (boxes shared by name, picker order, backgrounds, validation, data sources, primary colours), `tests/test_network_colours.py` (the palette, module colours, the primary following the network), `tests/test_module_views.py` (the texts and lists the modules hand to the widgets), `tests/test_modules.py` (the modules well formed; the page and endpoints with everything on; with nothing (the base alone, JS syntax-checked with node); each module deleted alone and switched off alone and back while the web service keeps running; a broken module; a new folder picked up; the services following the picker; the installer's `sync_modules` on temp folders; layering), `tests/test_ui_kit.py` (the kit rules, the loader and page agreeing on the widget list). `sh tests/ui/run.sh` (optional, needs Chromium) audits the page at four widths and runs `tests/ui/functional.js`, which drives the real page: network switching and its primary colour, the colour pick, the numbers table, a saving form, moving and switching modules, the debug log.
