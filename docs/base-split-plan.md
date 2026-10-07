# Splitting the base from the project (plan)

**Goal.** The base is a reusable framework for a modular web dashboard on a small device: it knows modules, a page with a theme, a colour palette, settings,
a PIN and the web service. It must know nothing about DreamPi, networks, LEDs, modems, Wi-Fi, openMenu or events. **All of that lives in the modules**: each module
owns its scripts, its state files, its installer part and its page code, and a different project can bring a different `modules/` folder and a different
`project.json` and reuse the base unchanged.

**Rules (decided).**
1. A module owns its code and its state files. **Modules never import each other.** What module B needs from module A it reads from A's state file (the file
   format is the contract, a few lines of reader in B) or gets from `/api` / the page. Nothing DreamPi-specific is shared code.
2. The base offers generic things only: module manifest / state / order / groups, colours (palette, tokens, picks, tints, highlight), screen layout and theme,
   PIN and security, time zone, `read_file`, `poke`, a log line, the web service and the page kit. A module can offer a *service* to other modules of the
   same process (`register_service` / `service`), used for what must be computed at the moment (the colour a colour token has now).
3. **Neutral names.** Base files are `base_*.py` in `base/`, with `base/page/` (the page frame and kit). Everything about the project is in `project.json`
   (name, page title, data folder, tmp prefix, service names, ports, icons). The base reads it; it has no project words in its code (a test checks).
4. The palette has no LED colours any more: the LED module owns how the LED shows a colour (its own defaults table + `led_colours.json`).

**Layout after the split.**
```
base/                 base_core.py base_modules.py base_web.py base_security.py base_tz.py  page/ (index.html page.css page.js widgets.js boot.js)
project.json          what is specific to this project, read by the base
static/               the project's icons
modules/<name>/       module.json layout.json  <its Python files>  page.js page.css  install.sh remove.sh
install.sh uninstall.sh   the project's installer (copies base/ and modules/ to the data folder)
```

**Where the project code goes.**
| now in the base | goes to | how others get it |
|---|---|---|
| selected network (`dcnet_mode`), `tag()`, DCNET checks, `network_colour()`, boot reset, DreamPi / modem state readers, hook checks | `switcher` | files: `dcnet_mode`, the state files; openMenu asks the `switcher` service in the web process |
| `netswitch_probes.py` (internet, link, Pi health, hang up, modem id, checker loop) | `switcher` (the About rows to `system`) | `net` state file (`/tmp/....net`) for the LED |
| `netswitch_hook.py` (inside DreamPi) | `switcher` (the numbers matching to `numbers`) | `module.json` `hook` files, as now |
| `netswitch_buttons.py`, `base_gpio.py`, the button settings | `switcher` (its own service) | `led` has its own GPIO driver copy-free: it imports nothing from here (the LED output uses its own small register code) |
| update / reboot marks, `update_info()`, `ADDON_*` | `rebootupdate` | files `updateinfo`, `update`, `reboot` read by `led` |
| `WIFI_*`, Wi-Fi button | `wifi` | files `wifi`, `wifi_start` ... |
| events paths, `event_reminder()`, `next_event()` | `events` | file `event_reminders.json` read by `led` and `openmenu` |
| players paths, `players_watch()` | `players` | files `players_cache.json`, `players` read by `openmenu`, `led` |
| `LED_*`, `WB_TEST`, SPI, `led_colours.json`, the LED value of every palette colour | `led` | - |
| `OPENMENU_GAMES`, `NUMBERS`, `CLOCK_*`, `IMAGEBG_*` | their modules | - |
| debug log paths and `debug_log()` | the base keeps a generic `log()` (a file and a flag from `project.json`); `debuglog` owns the switch | - |

**Order of work (tests green and a push after each step).**
1. Neutral names: `base/`, `base_*.py`, `project.json`, the installer copies `base/` and `modules/`; a test forbids project words in `base/`.
2. The DreamPi integration files into `switcher` (probes, hook, buttons, gpio); numbers matching into `numbers`; About rows into `system`.
3. The module-owned paths and readers out of `base_core.py`, owner by owner (wifi, rebootupdate, events, players, openmenu, imagebg, numbers, clock, led, switcher).
4. LED colours into the `led` module; tokens resolved by the module that adds them (service); `realColour()` in the page without the word `switcher`.
5. Documentation, and the forbidden-words test switched on for all of `base/`.

Not verified on a Pi: the installer and the hook inside DreamPi are only tested off-hardware, as before; every step keeps that boundary and says so in
`docs/hardware-status.md`.
