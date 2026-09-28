# Notes for Claude Code

## Goal and hard rules
- Add-on for DreamPi (Raspberry Pi bridge for the Sega Dreamcast modem) that routes calls to DC Now or DCNet.
- **Never modify DreamPi's own files** (`/home/pi/dreampi/dreampi.py`, `netlink.py`, `dcnow.py`). DreamPi auto-updates them from GitHub, and the add-on must install and uninstall cleanly without touching them.
- `netswitch_hook.py` runs inside DreamPi, which runs on **Python 2.7**. Keep it Python 2 and 3 compatible: no f-strings, no type hints, no Python-3-only stdlib. The web page runs separately under Python 3.

## How it works
- `install.sh` copies files to `/opt/dreampi-netswitch`, writes `dreampi_netswitch.pth` into site-packages for `python`, `python2` and `python3` (the list is kept in `pth_locations`), creates and starts the `dreampi-netswitch` systemd service (web page), and restarts the `dreampi` service.
- The `.pth` file imports `netswitch_hook`, which temporarily wraps `builtins.__import__`. When a module named `netlink` is imported from `/home/pi/dreampi`, it wraps `Netlink.check_number()` and then restores the original `__import__`. Every other program is left alone.
- State lives in files: `/opt/dreampi-netswitch/dcnet_mode` (exists means DCNet is selected) and `/opt/dreampi-netswitch/autoreset` (reset toggle). The hook writes `/tmp/dreampi-netswitch.active` (`active` or an error), which the web page shows.

## Upstream facts the hook depends on (netlink.py, dpi2 branch)
- `check_number(self, raw_string)` returns `{'client': mode, 'dial_string': ...}`. `dreampi.py` answers with its own pppd only when `client == 'PPP'`. Any other non-idle mode is handled by `Netlink.poll()` -> `mode_handler()`.
- Mode `"dcnet"` makes `mode_handler()` call `dcnet_connect()`, which answers and runs `dcnet.rpi`. This is the same route the built-in `*69` prefix uses: it stores `self.dial_modifier` in memory, valid for 10 seconds.
- `self.dcnet` is True only when `netlink_config.ini` has `[DCNet] enabled = yes` and `dcnet.rpi` exists.
- The serial-port path (`serial_poll`) also calls `check_number()` and handles `"dcnet"`.
- openMenu 1.7.0 always dials `1111111` with login `openMenu`/`openMenu` (see `dcnow_net.h` in DerekPascarella/openMenu-Virtual-Folder-Bundle). DCNet expects the password `password`, so `1111111` must stay on DC Now.
- If upstream renames `check_number`, the hook writes an error to the status file and does nothing, and DreamPi keeps working.

## Routing rules (see README table)
Only calls the original `check_number` returns as `PPP` are redirected. `1111111` and `2222222` always stay PPP. `3333333`, or any number while `dcnet_mode` exists, becomes `dcnet` if `self.dcnet` is true.

## Testing without a Pi
Download the current `netlink.py`, place it at `/home/pi/dreampi/netlink.py`, stub the `serial`, `stun` and `sh` modules, load the `.pth` with `site.addsitedir()`, create the object with `Netlink.__new__(Netlink)`, set `logger`, `servers`, `dcnet`, `dial_modifier` and `mode`, then call `check_number()` for each rule. Also check that `netlink.py`'s hash is unchanged afterwards.

## Not yet verified
- Running under real Python 2.7 on a Pi.
- A real DCNet call end to end.
- Whether port 80 is free on every DreamPi image.

## Ideas for later
- Let openMenu read `/status` over plain HTTP to show the selected network.
- Show DCNet player counts on the page, for example by relaying DC99 / dcnet.flyca.st data.
- Make the special numbers configurable in a small config file.
