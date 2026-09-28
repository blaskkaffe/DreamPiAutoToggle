# Notes for Claude Code

## Goal and hard rules
- Add-on for DreamPi (Raspberry Pi bridge for the Sega Dreamcast modem) that routes calls to DC Now or DCNet.
- **Never modify DreamPi's own files** (`/home/pi/dreampi/dreampi.py`, `netlink.py`, `dcnow.py`). DreamPi auto-updates them from GitHub, and the add-on must install and uninstall cleanly without touching them.
- `netswitch_hook.py` runs inside DreamPi, which runs on **Python 2.7**. Keep it Python 2 and 3 compatible: no f-strings, no type hints, no Python-3-only stdlib. The web page runs separately under Python 3.

## Naming in the UI
User-facing text (web page, README, log lines) spells the networks **DCNow!** and **DCNET**; the buttons read "DCNow! / DreamPi" and "DCNET / FLYCAST". Code identifiers, file names and upstream strings keep their original spelling (`dcnow`, `dcnet`, `[DCNet]` in `netlink_config.ini`, DreamPi's `DCNet Call answered` log text).

## How it works
- `install.sh` copies files to `/opt/dreampi-netswitch`, writes `dreampi_netswitch.pth` into site-packages for `python`, `python2` and `python3` (the list is kept in `pth_locations`), creates and starts the `dreampi-netswitch` systemd service (web page), and restarts the `dreampi` service.
- The `.pth` file imports `netswitch_hook`. It only acts when `/proc/self/cmdline` contains `dreampi` (`sys.argv` doesn't exist yet during `.pth` processing on Python 2). It then temporarily wraps `__import__`, using `__builtin__` before `builtins` because python-future can provide a fake `builtins` on Python 2. When a module named `netlink` is imported from `/home/pi/dreampi`, it wraps `Netlink.check_number()` and restores the original `__import__`.
- State lives in files: `/opt/dreampi-netswitch/dcnet_mode` (exists means DCNet is selected), `/opt/dreampi-netswitch/autoreset` (reset toggle) and `/opt/dreampi-netswitch/default_dcnet` (exists means auto reset returns to DCNet instead of DC Now; page: `POST /default`). The hook writes `/tmp/dreampi-netswitch.active` (`active pid=N` or an error). The hook also writes `/tmp/dreampi-netswitch.state` (`starting`, `ready`, `call <network>` or `unknown`, plus a unix time): `starting` when netlink is imported, `call ...` from `check_number()`, and `ready` after `__main__.Modem.start_dial_tone()` (the moment DreamPi logs `<LISTENING>`) or `Netlink.reset_serial()`. The web page checks that pid under `/proc`, and also reads `netlink_config.ini` and `/boot/noautoupdates.txt` to warn when DCNet is off.
- Modem status: the hook adds a `logging.Handler` to DreamPi's `dreampi` logger and maps DreamPi's own messages (`<LISTENING>`, `Heard:`, `CONNECT 33600`, `Call answered`, `Connected`, `Detected modem hang up`, ...) to a short text in `/tmp/dreampi-netswitch.modem` (`<unix time> <text>`). Table `_MODEM_EVENTS`; keep it in sync if upstream log texts change.
- HTTPS: `install.sh` makes a self-signed certificate (`https.crt`/`https.key` in `/opt/dreampi-netswitch`, SAN `dreampi.local`, `<hostname>.local`, the Pi's IPv4 addresses; 820 days because Apple rejects > 825; renewed by the installer when < 30 days are left) with `openssl req -config` (no `-addext`, for older OpenSSL). The web service is started as `netswitch_web.py <http port> <https port>` (443 by default, `0` = off, `--https-port=N` / `--no-https`). The HTTPS server runs in a second thread; the TLS handshake happens in each request's thread (`finish_request`), so a browser sitting on the certificate warning can't block the accept loop. If the certificate is missing or the port is taken, HTTP keeps working. Both servers are threading (`ThreadingMixIn`).
- The web page works on Python 3 and 2.7. It serves a static page that polls `GET /api` (JSON) every 2 s; buttons POST via XMLHttpRequest (plain form POST + 303 still works without JS). A background thread checks internet every 30 s. The debug panel is hidden behind a "Debug log" toggle button; the log is only polled while it is open. The status box shows only the DreamPi row until it is clicked, which reveals the Modem and Internet rows.

## Status NeoPixel
`netswitch_led.py` (Python 3, service `dreampi-netswitch-led` running as root, installed with `install.sh --led`, remembered via `/opt/dreampi-netswitch/led_enabled`, removed with `--no-led`) imports `netswitch_web` and shows `dreampi_state()` on one WS2812 on **GPIO18** (PWM0, physical pin 12). No driver or package: it maps the GPIO, clock-manager and PWM register blocks from `/dev/mem` (peripheral base read from `/proc/device-tree/soc/ranges`; 32-bit accesses via `ctypes.c_uint32.from_buffer`), sets GPIO18 to ALT5, runs the PWM clock from the crystal (19.2 MHz / 8 = 2.4 MHz; Pi 4: 54 MHz / 22) and uses serialiser mode with the FIFO: 3 PWM bits per LED bit (`100` = 0, `110` = 1), 72 bits = 3 FIFO words, GRB order, MSB first. With `RPTL1` off the pin idles low when the FIFO empties, which latches the colour. It resends every 0.5 s. Analog audio also uses PWM; DreamPi doesn't play sound. Colours match the page's dot classes (`ok`, `busy`, `call-dcnow`, `call-dcnet`, `call`, `off`, `unknown`); `busy` and `off` blink. Older versions used SPI on GPIO10 and added `dtparam=spi=on  # added by dreampi-netswitch` (recorded in `spi_added`); the installer and uninstaller remove only that line.

## Debug log
If `/opt/dreampi-netswitch/debug_dtmf` exists, the hook writes one timeline to `/tmp/dreampi-netswitch-dtmf.log` (`HH:MM:SS.mmm  +Nms  text`):
- modem bytes read while `modem._sending_tone` is true, decoded by `_serial_feed()`: `<DLE><digit>` -> `modem: DTMF x`, other `<DLE>` codes via `_DLE_CODES` (V.253), text lines -> `modem says: ...`. The hook replaces `read` on the pyserial object again after every `start_dial_tone()`, since DreamPi opens a new serial object after each call;
- every message on DreamPi's `dreampi` logger (`dreampi: ...`), via the same handler as the modem status;
- the number `check_number()` received (`add-on: number heard ...`) and routing lines.
The web page appends its own actions (`web page: ...`), serves new text incrementally at `GET /log?from=<byte offset>` (JSON; `reset` when the file was cleared), shows it live in a panel polled every 0.7 s, and has `POST /debug` (toggle) and `POST /clearlog`. The page's status poll runs every 1 s. Note the page's HTML/JS lives in a Python string: write `\\n` for a JavaScript `\n`.

Open question being investigated: on hardware DreamPi heard openMenu's `1111111` as `11111111`, `1111` and `1`. Known contributors: (1) `digit_parser()` in netlink.py reads the digit right after `<DLE>` on a non-blocking port (`timeout=0`); if the byte hasn't arrived yet the digit is dropped and parsing restarts at the next `<DLE>` (reproduced in simulation). (2) openMenu's KallistiOS `modem_dial()` dials immediately after opening the line, without waiting for dial tone, using the modem chip's default DTMF timing. The debug log on real hardware decides which it is. Do not paper over it in the routing rules; the user wants the cause fixed.

## Upstream facts the hook depends on (netlink.py, dpi2 branch)
- `check_number(self, raw_string)` returns `{'client': mode, 'dial_string': ...}`. `dreampi.py` answers with its own pppd only when `client == 'PPP'`. Any other non-idle mode is handled by `Netlink.poll()` -> `mode_handler()`.
- Mode `"dcnet"` makes `mode_handler()` call `dcnet_connect()`, which answers and runs `dcnet.rpi`. This is the same route the built-in `*69` prefix uses: it stores `self.dial_modifier` in memory, valid for 10 seconds.
- `self.dcnet` is True only when `netlink_config.ini` has `[DCNet] enabled = yes` and `dcnet.rpi` exists.
- The serial-port path (`serial_poll`) also calls `check_number()` and handles `"dcnet"`.
- openMenu 1.7.0 always dials `1111111` with login `openMenu`/`openMenu` (see `dcnow_net.h` in DerekPascarella/openMenu-Virtual-Folder-Bundle). DCNet expects the password `password`, so `1111111` must stay on DC Now.
- If upstream renames `check_number`, the hook writes an error to the status file and does nothing, and DreamPi keeps working.

## Routing rules (see README table)
Special numbers are matched with `endswith()` on the dialed string: on real hardware DreamPi hears an extra leading `1` (e.g. `13333333`, `11111111`), and ISP prefixes add digits too. Only calls the original `check_number` returns as `PPP` are redirected. Numbers ending in `1111111` or `2222222` always stay PPP. `3333333`, or any number while `dcnet_mode` exists, becomes `dcnet` if `self.dcnet` is true. With `autoreset`, `1111111` first sets the selection to the default network (`default_dcnet`); the openMenu call itself still stays PPP.

## Testing without a Pi
Download the current `netlink.py`, place it at `/home/pi/dreampi/netlink.py`, stub the `serial`, `stun` and `sh` modules, load the `.pth` with `site.addsitedir()`, create the object with `Netlink.__new__(Netlink)`, set `logger`, `servers`, `dcnet`, `dial_modifier` and `mode`, then call `check_number()` for each rule. Also check that `netlink.py`'s hash is unchanged afterwards.

## Verified on hardware
- The hook loads and patches under DreamPi's real Python 2.7.
- A real DCNet call end to end via 333-3333.

## Not yet verified
- The GPIO18 PWM NeoPixel driver on real hardware (register sequence only tested against fake memory).
- Whether port 80 is free on every DreamPi image.

## Ideas for later
- Let openMenu read `/status` over plain HTTP to show the selected network.
- Show DCNet player counts on the page, for example by relaying DC99 / dcnet.flyca.st data.
- Make the special numbers configurable in a small config file.
