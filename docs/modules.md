# Modules: the optional features

Read before adding, removing or restructuring a feature. Back to [CLAUDE.md](../CLAUDE.md).

## What is base and what is a module

**Base** (always there): the web page with the Selected-network box (DreamPi, modem, internet and Pi status, Hang up), the two network buttons (`POST /dcnow`, `/dcnet`), Settings with Appearance, the buttons' GPIO config, **Modules**, About (with updates) and Reboot; the hook inside DreamPi (routing, state files, the fixed openMenu number), the buttons service, `GET /tag`, security (Host/Origin checks, PIN) and the updater.

**Modules** (`modules/<name>/`, one folder each, all optional):

| Module | Folder | What it is | Default |
|---|---|---|---|
| `numbers` | `modules/numbers/` | the editable phone numbers: Settings > Phone numbers, `GET`/`POST /numbers`, `numbers.json` (the hook only reads it while the module is on, else it uses its built-in defaults) | on |
| `players` | `modules/players/` | the Online players box on the main page and `GET /players` | on |
| `wifi` | `modules/wifi/` | Wi-Fi setup: the Wi-Fi rows in Settings, `POST /wifitoggle` and `/wificonnect`, its own service `dreampi-netswitch-wifi` (`netswitch_wifi_service.py` + `netswitch_wifi_setup.py`) | **off** |
| `led` | `modules/led/` | the status LEDs: the service (`netswitch_led.py`, `netswitch_led_drivers.py`), `netswitch_ledconfig.py`, the NeoPixel calibration and Status LED settings **including the LED count / GPIO pin / wire order row**, `GET`/`POST /ledconfig` | on |
| `debuglog` | `modules/debuglog/` | the Debug log bar and live log on the main page, `GET /log`, `/dtmf`, `POST /debug`, `/clearlog`, and the part that runs inside DreamPi (`netswitch_hookdebug.py`) | **off** |

A module is **installed** when its folder (with a `module.json`) is there, and **enabled** when the Modules menu has it on (`modules.json` in `/opt/dreampi-netswitch`: `{"led": true, ...}`; a module without an entry uses `default` from its manifest). Not installed or not enabled = absent: no page parts, no endpoints (404), no service work. `core.module_manifest()`, `module_names()`, `module_enabled()`, `save_module_enabled()` read and write that state; the web service, the LED service, the buttons service and the hook (own Python 2 copy, `_module_active()`) all ask it.

## A module folder

```
modules/<name>/
  module.json      {"title", "description", "order" (menu order), "default" (on/off until the menu says otherwise),
                    "web" (Python module name of its web entry), "note" (optional hint shown in the menu)}
  netswitch_*.py   its Python: the web entry named in "web", plus anything its services use
  page.html        fragments for the page's slots:  <!--slot:NAME-->  ...markup...  <!--slot:OTHER--> ...
  page.css         added to the page's styles
  page.js          added to the page's script (same scope, after page.js; uses hook(), fire(), $, esc ...)
  install.sh       optional, sourced by install.sh (sees $DEST $SRC $LED_COUNT $LED_GPIO $WIFI $WIFI_DEMO, ns_module_enable)
  remove.sh        optional, sourced when the folder is gone from the repo, and by uninstall.sh
```

Python files in a module folder import the base by name (`import netswitch_core as core`): the loader, and the module's own services, put the base folder and the module folder on `sys.path`. The base never imports module code, with one guarded exception: the hook loads `netswitch_hookdebug` (only while the debug log module is installed and on). `tests/test_modules.py` enforces this.

### Web entry

The module named in `"web"` may define:

- `GET = {"/path": fn(handler)}` and `POST = {...}`: exact paths. `fn` answers with `handler.send(body, ctype, status=200)`; a POST function returns `True` once it has answered (else the web service sends the usual 204 / 303). `handler._body(limit)` reads the request body.
- `api(d, warnings)`: called for every `GET /api`; add keys to the answer dict `d` and lines to `warnings` (the warning boxes).

POSTs pass the same security gate as every other POST (Origin / `X-Requested-With`); only `security.PROTECTED` paths need the PIN. Unknown paths answer 404, so a module's endpoints disappear with the module.

### Page slots

`page/index.html` has `@@SLOT:name@@` markers; each module's `page.html` fills the ones it names (modules in menu order):

| Slot | Where |
|---|---|
| `main` | `#main-slot`, under the two network buttons (Online players box, Debug log bar) |
| `about_top` | extra rows at the top of the About card (the Wi-Fi setup row) |
| `sections_a` | whole Settings sections before Appearance (Phone numbers) |
| `buttons_rows` | extra rows in the buttons' GPIO card (the Wi-Fi hold button) |
| `sections_b` | whole Settings sections after the GPIO card (NeoPixel calibration, Status LED) |

Client-side hooks (`page/page.js`): a module's `page.js` calls `hook(name, fn)`, the page calls `fire(name, arg)`: `api` (d, every second), `settingsOpen`, `settingsClose`, `escape` (return `true` if handled), `buttons` (the button settings were loaded), `posted` (after a form post). Settings opening, closing and refreshing never mention a module by name.

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
