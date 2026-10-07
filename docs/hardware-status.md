# What is verified on real hardware

Check this before saying something works. Anything not listed under Verified has only been tried in simulation or unit tests. Update it whenever the user reports a hardware result. Back to [CLAUDE.md](../CLAUDE.md).

## Verified on hardware

Nothing yet in this version of the add-on (the check-in board, the contacts and the kiosk script are new). The base it grew out of (the module system, the page kit, the update and reboot controls, the clock) ran on a Raspberry Pi as part of the DreamPi network switcher, but the page has been rebuilt since and none of it has been re-checked here.

## Not yet verified

- **The check-in board** (`modules/checkin/`, the `roster` widget): tested off-hardware in Chromium against the demo server (`sh tests/ui/run.sh`: at four widths, tapping, the status menu, a second browser page following the first within about two seconds, the buildings filter, the settings, the CSV import) and by unit tests. **Not seen on a Pi, on a touch screen, on a TV or with more than two browser windows at once.** How it looks and feels on the real screens (button size, the 1 s refresh) is unconfirmed.
- **Several screens on one host:** only two Chromium pages against one demo server were tried. Whether a Pi 3 / Zero serves 10+ screens polling `/api` once a second is untested; the answer carries the whole board (a few kilobytes per hundred people).
- **Kiosk mode** (`kiosk/kiosk-browser.sh`, the autostart file): never run. It is adapted from CheckinChicken's script, which is the reference.
- **Contacts import** from a real CSV exported by Excel or Google Sheets (encodings, delimiters): comma, semicolon and tab and a BOM are handled and tested with made-up files only.
- **The module system** (`modules/<name>/`, Settings > System > Modules, `netswitch_modules.py`, the module picker with drag and drop: mouse and keyboard tested in Chromium, touch dragging with touch events in a phone-sized Chromium context, **not on a real iPhone / Safari**): tested off-hardware. **Not run on a Pi:** the clean-up of an install from the DreamPi version (the old services, the `.pth` files and the files of the removed modules, including the old Wi-Fi setup module's service, folder and state files, are removed by `install.sh`; only checked as shell syntax).
- **Web-service safety** (Host / Origin checks, the optional PIN, update origin pinning, the systemd sandbox directives on `dreampi-netswitch.service`): tested off-hardware (`tests/test_security.py`, the PIN prompt flow driven in a browser). Not run on a Pi: whether the sandboxed unit starts and still reboots / starts the update on every Raspberry Pi OS version, and `install.sh --pin` on a real terminal. See [web.md](web.md#security-netswitch_securitypy).
- **Update check and Update now:** the GitHub comparison is tested against fake responses and the update script against a local git origin with a stub installer; the real GitHub API calls and the `systemd-run` + `runuser` launch have not run on a Pi. The default repository is still `blaskkaffe/DreamPiAutoToggle`, branch `main`: the page offers whatever the installed checkout's origin and branch say.
- **Reboot:** the endpoint is tested; the reboot itself (`systemctl reboot` after 2 s) has not been run on a Pi.
- **The clock** (12 / 24 h, .beat, world times, the time-zone map, summer time with and without `zoneinfo`): tested off-hardware; the time-zone reader is checked against `zoneinfo` for every listed zone.
