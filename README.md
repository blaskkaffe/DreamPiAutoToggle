# DreamPi Netswitch

Switch a DreamPi between **DC Now** (normal DreamPi / Dreamcast Live) and **DCNet** (Flycast's network) from a web page or by dialing special numbers from the Dreamcast. It installs as an add-on and changes no DreamPi files, so DreamPi's auto-updates keep working and uninstalling leaves DreamPi exactly as it was.

## How calls are routed

| Number dialed | Result |
|---|---|
| `111-1111` | openMenu's built-in number. Always DC Now. If **Auto reset** is on, the selection also goes back to the **default network**. |
| `222-2222` | Selects DC Now and connects through DC Now. |
| `333-3333` | Selects DCNet and connects through DCNet. |
| Any other number | Connects through the currently selected network. |

Netlink/XBAND dial codes and DreamPi's built-in `*69` prefix are not affected. If DCNet is not enabled in `netlink_config.ini`, all calls go to DC Now.

Setting a game's or the browser's ISP number to `333-3333` makes it always use DCNet. Other numbers follow the website.

The special numbers are matched on their last seven digits, so a leading `1`, an area code or an outside-line digit doesn't matter (DreamPi often hears an extra leading `1`, for example `13333333`). DreamPi's own `*69` prefix still works and still means "this call to DCNet".

## Web page

`http://dreampi.local` updates live (every second). The status box at the top shows only the **DreamPi** row; tap it (the small arrow) to show the Modem and Internet rows as well:

- **DreamPi:** starting up, ready for calls, in a call (and on which network), or not running.
- **Modem:** what the modem is doing right now, taken from DreamPi's own log: looking for the modem, dial tone on, number dialed, carrier speed, online via DC Now or DCNet, call ended.
- **Internet:** whether the Pi can reach the internet and resolve `dreamcast.online` (checked every 30 seconds).
- The selected network and the **Use DC Now** / **Use DCNet** buttons.
- **Default network:** a switch (orange DC Now! / blue DCNet) that sets which network Auto reset returns to. DC Now unless changed.
- **Auto reset:** when ticked, dialing openMenu's `111-1111` switches the selection back to the default network (off by default). openMenu's own call always uses DC Now, since DCNet won't accept openMenu's login.

`http://dreampi.local/api` returns everything as JSON, and `http://dreampi.local/status` as plain text, for example:
```
network=dcnet
default=dcnow
autoreset=off
dreampi=Ready for calls
modem=Dial tone on, waiting for a call
internet=Connected (18 ms)
```

## Status colours

The dot next to **DreamPi** on the web page, and the optional NeoPixel, use the same colours:

| Colour | DreamPi status |
|---|---|
| Green | Ready for calls |
| Yellow (blinks on the LED) | Starting up, not answering calls yet |
| Orange | In a call on DC Now |
| Blue | In a call on DCNet |
| Purple | In another kind of call (e.g. Netlink) |
| Red (blinks on the LED) | DreamPi not running |
| Grey / dim white | State unknown |

## Status NeoPixel (optional)

A single WS2812 / NeoPixel LED can show the DreamPi status next to the Pi.

**Wiring:** data in to **GPIO10** (physical pin 19), power to **3.3 V** (pin 1) and ground to **GND** (pin 6). Running one pixel from 3.3 V keeps its data input compatible with the Pi's 3.3 V signal. The LED is driven through SPI, which gives accurate NeoPixel timing without special drivers.

**Install:** `sudo ./install.sh --led`. This switches on SPI (`dtparam=spi=on` in `config.txt`), installs `python3-spidev` and starts the `dreampi-netswitch-led` service. Reboot once the first time so SPI becomes active. Later updates keep the LED; `sudo ./install.sh --no-led` removes it again. Brightness is set with `NETSWITCH_LED_BRIGHTNESS` (0 to 1, default 0.15) in `/etc/systemd/system/dreampi-netswitch-led.service`.

## Debug log

The debug log is hidden by default. Click **Debug log** at the bottom of the web page to open it (click again to close), make sure **Recording** is on, and dial. The panel shows one live timeline with millisecond timing:

- what the modem reports while DreamPi listens: each dialed digit (`DTMF 1`), dial tone underruns, calling tones, and its replies (`OK`, `CONNECT 33600`),
- every message DreamPi logs (heard, mode, answering, carrier speed, hang-up),
- the add-on's routing decisions and your button presses.

**Clear** empties it, **Open as text** shows the whole file (`http://dreampi.local/dtmf`), and switching **Recording** off stops recording.

## Install

On the Pi:
```
git clone https://github.com/blaskkaffe/DreamPiAutoToggle.git
cd DreamPiAutoToggle
sudo ./install.sh          # or: sudo ./install.sh 8080  if port 80 is taken
                           # add --led for the status NeoPixel on GPIO10
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
