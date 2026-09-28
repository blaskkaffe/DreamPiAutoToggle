# DreamPi Netswitch

Switch a DreamPi between **DC Now** (normal DreamPi / Dreamcast Live) and **DCNet** (Flycast's network) from a web page or by dialing special numbers from the Dreamcast. It installs as an add-on and changes no DreamPi files, so DreamPi's auto-updates keep working and uninstalling leaves DreamPi exactly as it was.

## How calls are routed

| Number dialed | Result |
|---|---|
| `111-1111` | openMenu's built-in number. Always DC Now. If **reset** is on, the selection also goes back to DC Now. |
| `222-2222` | Selects DC Now and connects through DC Now. |
| `333-3333` | Selects DCNet and connects through DCNet. |
| Any other number | Connects through the currently selected network. |

Netlink/XBAND dial codes and DreamPi's built-in `*69` prefix are not affected. If DCNet is not enabled in `netlink_config.ini`, all calls go to DC Now.

Setting a game's or the browser's ISP number to `333-3333` makes it always use DCNet. Other numbers follow the website.

The special numbers must arrive exactly as those seven digits. An area code, outside-line digit or dial prefix set in the ISP settings becomes part of the number, and then the call just follows the selected network. (DreamPi's own `*69` prefix still works and still means "this call to DCNet".)

## Web page

`http://dreampi.local` shows the selected network, buttons for **Use DC Now** / **Use DCNet**, and the **reset on openMenu connect** toggle (off by default).

`http://dreampi.local/status` returns plain text, for example:
```
network=dcnet
autoreset=off
```

## Install

On the Pi:
```
git clone https://github.com/blaskkaffe/DreamPiAutoToggle.git
cd DreamPiAutoToggle
sudo ./install.sh          # or: sudo ./install.sh 8080  if port 80 is taken
```
Running it again updates the add-on and keeps your settings.

## Uninstall

```
sudo /opt/dreampi-netswitch/uninstall.sh
```

## Requirements

- DreamPi 2.x with the current `netlink.py` (eaudunord/Netlink, `dpi2` branch), which contains DreamPi's DCNet support.
- DCNet enabled in `netlink_config.ini` (`[DCNet]` with `enabled = yes`).
- `/boot/noautoupdates.txt` must **not** exist, otherwise `netlink.py` skips its config and DCNet stays off.

## Checking it works

- The web page shows a red **Add-on not active** box if DreamPi has not loaded the hook or is not running, and a **DCNet unavailable** box if DreamPi's DCNet support is switched off.
- `sudo grep netswitch /var/log/messages` shows lines like `netswitch: routing 5551234 to DCNet`.
- `cat /tmp/dreampi-netswitch.active` should say `active pid=<DreamPi's process id>`.
