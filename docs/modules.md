# Modules: everything the page shows

Read before adding, removing or restructuring a feature. Back to [CLAUDE.md](../CLAUDE.md).

## Base and project (the base is reusable)

`base/` is a framework that knows no project: `base_core.py` (paths from `project.json`, the module state, the palette and its editor's logic, the theme and screen settings, the PIN lock, `service()` / `module_announcements()`), `base_modules.py` (the module loader), `base_web.py` (HTTP), `base_security.py`, `base_tz.py`, `layout.json` (the base's own Settings boxes: Appearance with the palette editor, screen layout, theme, PIN, and the Global colours box) and `page/`. `project.json` (name, page title, data folder, `/tmp` prefix, service name, host name, icons) is the only place the project names itself; everything that is the project (the check-in board, the contacts, the clock ...) is a module. `tests/test_base_neutral.py` fails when a project word gets into `base/`. The base's Settings boxes come before the modules' boxes (Appearance, Global colours, then the modules in picker order, System last).

The rules that keep it so:

- **A module owns its code and its state files.** It defines its own path constants from `core.BASE_DIR` / `core.TMP_PREFIX` (never in `base_core.py`); `tests/support.py` imports every module file and `sandbox()` redirects all of those paths into a temp dir.
- **Modules never import each other.** A module that needs another's state reads that module's **file** (its documented format) or asks `/api`: the check-in board reads `contacts.json` and the photos folder, the contacts module's files.
- **What many modules fill together goes through the base**: `core.module_announcements(key)` (module.json lists), `modules.collect("about_rows")` (each module's `about_rows()` adds rows to the About table) and `core.service(name)` (a module's web entry lists `SERVICES = {"name": fn}`; the base calls it while the module is on).
- **The base never imports module code** and never names a module.

## The idea

The base is small. It **scans `modules/`**, loads what is there, owns the **theme** (the global colours and the page kit) and the
**three areas** a module can show something in, and **draws the modules' layouts**. Nothing on the page is the base's own
except the frame (header, cog, warning boxes, Settings overlay) and the **module picker** (the loader's own box). Every box,
row and button belongs to a module that says so in a `layout.json`; the base turns that JSON into HTML with its standard widgets
(`base/page/widgets.js`). A module needs no HTML of its own, and no JavaScript unless it has something the standard widgets can't do.

There is no service besides the web service; a module that needs one writes its unit in its `install.sh` and lists it in `NS_SERVICES`.

## The modules

| Module | Visible in picker | What it shows / does | Default |
|---|---|---|---|
| `checkin` (Check-in board) | yes | Dashboard: the **board**, one `roster` widget over `@checkin` (the whole board, in every `/api` answer): a button per person, or a box per group; Settings: the **Check-in board** box (look, grouping, colouring, the colour of each department / building, All in / All out); see [checkin.md](checkin.md) | on |
| `contacts` (Contacts) | yes | Settings: the **Contacts** box (the count, a CSV file or pasted text to import, Export); `GET /contacts`, `/contacts.csv`, `POST /contacts/import`, `POST /contacts/photo`, `GET /contacts/photo/<id>`; the roster is `contacts.json`, which the check-in board reads | on |
| `imagebg` (Background image) | yes | A fullscreen **background** (a fixed picture layer and a black layer that darkens it, drawn from `/api` `imagebg` {has, fit, dim, version}) **and** a settings box `background-image`: the custom widget `imagebg-pick` (Choose / Remove, a thumbnail; a big picture is shrunk in the browser first) and a form for Fit and Darken. `GET /imagebg`, `POST /imagebg`, `POST /imagebg/upload` (the picture as the body, at most 8 MB, type decided by its first bytes: PNG, JPEG, GIF, WebP), `POST /imagebg/remove`, `GET /imagebg/image?v=`; files `background_image`, `imagebg.json` | **off** |
| `system` (System) | no, always on | Settings > **About**: the versions (`GET /about`) and the GitHub link | on |
| `clock` (Clock) | yes | Dashboard: the Clock box, an `infobox` (`@clock.beat` top line, `@clock.time` middle, a carousel of `@clock.items` at the bottom, hidden while the box is open; open, a `list` (`"style": "grid"`, two or more cities on a row) over `@clock.cities` and the kit's `worldmap` widget draw the time zone map: a hand-drawn outline of the land (`WORLD_LAND` in `base/page/widgets.js`) on 24 bands, the hour of each band on top, its UTC offset below, a dot per city and a **white dot** for the clock's own place (`@clock.map.dot`, from `clock.here()`: the city of the zone in the catalogue, or the middle of the band of the zone's winter offset); the highlighted band is the one that place is in (summer time does not move it) and shows the clock's own hour (`@clock.map.here`); the box has `"title_rows": "@clock.size"` (the large clock: `"full"`, `"upper"`, `"lower"` = how many of the three rows the time takes) and `"open_if": "@clock.world"` (nothing to open without world time); Settings: Time format as a `choice` (`12h`, `12h-ampm`, `24h`; a form, `GET`/`POST /clock`), switches for .beat (`POST /clock/beat`), world time (`POST /clock/world`) and Large clock (`POST /clock/large`), the Cities picker as an Edit pop-up (`GET`/`POST /clock/cities`, up to 12 from `base_tz.CITIES` as the group's `choices`); the time zone is the common one (`core.time_zone()`), its colour (`colours: {"clock"}`, a swatch row in Appearance; `api()` sets its primary), `clock.json` (`clock_mode` of older versions is read once; the zone it once held is carried over to `time_zone`). Offsets with summer time come from `netswitch_tz` (base) | on |
| `rebootupdate` (Reboot and Update) | yes | Settings: the Updates rows (check, Update now, log) and the Reboot row, all in System; `GET /update`, `POST /update/check`, `/update/start`, `/reboot` | on |

A module is **installed** when its folder (with a `module.json`) is there, and **enabled** when the picker has it on (`modules.json` in
`/opt/checkin-board`: `{"led": true, ...}`; a module without an entry uses `enabled` from its manifest; a module that is not
visible in the picker is always on). Not installed or not enabled = absent: no layout, no endpoints (404), no service work.
`core.module_manifest()`, `module_names()`, `module_enabled()`, `module_visible()`, `save_module_enabled()` are the one place that knows.

## A module folder

```
modules/<name>/
  module.json      {"name", "description", "enabled", "visible"}  + optional "web", "ui", "order", "colours", "colours_unique", "primary", "note"
  layout.json      what it shows (below); a module with only a web entry or only a background may differ
  <name>_web.py     its Python: the web entry named in "web", plus anything its services use
  page.js          optional: custom widgets, hooks, a background (runs in the page's script after the base scripts)
  page.css         optional: only for what the page kit has nothing for (see the kit rules below)
  *.html           optional: markup of a custom widget (layout.json: "html_file")
  install.sh       optional, sourced by install.sh (sees $DEST $SRC, ns_module_enable)
  remove.sh        optional, sourced when the folder is gone from the repo, and by uninstall.sh
```

### module.json

| Key | Meaning |
|---|---|
| `name` | the title in the picker (older files: `title`) |
| `description` | the text under it in the picker |
| `enabled` | on when first loaded; what the user sets in the picker (`modules.json`) overrides it (older files: `default`) |
| `visible` | `false` = always on (no switch in the picker, which still lists it so it can be moved) (the About box: it can't be removed); default `true`. The picker lists a module whenever it has a dashboard box, a settings box or a background (`base_modules.shows_something()`, also while it is off) or is `visible`; only a plain service with none of them is left out |
| `web` | Python module name of its web entry (routes, `api()` hook) |
| `ui` | the page kit version it was written for (now 2); a module for a newer kit is not loaded |
| `order` | where it starts out in the list until the user moves it (the picker order, `module_order.json`, replaces it) |
| `colours` | `{"checkin": "green", ...}`: colours the module picks from the global palette (below); `colours_unique: true` = no two keys share one |
| `primary` | the palette id (or one of its own colour keys) it uses as its primary colour; it may change it while running (below) |
| `note` | an optional second line in the picker |
| `toggle_box` | a Settings box name (`"appearance"`): the page gets a row with this module's on/off switch in that box, even while the module is off (it has no layout of its own then); useful for a background-only module |

The picker is one **Modules** row at the top of the **System** box with an **Edit** button. Edit opens a pop-up (as wide as every pop-up: the card between its paddings) that lists **every** module in priority order, the always-on ones too: each row has a switch (the always-on ones say "Always on" instead, they can be moved but not switched off) and a **drag handle** (⋮⋮). **Nothing is applied while it is open**: ticking a switch or moving a row only changes the list; **Done** (or Esc, or a click outside) saves the order (`POST /modules/order`) and the switches (`POST /modules`) and builds the page again with Settings still open. To move a row, drag it by its handle (mouse, finger or pen; the other rows make room, Esc cancels, and near the edge Settings scrolls along), or focus the handle and use the up / down arrow keys (the order is stored in `module_order.json`). The drag is the standard `sortable()` in `base/page/widgets.js`: it uses pointer events with `touch-action: none` on the handle, and it never takes the grabbed row out of the page (the neighbours move instead), because iOS Safari ends a touch whose element is re-inserted. **The order is the priority**: the module at the top comes first inside shared boxes, names a box
first, sets the page's primary colour and wins when two backgrounds compete. Applying a change reloads the page.
A folder that is new to the picker starts at its `order` hint among the ones not yet placed.

## layout.json

```json
{ "dashboard": [ BOX, ... ],
  "settings":  [ BOX, ... ],
  "data":      { "contacts": {"url": "/contacts", "every": 20, "when": "settings"} } }
BOX = { "box": "system", "title": "System", "items": [ WIDGET, ... ] }
```

or, for a **background module**, only `{"background": {"type": "fullscreen"}}` (see Backgrounds). The loader checks it
(`base_modules.read_layout()`); a layout with an unknown widget, section or key keeps its module out, and the reason shows as a
warning box on the page (and in the picker).

**Areas.** `dashboard` is the main page, `settings` the Settings overlay, `background` what is drawn behind everything. **One module can make any number of boxes in both `dashboard` and `settings`**, each with any mix of widgets. The network switcher is one module: a dashboard box `network` (one expandable `infobox` widget plus two `button` widgets) and a settings box `network colours`; the LED module is one module with the `gpio` box (its LED row) and the `status led` box.

**Box names (best practice).** Not enforced by code, but use the same names for the same kind of thing, so modules land in the box the user expects and share it instead of adding a box each (a module's own feature gets a box named after it, like `check-in` or `contacts`):

| Box | Put here | Used by now |
|---|---|---|
| `system` | things that act on the computer or the add-on: updates, reboot | rebootupdate |
| `about` | read-only information: versions, hardware, links | system |
| `check-in` | the check-in board's own settings (grouping, colours) | checkin |
| `configuration` | a module's general settings that fit no other box; a module with only a few settings adds them here instead of making its own box | (none yet) |
| `appearance` | the module's own colour pick (`swatches` row with `"tint": true`) and the look of the page | checkin, clock |
| `colours` (**Global colours**) | colours more than one module uses, which a module announces by adding a row here; others pick them by name (`"global"`) | system (Global main, Notification highlight) |
| `contacts` | the people the board is built from | contacts |

**The picker order is grouped** (`core.module_group()`, applied by `core.module_names()`, so it holds for the Modules list, the boxes and the priorities alike): first the modules with a dashboard box, then the settings-only ones, then the backgrounds; a module moves inside its group. Moving the tiles of the main screen (Settings > Appearance > Rearrange the main screen) reorders the dashboard group. **System is always the last box of Settings**, whatever the module order (the loader sorts it last); the default order also puts **About** just above it. The default order puts **About** and then **System** at the very bottom of Settings (the system module starts out before rebootupdate in the list, and the module picker is a row inside System), and the Reboot row is the last row of System. Use the same title for the same box everywhere (`System`, `About`, `Appearance`): the first module in picker order that gives one names it. Lower-case in `layout.json`, as the box id.

**Boxes are shared by name.** Boxes with the same `box` name (case-insensitive) in any modules are **one box**: their items follow each
other in picker order (the items of one module keep their order). The box's title is the first non-empty `title` in picker order, so a
module that only adds rows leaves it out. Boxes appear in order of first appearance. Example: if `rebootupdate` and a module of your own both
declare `system`, the page shows one System box with the Updates and Reboot rows and the rows of the other module. A settings box is a titled card
(`<h2>` with a "Saved ✓" flash that any saving widget in it triggers); a dashboard box has no frame, its widgets stand directly on the page.
A box whose widgets are all hidden is hidden too.

**Bindings.** A string value that starts with `@` is read from the page's state `S` and the widget follows it live:
`"@checkin.text"`. `S` is the latest `/api` answer plus one entry per data source (`S.contacts`). Anything else is literal. Most
text-like properties accept a binding (`text`, `title`, `sub`, `label`, `confirm`, `disabled`, `show`, `hide`, `items`, `lines` ...);
`show` / `hide` on any widget bind to a truthiness. A newline in a text makes a line break.

**Colour references.** A colour in a layout is a palette id (`"orange"`), one of the module's own colour keys (`"checkin"`) or
`"module.key"` of another module (`"clock.clock"`).

**Data sources** (`"data"`): `{"url", "every" (seconds, default 60), "retry" (seconds, default 2), "retry_if" (a field of the answer; ask
again after `retry` while it is true), "when": "settings" (only while Settings is open)}`: the page GETs the url into `S.<name>`
(also after every button POST, and again after `retry` if a request fails). Names are global: the first module to ask for one keeps it.

### The standard widgets

| Type | What it is | Main properties |
|---|---|---|
| `text` | a paragraph | `text`, `muted`, `style` (`"log"`: a few lines of small monospace text that never wrap), `cls` |
| `row` | a Settings row: title and grey subtitle on the left, a widget on the right | `title`, `sub`, `control` (a widget), `below` (widgets under the row, full width) |
| `button` | `style` `"small"` (default round button), `"pill"` (big, in the primary colour), `"danger"` | `label`, `post` (a POST to this path), `body`, `colour` (pill: a colour reference), `confirm` (asks first), `pin` (asks for the PIN when one is set), `arm` (text shown on the first tap; a second tap within 4 s does it), `busy` + `busy_label`, `disabled`, `href` (a link instead of a POST), `aria`, `then` (`"reload"`, or `"wait"` = wait until the computer is back, for a reboot), `reload` (the name of a data source of this module's `data`: it is read again right after the POST; **without it only `/api` is asked for**, so a button whose press changes what a data source shows, such as Check for updates, must name it) |
| `toggle` | a tick box | `bind` + `post` (POSTs `{"value": bool}`), or `module` (a module's own switch: follows `@enabled.<name>` and POSTs `/modules`, then the page is built again), or `local` (kept in the page only, `default`), `text` (label beside it), `look` (`"neutral"` default, `"pri"`) |
| `swatches` | a small **Colour** button in the currently chosen colour; it opens a pop-up with the 16 palette colours (two rows: normal, bright) and a pick is stored for the module (and closes it) | `key` (one of the module's `colours` keys), `label` (default "Colour"), `title` (the pop-up's heading); `tint: true` (a tick box to the left of the button: coloured or neutral background, `POST /colour` with `tint`); use it as a `row`'s `control`; the row's `sub` says what the colour is for: **"Network"** for a network colour (DCNow!, DCNET), **"Module"** for a module's own colour (a test enforces one of the two) |
| `link` | a link that looks like a small button | `label`, `href`, `aria` |
| `form` | one **edit row** per field (title, a grey line, an **Edit** button on the right, and a list of tags under it when the field has one); the field's controls are in a pop-up that the button opens (the pop-up has a **Done** button) | `get`, `post`, `fields`: `[{"title", "sub" (a fixed line) or "sub_text": key into the reply's `texts`, "list": key into the reply's `lists`, "button" (default "Edit"), "edit": {a control spec, e.g. {"type": "checklist", "key", "options", "title", "empty"}} (with `inline`: an Edit button on the row opens a pop-up with that control; the checklist shows the options as ticked boxes with All / None, the value is `null` = all or the list of ticked ones), "inline": true (a field with one control: that switch or select sits on the row itself, no Edit button and no pop-up), "show", "controls": [{"type": "select"/"number"/"text"/"toggle", "key", "options": name or list, "min", "max", "label" (shown in the pop-up)}]}]`; `GET` answers `{"values": {...}, "options": {name: [{"value", "label", "group"}]}, "texts": {key: "ready-made line"}, "lists": {key: [...]}}`, `POST {"values": {...}}` saves and answers the same, with the lines recomputed (so "GPIO17 toggles ..." is written in Python, not in the page). Changes save 250 ms after the last one. | The controls are `select`, `choice` (buttons), `number`, `text`, `toggle` and, used by the `triggers` rows: `colour` (palette balls), `slider` (a level) and `range` (LEDs of a strip).
| `infobox` | the tap-to-open status box | `label` (a text or a binding), `title` or `parts` (`[{"text", "colour"}]`), `rows`: `[{"label", "main" (always visible), "show", "value": widget}]`, `actions` (widgets shown when open), `actions_show` `title_small`: the main title is as big as the rows' text (still bold; the Online players box shows its network counts so). A row's `busy` spinner sits next to the row's title (at the start of a row whose title is not shown). The names in a `"style": "compact"` list (title and grey line) scroll round like the carousel when they are too long (`marquee()` in `base/page/widgets.js`). **The line under the title** (a `main` row whose value is a `text`, other than `"style": "log"`) is drawn as a `carousel`: one line, centred while it fits, scrolling round when it is too long, closed or open (the room is the row without its label column). **Row options:** `only: "closed"` (shown only while the box is closed), `full` (no label column, the value takes the whole width), `bleed` (runs out to the box's left, right and bottom edge: the log), `tight` (no divider, little room above); a row with a `bar` or `console` keeps a tap from closing the box. Everything inside a box is the size of a settings row; only its top line (1.3em) and main title (1.6em) are larger. **The main title is the same closed and open:** one line, centred while it fits and scrolling round like a carousel when it is too long (never wrapped, never left-aligned); the base (`ticker()` in `base/page/widgets.js`) measures it whenever it is shown, resized or its text changes, so it starts by itself, and no module does anything for it |
| `status` | a dot and text, for infobox rows | `dot` (a state: `ok busy warn bad off call` = fixed state colours), `text`, `sub`, `lines` (first line + smaller ones) |
| `bar` | widgets side by side | `items` |
| `carousel` | one line that scrolls round, like a ticker, only when it doesn't fit; while it fits it stands still and is centred | `items` (list, joined with a bullet) or `text` |
| `pinset` | the **Set PIN / Change PIN** and **Remove** buttons (Settings > Appearance; the page asks for the old PIN first, `POST /pin`) | none |
| `picker` | a table to pick values for (a group may carry `choices` `[{value, label, sub, disabled}]`: its Add pop-up then lists them, the input filters; `free` also allows typing a value; `initial` (text) = show only choices with `now: true` until something is typed; `notes` `{item: text}` shows text behind a tag): one edit row per group (title, grey line, **Add** button; the items are listed as removable tags under the row once there are any), with **Restore** and an **(i)** information button (pop-up with `rules.help`) at the bottom (the phone numbers; the LED message table will follow it) | `source`: `GET` answers `{"groups": [{"key", "label", "sub", "items": [...]}], "defaults": {key: [...]}, "rules": {"min", "max", "per_group", "allowed" (characters, regex class syntax), "unique", "add_label", "add_title", "min_msg", "help", "restore"}}`, `POST {key: [...]}` saves and answers the same |
| `triggers` | rows of "something to do + what triggers it": one edit row per entry (title, grey line, its triggers as tags) with an **Edit** pop-up (a generic widget; no module uses it now, it came from the phone numbers and LED rows) | `source`: see `base/page/widgets.js` `W.triggers` |
| `list` | a list from the server, each row with a button that opens a small form (for example a list of networks), or compact rows with a coloured tag (the clock's cities) | `items`, `row` (`title`, `sub`, `button` or `tag` / `tag_colour` field names), `style` (`"compact"`), `empty`, `when`, `extra` (fixed rows after the list: `title`, `sub`, `button`, `item`), `popup` (`title` (`{field}` is filled in from the row), `title_other`, `fields` `[{key, label, type, show_if, required, blank}]` (a field whose `show_if` is never true is not shown, but its value is sent: the row's id), `submit`, `busy`, `post`, `reload` (a data source of the module that is read again after it), a PIN is asked for when one is set; when the server refuses with a `message` it stays in the pop-up), `row.button_if` (a field of the item that must be set for the button to show), `search` (a box that narrows the rows by title and grey line; the placeholder text) and `limit` (at most that many rows are drawn, then "N more: use the search"). Also `"style": "compact"` (rows in a box) and `"style": "grid"` (short name / value pairs in columns); `row` = which fields to show: `lead` / `lead_big` (a small line over a bold one at the left), `title` (+ `href`: a link), `sub`, `tag` / `tag_colour`, and `icon` = `{kind: "star" \| "bell", post, on, data, body, fields}` (a round on / off button that POSTs the item's fields and `on`) |
| `roster` | the check-in board: one **box per group** with a row per person (grey while out, in the person's colour while in); `"mode": "colours"` is the Settings list that gives each department / building a colour | `source` (`"@checkin"`: groups of people, the status menu, buildings), `toggle` (POST `{id}`: INNE / UTE switches in / out), `status` (POST `{id, code, detail}`); mode `colours`: `get` / `post` (`{kind, name, colour}`). The INNE / UTE button on a row switches the person; a tap on the row opens the status menu (a centred pop-up, `.rp-modal`); a chip row picks buildings (kept in the browser, `?location=A,B` in the address sets it). Colours are palette ids only. See [checkin.md](checkin.md) |
| `links` | a row of text links, or with `"style": "buttons"` grey buttons in one row | `items`: `[[label, url, tooltip], ...]` (the tooltip is optional) |
| `console` | lines of text | `lines` (binding: replaces all) or `tail` (url; `GET url?from=N` answers `{"text", "size", "reset"}`), `rules` (`[[regex, "l-err"], ...]`, first match wins), `nowrap`, `height`, `follow`, `active`, `hide_empty`, `label` |
| `info` | a read-only table of name / value pairs | `rows` (binding) or `source` (a url, fetched when Settings opens, `[[name, value], ...]`) |
| `custom` | a box of the module's own | `name`, `html` or `html_file` (a file in the module folder), `cls` |

**The edit row** is the one look for a setting that has a button: `editRow()` in `base/page/widgets.js` (title and grey line on the left, a small button on the right, an optional tag list underneath that takes no room while it is empty). The `form` widget, the `picker` and the colour pick (`row` + `swatches`) are all made of it, so Appearance, GPIO and Special phone numbers look alike; use `form` or `picker` rather than building a row by hand. **Borders are always opaque** (boxes, buttons, banners: `rgb(...)`, never `rgba`), while the backgrounds of the boxes stay see-through; a translucent border over a see-through background looked duller than the same border on a button (`tests/test_ui_kit.py` checks it). **An infobox's main title** (`title`, or `parts` = coloured pieces `[{text, colour}]` in the colour of a palette id or `module.key`, so the network name has its network's colour) never wraps while the box is closed: when it is too long for the box it scrolls round like a carousel (`ticker()` in `base/page/widgets.js`; not in an open box or a large clock). **After a button's POST the page asks only for `/api`**; a data source is read again only when the widget says so with `"reload": "<data name>"` (a `button`, or a `picker` whose list the data shows: the events Sync buttons, the players favorites). Reading every source after every press made the network buttons take seconds on a computer. **Global main** (`colourpick`) is a small Colour button in its own colour like the other picks; the system's colour chooser lies invisibly over it. **Styling is the kit's alone** (`base/page/page.css`): tokens in `:root` (`--r-box` 29 px boxes, `--r-ctl` 12 px fields and checkboxes, `--r-pill` buttons and chips, round = 50%, `--h-ctl` 36 px for every control, `--text-1..3` and `--box-text-2..3`, `--fs-xs..xl`), one look per component. A module sets layout and function in `layout.json` and ships no CSS of its own (the debug log and players modules already have none; the rest are being moved over); `tests/test_ui_kit.py` checks the radii and the tokens. **Refreshing:** the last answer of every data source is kept in the browser and shown at once when the page opens (with `busy: true` until the new one is there), and a list widget whose items are `null` says nothing (no "Nobody is online" before the first answer). An infobox row may have `"busy": "@path"` (`players.busy`, `events.busy`): a small spinner (`.spin`) turns at the end of the row while that is true. The row keeps what it shows until the new data is complete and the box does not close or shrink; the players and events modules use it (`players.refreshing`, `events.syncing`), any module whose data is fetched again should too. **Icon buttons:** `ui.iconButton(kind, on, what)` / `ui.iconButtonHtml()` in `base/page/page.js` make the round on / off button of the kit (`.ibtn`, `bell` for a reminder, `star` for a favorite); a compact `list` widget row takes `"star": {post, kind, on, data}`. **An Edit button is always at the top right of its row** (`.srow.edit`: the row aligns to the top, so the button stays there however many lines the text has). **Simple picks are buttons, not a list:** a form field whose only control is `{"type": "choice", "key", "options"}` opens a pop-up that is just the options as a row of buttons (the chosen one in the module's colour, like the colour pop-up): a tap picks, saves and closes, there is no Done. Use it whenever there are a handful of options (the clock's 12h / 12h am/pm / 24h); a `select` with Done stays for long lists (the time zone). **A picker can be one row with an Edit button:** `{"type": "picker", "source": ..., "edit": true}`: the tags, Add (a search / pick area inside the same pop-up) and Restore are in the Edit pop-up, which keeps a long settings box short (the clock's Cities). **An infobox** may take `"mode": "@path"` (puts the text on the box as `data-mode`, so the module's `page.css` can lay it out differently: the large clock) and `"open_if": "@path"` (while false the box has nothing to show when tapped, so it is not a button and does not open); it has no arrow. **The time zone is a base setting** (`core.time_zone()` / `save_time_zone()`, `time_zone` file, `GET`/`POST /timezone`, the form is in Settings > About from the `system` module): every module that shows a time of day reads it (the clock does; the events module still has a zone of its own).

A **custom widget** is registered by the module's `page.js`: `custom("contacts-import", function(host, ctx){ ... })`. The page calls
it after the whole layout is in the document, so it can look its elements up by id; `host` is the element holding the markup,
`ctx.saved()` flashes the box's "Saved ✓", `ctx.mod` is the module name. Pop-ups inside it use `ui.popup(el)` (below). Use a custom widget only for what no standard widget does
yet; a new widget that two modules could use goes into `base/page/widgets.js` instead (plus `WIDGETS` in `base_modules.py`; a test keeps the two lists equal).

### Backgrounds

A module with `{"background": {"type": "fullscreen" | "part", "position": "top" | "bottom"}}` is a **background module** and can have
**settings boxes** (the Background image module has one) but no dashboard boxes and no data: it is the only kind of module that draws behind the boxes. The page walks the enabled background modules in
picker order: the first one is drawn; if it is `fullscreen` nothing below it is (and its script isn't even sent); if it is `part` (a
taskbar-like strip or a logo that only fills an area; `position` pins it to the top or bottom, the module sets its height) the next one is drawn too.
The module's `page.js` calls `background("<module name>", function(host, spec){ ... })` and draws into `host`
(a div in the page's `#bg` layer). No module has one at the moment; the mechanism stays for a theme (the one place a module's CSS may restyle base classes).

### Web entry

The module named in `"web"` may define:

- `GET = {"/path": fn(handler)}` and `POST = {...}`: exact paths. `fn` answers with `handler.send(body, ctype, status=200)`; a POST function returns `True` once it has answered (else the web service sends 204 / 303). `handler._body(limit)` reads the request body.
- `api(d, warnings)`: called for every `GET /api`, in picker order; add keys to the answer dict `d` (what the module's widgets bind to: put ready-to-show texts here, not logic in the page) and lines to `warnings` (the warning boxes). A hook should not depend on another module's keys (the LED module sets `d["dreampi"]["look"]`, the switcher adds the rest with `setdefault` rules).
- `GET_PREFIX = {"/api/events/": fn}` / `POST_PREFIX`: paths that start with the key (and go on); an exact path wins. `fn` reads the rest of `handler.path` itself.
- `OPEN = ("/path", ...)`: POST paths that stay open while Settings is locked with the PIN (Settings > Appearance): the dashboard's own actions (the check-in module lists tapping people in and out and a photo). Every other POST of a module is a setting and needs the PIN then, so a new module is locked by default.
- `start()`: called once when the web service runs (and when the module is switched on later): background work that must go on without the page open (the events module's sync).
- `PROTECTED = ("/path", ...)`: POST paths of this module that run as root (reboot, update, joining a network): they need the PIN when one is set.

POSTs pass the same security gate as every other POST (Origin / `X-Requested-With`); only paths a module lists in `PROTECTED` need the PIN: `/reboot`, `/update/start`, `/contacts/import`, `/contacts/active`. A module that is off has no protected paths at all, because it has no routes. Unknown paths answer 404.

## Colours and the theme

The base owns the theme. **One global palette of 15 named colours** (`core.PALETTE`; in the order of the pick-a-colour grid, two rows of eight: **Global main** (`global`: one colour the user picks, `colourpick` widget, `POST /palette`), red, orange, yellow, green, cyan, blue, purple, white, then `bright-` red, green, cyan, blue, purple, pink. Older picks of `bright-orange`, `bright-yellow` and `pink` become their nearest, `core.LEGACY_COLOURS`) with a page colour and a lighter variant for borders. The page gets them as CSS variables (`--c-<id>`, `--c-<id>-l`, `-rgb` triples) and a class `.c-<id>` that makes an element and everything inside it use that colour as its `--primary`.

- A module **never writes a colour of its own**. It names palette ids in `module.json` `"colours": {"checkin": "green"}` — defaults the user changes in the module's own settings (`swatches` widget, `POST /colour`, kept in `colours.json`; `core.module_colours(name)`, `core.set_module_colour()`; with `colours_unique` no two keys share a colour). `/api` carries `colours` (`{module: {key: id}}`) so every device follows.
- **Every module with a box on the main page has a colour of its own** (`checkin`, `clock`) with a `swatches` row (`"tint": true`) in the Appearance box. The tick box is the background setting: `core.module_tints()` / `set_module_tint()` (`tints.json`, `{module: {key: bool}}`, only what differs from the default is kept; the default is the manifest's `"tints": {"clock": false}`), `/api` carries `tints` and `primary_key` (which colour key a module's primary is), and the page puts the class `plain` on a box (or an own-colour button) whose background is neutral. CSS: `.dbox.plain .now`, `.pill.plain`.
- **The palette can be edited** (Settings > Appearance > Colour palette: the base widget `palette`, in the System module's Appearance box; `GET /palette/list`, `POST /palette/edit` / `add` / `delete` / `order` / `reset` in `base/base_web.py`; also the `colourpick` widget for Global main): `palette.json` holds the colours the user changed and `palette_custom.json` the list (order, deleted, renamed, own colours); `core.colours()` merges them over `PALETTE`, so everything that asks for a colour gets the edited one (`core.palette_*()`, `set_palette_colour()`, `reset_palette()`; the pick lists and `palette_ids()` follow). What the page shows follows at once: `/api` carries `palette` and `palette_css` whenever `palette_v` changed.
- A module also has a **primary colour**: the one used on its borders and primary buttons. It is set statically (`"primary"` in `module.json`: a palette id or one of its own colour keys) or while running through its `api()` hook (`d["primary"][name] = id`). Each box and widget takes the primary of its own module (a `.c-<id>` class); the top module in picker order that has a primary also sets the page's. **A lower module that picks another colour only uses it for itself.** The board's buttons are the exception: each takes the colour of its department, building or status (`data-own-colour`).


## The page kit (what is left for a module's own CSS and JS)

A module does not decide how things look. The base page (`base/page/page.css`, the block marked "The page kit", `ui` in `base/page/page.js` and the widgets in `base/page/widgets.js`) provides the building blocks, so a change there changes every module. `ui.version` and `UI_KIT` in `base_modules.py` are its version (now 2); a module's `"ui"` says which it was written for.

- Layout, rows, buttons, forms, boxes, tables, lists, consoles, colour pickers: the widgets above, nothing else needed.
- **Pop-ups** inside a custom widget: an element in a card (`<div class="t">Title</div> ... <div class="msg"></div>`; `fld` puts an input and a button on one line, `bar` / `bar end` / `bar center` lay out buttons, `big` makes it wider) and `var p = ui.popup(el)`; `button.onclick = function(e){ p.toggle(this, e) }`, `p.close()`, `p.onclose`. It moves into its card the first time it opens. Esc, a click elsewhere, opening another pop-up and closing Settings close it. While a pop-up is open its card grows to hold it (`fit()` in `ui.popup`), because in the multi-column settings view anything that sticks out of a card is continued in the next column.
- **CSS classes** for a custom widget's markup: `srow` (+ `wrap`, `below`), `pill-s` (+ `danger`), `cbox` (+ `neutral`), `select.ord`, `tags` / `tag`, `range` (+ `grid`), `console` (+ `nowrap`; line classes `l-err l-ok l-dim l-hd l-info l-warn l-mod l-b`), `msg`, `empty`, `sub`.
- **Highlight and notices** (base, for any module's `api()`): `d["highlight"][box id] = "why"` makes that dashboard box stand out while the module keeps asking (class `hl` on the box, the reason as its tooltip). A neutral box (class `plain`: its colour's Highlight switch is off, the default) turns its own colour; a coloured box gets the global look of Settings > Appearance > Notification highlight (`GET`/`POST /highlight`, `core.highlight_style()`: `rainbow` = an animated rainbow edge drawn over the border, or a palette id = a glow in that colour; `/api` `theme.highlight`). Not to be confused with a colour's Highlight switch (`tints`), which makes a box coloured for good. `d["notices"].append({"id", "text", "post"})` shows a banner above the boxes in the page's colour; its ✕ POSTs `{"id"}` to `post`. Both keys are in every `/api` answer, so a box stops standing out as soon as no module asks.
- **Hooks** (`hook(name, fn)` / `fire(name, arg)` in `base/page/page.js`): `api` (d, every second), `settingsOpen`, `settingsClose`, `escape` (return `true` if handled), `posted` (after a button's POST), `layout` (a box changed size), `expand` / `collapse` (an expander).

Rules (`tests/test_ui_kit.py` checks them): a module's `page.css` does not style a base class on its own (`.srow{...}` would change every row; `#my-list .srow{...}` and the module's own class names are fine), does not write colours as `#hex` (except white and black), and its `page.js` does not write `.srow` markup or open pop-ups by hand. The LED message table keeps its CSS in its own `page.css` until it moves to a standard table; a theme such as the Dreamcast background restyles base classes on purpose and is the one exception. To add something new that two modules could use, add it to the kit (CSS, widget, this table, a test) instead of to a module.

## The loader (`base_modules.py`)

`refresh()` runs for every request (`base_web.refresh_page()`): when the signature (mtimes of the module folders, `modules.json`, `module_order.json`, `colours.json`, the base page files) changed, it checks every enabled module (`ui` version, `layout.json`), imports the web entries, collects routes and `api` hooks and the web service builds the page again: **adding or deleting a module folder, editing its files, switching or moving it in the picker takes effect on the next page load**, without restarting the web service. A module whose layout or Python is broken is skipped and reported (`errors()`: a warning box, and in the picker). `layout()` merges the layouts (`window.LAYOUT` in the page); `page_parts()` returns the modules' `page.css` / `page.js` (a background module that isn't drawn is left out); `live_colours()` feeds `/api`.

`GET /modules` lists the visible modules with `enabled`; `POST /modules {"name", "enabled"}` switches one; `POST /modules/order {"order": [names]}` moves them. Both need the page's own request header, and both reload the page.

The page itself (`page/`): `index.html` is only the frame (`#bg`, header, `#warnings`, `#dash`, the Settings overlay with `#set-boxes`); `page.js` the kit, hooks and `/api` loop; `widgets.js` the layout engine and the widgets; `boot.js` draws the layout and starts the loop last.

## Services and the installer

- `install.sh` `sync_modules`: copies every `modules/*/` that has a `module.json` to `$DEST/modules/` (replacing the old copy as a whole); a folder that was installed before but is gone from the repo gets its `remove.sh` run and is deleted. Then every installed module's `install.sh` is sourced. The installer also copies the base page files (`index.html`, `page.css`, `page.js`, `widgets.js`, `boot.js`).
- To **remove a module for good**: delete its folder in the folder you installed from and run `sudo ./install.sh` (its service and files go; its settings files like `contacts.json` and `checkin.json` stay for when it comes back). To **add one**: put the folder in and run the installer. To only hide it: switch it off in Settings > System > Modules.

## Adding a new module

Make `modules/<name>/` with a `module.json` (`name`, `description`, `enabled`, `visible`, `ui: 2`), a `layout.json` with its boxes, and a web entry for its endpoints and `api()` texts (`"web"`). Put the texts the widgets show in `api()` (or in the reply of a data source), not in JavaScript. Add it to `NAMES` / `ENDPOINT` in `tests/test_modules.py` so the "every module can be removed or switched off alone" tests cover it, and a view test (`tests/test_module_views.py`) for what it hands to the widgets. Add an `install.sh` / `remove.sh` if it has a service. If you need a widget the base lacks, add it to `base/page/widgets.js` (and the kit, docs, a test) rather than a one-off in the module.

## Tests

`tests/test_module_picker.py` (manifest keys, visible, order, the picker's HTTP), `tests/test_layout.py` (boxes shared by name, picker order, backgrounds, validation, data sources, primary colours), `tests/test_module_views.py` (the texts and lists the modules hand to the widgets), `tests/test_modules.py` (the modules well formed; the page and endpoints with everything on; with nothing (the base alone, JS syntax-checked with node); each module deleted alone and switched off alone and back while the web service keeps running; a broken module; a new folder picked up; the installer's `sync_modules` on temp folders; layering), `tests/test_checkin.py` (the CSV import, the board, statuses, colours, two screens in step over HTTP), `tests/test_ui_kit.py` (the kit rules, the loader and page agreeing on the widget list). `sh tests/ui/run.sh` (optional, needs Chromium) audits the page at four widths (the board as buttons and as boxes) and runs `tests/ui/functional.js`, which drives the real page: tapping, the status menu, a second screen following, the buildings filter, the settings, the CSV import, the module picker.
