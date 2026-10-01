# Notes for Claude Code

## Goal and hard rules
- Add-on for DreamPi (Raspberry Pi bridge for the Sega Dreamcast modem) that routes calls to DC Now or DCNet.
- **Never modify DreamPi's own files** (`/home/pi/dreampi/dreampi.py`, `netlink.py`, `dcnow.py`). DreamPi auto-updates them from GitHub, and the add-on must install and uninstall cleanly without touching them.
- `netswitch_hook.py` runs inside DreamPi, which runs on **Python 2.7**. Keep it Python 2 and 3 compatible: no f-strings, no type hints, no Python-3-only stdlib. The web page runs separately under Python 3.
- Behaviour-changing work: run `sh tests/run.sh` before committing and add a test for a fixed bug. Keep README.md and the matching `docs/` file accurate in the same commit, including whether something is **verified on hardware** (see `docs/hardware-status.md`; never claim hardware behaviour that was only simulated).

## Naming in the UI
User-facing text (web page, README, log lines) spells the networks **DCNow!** and **DCNET**; the buttons read "DCNow! / DreamPi" and "DCNET / FLYCAST". Code identifiers, file names and upstream strings keep their original spelling (`dcnow`, `dcnet`, `[DCNet]` in `netlink_config.ini`, DreamPi's `DCNet Call answered` log text).

## Module map
- Modules (Python 3 services, flat files in `/opt/dreampi-netswitch`): `netswitch_core.py` = all path constants, state-file readers (DreamPi/modem/network/Wi-Fi), debug log, button settings; no server, imported by everyone. `netswitch_ledconfig.py` = LED settings (`led.json` validation, count, pin, hidden, white-balance test flag), the LED message list (`LED_STATES`) and `active_messages()`; imports core. `netswitch_probes.py` = what the web service measures (internet/link checks, `pi_health()`, hang up, versions, modem identification, the `checker()` loop); imports core. `netswitch_web.py` = HTTP side (`api_state()`, handlers, HTTPS, watchdog, page assembly); imports both. `netswitch_led.py` (what to show: effects, colour pipeline, render, main loop) uses `netswitch_led_drivers.py` (WS2812 output on PWM/PCM/SPI: encoding, `open_output()`); `netswitch_buttons.py` (GPIO buttons: debounce, hold, short-press functions, config reload) uses `netswitch_wifi_setup.py` (scan, access point, connect, `setup_cycle()`) only when `wifi_enabled()`. LED and buttons import only core/ledconfig/probes/gpio and must never import `netswitch_web` (tests enforce it). Path constants live only in core; other modules read them as `core.NAME`. `netswitch_hook.py` is standalone and Python 2 compatible.
- `install.sh` copies files to `/opt/dreampi-netswitch`, writes `dreampi_netswitch.pth` into site-packages for `python`, `python2` and `python3` (the list is kept in `pth_locations`), creates and starts the `dreampi-netswitch` systemd service (web page), and restarts the `dreampi` service. It also copies `netswitch_gpio.py` (shared low-level GPIO register access) and the other modules in the map above, and always creates/starts the `dreampi-netswitch-buttons` service (the two GPIO buttons); `--wifi` only adds Wi-Fi setup on top (marker `wifi_enabled`, `hostapd`/`dnsmasq`), see `docs/buttons-wifi.md`. Older installs had one `dreampi-netswitch-wifi` service/`netswitch_wifi.py`/`wifi_button_enabled` marker for both; install.sh migrates the marker and removes the old service on update. `--led[=N]` is one option: bare `--led` keeps the existing LED count (1 on a fresh install), `--led=N` sets the starting count (1-300); the old separate `--leds=N` is gone.

## State is in files (cross-process; no sockets between services)
- `/opt/dreampi-netswitch/`: `dcnet_mode` (exists = DCNet selected), `autoreset`, `default_dcnet`, `debug_dtmf`, `led.json`, `led_enabled`/`led_count`/`led_gpio`/`led_hidden`, `button1_gpio`/`button2_gpio`/`button1_function`/`button2_function`/`wifi_button`, `wifi_enabled`, `wifi_start`/`wifi_stop`/`wifi_connect`, `version`, `https.crt`/`https.key`. All paths are constants in `netswitch_core.py`.
- `/tmp/dreampi-netswitch.*`: `active`, `state`, `modem`, `port` (written by the hook), `net` (web service -> LED), `wifi` (Wi-Fi setup -> web/LED), `wbtest`; `/tmp/dreampi-netswitch-dtmf.log` is the debug timeline.
- Details of each: see the docs below.

## Read the right doc before changing an area
| Area | Read |
|---|---|
| Hook inside DreamPi, phone-number routing, debug log, upstream `netlink.py` facts | `docs/hook.md` |
| Web page (`page/`), API, HTTPS, hang up, Pi health, modem identification | `docs/web.md` |
| LED messages, `led.json`, colour calibration, white-balance test, NeoPixel drivers | `docs/led.md` |
| GPIO settings box, buttons (debounce/hold), Wi-Fi setup | `docs/buttons-wifi.md` |
| What is / is not verified on real hardware | `docs/hardware-status.md` |

## Testing without a Pi
`sh tests/run.sh` runs the off-hardware tests (`tests/`: buttons debounce/hold, Wi-Fi setup helpers, LED pipeline and render, web config + HTTP round trips on a random port with all paths redirected into a temp dir, page JS syntax and id references, hook Python 2 syntax guard, layering, shell syntax). `tests/support.py` has `sandbox()` for redirecting paths. The routing test that needs the real `netlink.py` is described in `docs/hook.md` and is not in the suite. To look at the page, serve `netswitch_web.Server` from a script that calls `support.sandbox()` and screenshot it with Playwright (Chromium is pre-installed).

## Ideas for later
- Let openMenu read `/status` over plain HTTP to show the selected network.
- Show DCNet player counts on the page, for example by relaying DC99 / dcnet.flyca.st data.
- Make the special numbers configurable in a small config file.
