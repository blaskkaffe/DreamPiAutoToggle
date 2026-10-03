# Modules: the optional features

Read before adding, removing or restructuring a feature. Back to [CLAUDE.md](../CLAUDE.md).

## What is base and what is a module

**Base** (always there): the web page with the Selected-network box (DreamPi, modem, internet and Pi status, Hang up), the two network buttons (`POST /dcnow`, `/dcnet`), Settings with the buttons' GPIO config, **Modules**, and System (the versions, a GitHub link); the hook inside DreamPi (routing, state files, the fixed openMenu number), the buttons service, `GET /tag` and security (Host/Origin checks, PIN).

**Modules** (`modules/<name>/`, one folder each, all optional):

| Module | Folder | What it is | Default |
|---|---|---|---|
| `numbers` | `modules/numbers/` | the editable phone numbers: Settings > Special phone numbers, `GET`/`POST /numbers`, `numbers.json` (the hook only reads it while the module is on, else it uses its built-in defaults) | on |
| `players` | `modules/players/` | the Online players box on the main page and `GET /players` | on |
| `wifi` | `modules/wifi/` | Wi-Fi setup: the Wi-Fi rows in Settings, `POST /wifitoggle` and `/wificonnect`, its own service `dreampi-netswitch-wifi` (`netswitch_wifi_service.py` + `netswitch_wifi_setup.py`) | **off** |
| `led` | `modules/led/` | the status LEDs: the service (`netswitch_led.py`, `netswitch_led_drivers.py`), `netswitch_ledconfig.py`, the Status LED settings (with the calibration pop-up) **including the LED count / GPIO pin / wire order row**, `GET`/`POST /ledconfig` | on |
| `background` | `modules/background/` | the animated Dreamcast background: `GET /background/*.js` (its own script files), the `#dcbg` layer and the translucent box styling | **off** |
| `rebootupdate` | `modules/rebootupdate/` | the Updates rows (check, Update now, log) at the end of the System card, the Reboot card, `GET /update`, `POST /update/check`, `/update/start`, `/reboot`, and `netswitch_update.py` | on |
| `debuglog` | `modules/debuglog/` | the Debug log bar and live log on the main page, `GET /log`, `/dtmf`, `POST /debug`, `/clearlog`, and the part that runs inside DreamPi (`netswitch_hookdebug.py`) | **off** |

A module is **installed** when its folder (with a `module.json`) is there, and **enabled** when the Modules menu has it on (`modules.json` in `/opt/dreampi-netswitch`: `{"led": true, ...}`; a module without an entry uses `default` from its manifest). Not installed or not enabled = absent: no page parts, no endpoints (404), no service work. `core.module_manifest()`, `module_names()`, `module_enabled()`, `save_module_enabled()` read and write that state; the web service, the LED service, the buttons service and the hook (own Python 2 copy, `_module_active()`) all ask it.

## A module folder

```
modules/<name>/
  module.json      {"title", "description", "order" (menu order), "default" (on/off until the menu says otherwise),
                    "ui" (the page kit version it was written for, 1), "web" (Python module name of its web entry),
                    "note" (optional hint shown in the menu)}
  netswitch_*.py   its Python: the web entry named in "web", plus anything its services use
  page.html        fragments for the page's slots:  <!--slot:NAME-->  ...markup...  <!--slot:OTHER--> ...
  page.css         added to the page's styles (as little as possible: see the page kit below)
  page.js          added to the page's script (same scope, after page.js; uses hook(), fire(), $, esc ...)
  install.sh       optional, sourced by install.sh (sees $DEST $SRC $LED_COUNT $LED_GPIO $WIFI $WIFI_DEMO, ns_module_enable)
  remove.sh        optional, sourced when the folder is gone from the repo, and by uninstall.sh
```

Python files in a module folder import the base by name (`import netswitch_core as core`): the loader, and the module's own services, put the base folder and the module folder on `sys.path`. The base never imports module code, with one guarded exception: the hook loads `netswitch_hookdebug` (only while the debug log module is installed and on). `tests/test_modules.py` enforces this.

### Web entry

The module named in `"web"` may define:

- `GET = {"/path": fn(handler)}` and `POST = {...}`: exact paths. `fn` answers with `handler.send(body, ctype, status=200)`; a POST function returns `True` once it has answered (else the web service sends the usual 204 / 303). `handler._body(limit)` reads the request body.
- `api(d, warnings)`: called for every `GET /api`; add keys to the answer dict `d` and lines to `warnings` (the warning boxes).
- `PROTECTED = ("/path", ...)`: POST paths of this module that run as root (reboot, update, joining a network): they need the PIN when one is set.

POSTs pass the same security gate as every other POST (Origin / `X-Requested-With`); only paths a module lists in its web entry's `PROTECTED = (...)` tuple need the PIN (and the page's header, never a plain form post): `/reboot`, `/update/start` (Reboot and Update) and `/wificonnect` (Wi-Fi setup). A module that is off has no protected paths at all, because it has no routes. Unknown paths answer 404, so a module's endpoints disappear with the module.

### Page slots

`page/index.html` has `@@SLOT:name@@` markers; each module's `page.html` fills the ones it names (modules in menu order):

| Slot | Where |
|---|---|
| `main` | `#main-slot`, under the two network buttons (Online players box, Debug log bar) |
| `about_top` | extra rows at the top of the System card (the Wi-Fi setup row) |
| `about_bottom` | extra rows at the end of the System card (the Updates rows) |
| `system_after` | whole cards after the System card (the Reboot card) |
| `sections_a` | whole Settings sections before the GPIO card (Special phone numbers) |
| `buttons_rows` | extra rows in the buttons' GPIO card (the Wi-Fi hold button) |
| `sections_b` | whole Settings sections after the GPIO card (Status LED, with the calibration pop-up) |

Client-side hooks (`page/page.js`): a module's `page.js` calls `hook(name, fn)`, the page calls `fire(name, arg)`: `api` (d, every second), `settingsOpen`, `settingsClose`, `escape` (return `true` if handled), `buttons` (the button settings were loaded), `posted` (after a form post). Settings opening, closing and refreshing never mention a module by name.

### The page kit

A module does not decide how things look. The base page (`page/page.css`, the block marked "The page kit", and `ui` in `page/page.js`) provides the building blocks, and every module is written with them, so a change in the kit changes every module, current and future. `ui.version` in `page.js` and `UI_KIT` in `netswitch_modules.py` are its version (now 1); a module's `"ui"` says which version it was written for, and a module that wants a newer one than the page has is not loaded (the Modules menu says why).

| You want | Use |
|---|---|
| A Settings section | `<section class="sec"><h2>Title</h2><div class="card">...</div></section>` (the base's own classes), put in a slot |
| A row: title, grey subtitle, control on the right | `ui.row({title, sub, control, below, id, cls})` in JS, or `<div class="srow"><span>Title<span class="sub">...</span></span> control</div>` in `page.html`. `below` adds full-width content under the row (it makes the row wrap). |
| A small button | `ui.btn("Text", {attr: value})` or `<button class="pill-s">`; a link that looks like one: `<a class="pill-s">`; a dangerous action: `pill-s danger` |
| Tick box | `<input type="checkbox" class="cbox dcnow">` (or `neutral`) |
| Drop-down, number box | `<select class="ord">`, `<input type="number">`: both are 36 px high |
| Removable items (numbers, say) | `<div class="tags">` with `ui.tag("text", {attr: value})` for each; `<span class="empty">` when there are none |
| A pop-up under a button | an element in a card or section (`<div id="x"><div class="t">Title</div> ... <div class="msg"></div></div>`; `fld` puts an input and a button on one line, `bar` / `bar end` / `bar center` lay out buttons, `big` makes it wider) and `var p = ui.popup($("x"))`; then `button.onclick = function(e){ p.toggle(this, e) }`, `p.close()`, `p.onclose`. Esc, a click elsewhere, opening another pop-up and closing Settings close it. |
| A slider row | `<div class="range"><span>Label</span><input type="range"><span>value</span></div>`; `range grid` lines several of them up |
| A log / console | `<div class="console">` (add `nowrap` for one entry per line); line classes `l-err l-ok l-dim l-hd l-info l-warn l-mod l-b` |
| An error line | `<div class="msg">` (empty = hidden) |
| Colours | the CSS variables in `:root` (`--card --line --muted --ctl --ctl-line --pop --sel --sel-line --dim --txt2 --console --dcnow --dcnet` ...), never a colour written out |

Rules (`tests/test_ui_kit.py` checks them): a module's `page.css` does not style a base class on its own (`.srow{...}` would change every row; `#my-list .srow{...}` and the module's own class names are fine), does not write colours as `#hex` (except white and black), and its `page.js` builds rows with `ui.row()` and pop-ups with `ui.popup()`. A module whose look has nothing in the kit (the LED message table, the players box) keeps that CSS in its own `page.css`, scoped to its own ids and classes. A theme such as the Dreamcast background restyles base classes on purpose and is the one exception. To add something new that two modules could use, add it to the kit (CSS, helper, this table, a test) instead of to a module.

### The loader (`netswitch_modules.py`)

`refresh()` is called for every request (`netswitch_web.refresh_page()`): when the signature (mtimes of the module folders and `modules.json`, the base page files) changed, it imports the web entries of the enabled modules, collects their routes and `api` hooks, and the web service builds the page again. So **adding or deleting a module folder, editing its files, or switching it in the Modules menu takes effect on the next page load**, without restarting the web service. A module whose Python fails to import is skipped and reported (`error` in `GET /modules`, shown in the menu) - the page still works.

`GET /modules` lists the installed modules with `enabled`; `POST /modules {"name", "enabled"}` switches one (needs the page's own request header). The page then reloads and reopens Settings.

## Services and the installer

- The **LED service** (`dreampi-netswitch-led`, `modules/led/netswitch_led.py`) drives `ledconfig.led_count()` LEDs while the module is on and **0 (closed, dark) while it is off** (`wanted_count()`), so the Modules menu needs no systemctl. Its unit has `ConditionPathExists=` for the three files, so deleting the folder from `/opt/dreampi-netswitch` makes systemd skip it quietly.
- The **buttons service** is base and loads no module code. While the Wi-Fi module is on, a hold only touches `wifi_start` / `wifi_stop` (the same files the page's button touches). The **Wi-Fi service** (`dreampi-netswitch-wifi`, written by the module's `install.sh`, removed by its `remove.sh`) idles until a start request, runs `setup_cycle()`, and treats switching the module off mid-setup as a stop. Its unit has `ConditionPathExists` for the module's files.
- `install.sh` `sync_modules`: copies every `modules/*/` that has a `module.json` to `$DEST/modules/` (replacing the old copy as a whole); a folder that was installed before but is gone from the repo gets its `remove.sh` run and is deleted. Then every installed module's `install.sh` is sourced (the LED one writes its unit and handles SPI for GPIO10; the Wi-Fi one handles `--wifi` / `--no-wifi` / `--wifi-demo` and installs hostapd + dnsmasq) and the services they add (`NS_SERVICES`) are enabled and restarted. `--wifi` turns the Wi-Fi module on (`ns_module_enable`), an old `wifi_enabled` marker is converted. `uninstall.sh` sources every `remove.sh` first.
- To **remove a module for good**: delete its folder in the folder you installed from and run `sudo ./install.sh` (its service and files go; its settings files like `led.json`, `led_count`, `numbers.json` stay for when it comes back). To **add one**: put the folder in and run the installer. To only hide it: switch it off in Settings > Modules.

## Adding a new module

Make `modules/<name>/` with a `module.json`, a web entry (even an empty `GET = {}`), `page.html` / `page.css` / `page.js` as needed, and an `install.sh` / `remove.sh` if it has a service. Add it to `NAMES` / `MARKER` / `ENDPOINT` in `tests/test_modules.py` so the "every module can be removed or switched off alone" tests cover it. Keep the module's markup, styles and script in its own files: `index.html`, `page.css` and `page.js` must not mention it.

## Tests

`tests/test_modules.py`: the five modules well formed; the page and endpoints with everything on; with nothing (the base alone, JS syntax-checked with node); each module deleted alone and switched off alone from the menu and back, while the web service keeps running; bad menu requests; a broken module; a new folder picked up; the LED service following the menu; the installer's `sync_modules` on temp folders; layering. `tests/test_hook_modules.py`: the hook with the debug log module present, absent and off. `OFF=led,wifi` (or `OFF=all`) with `tests/ui/demo_server.py` shows the page with modules off. **Not run on a Pi:** the installer's service handling (removing the LED unit when the module is gone, `ConditionPathExists=`).
