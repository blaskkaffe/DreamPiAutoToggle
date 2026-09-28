# DreamPi Netswitch

Switch a DreamPi between **DCNow!** (the normal DreamPi / Dreamcast Live network) and **DCNET** (Flycast's network) from a web page, or by dialing special numbers from the Dreamcast.

It installs as an add-on and changes no DreamPi files, so DreamPi's auto-updates keep working and uninstalling leaves DreamPi exactly as it was.

## Install

On the Pi:
```
git clone https://github.com/blaskkaffe/DreamPiAutoToggle.git
cd DreamPiAutoToggle
sudo ./install.sh
```
Then open **http://dreampi.local** in a browser on the same network.

Options:
- `sudo ./install.sh 8080` puts the web page on another port, if port 80 is taken.
- `sudo ./install.sh --led` adds the status NeoPixel (see below). `--no-led` removes it again.

### Update

```
cd ~/DreamPiAutoToggle && git pull && sudo ./install.sh
```
Your settings (selected network, default network, Auto reset, LED) are kept. If the page still looks old afterwards, reload it in the browser.

### Uninstall

```
sudo /opt/dreampi-netswitch/uninstall.sh
```
This removes the services, the hook and the SPI setting (only if the installer added it), and restarts DreamPi.

## Requirements

- DreamPi 2.x with the current `netlink.py` (eaudunord/Netlink, `dpi2` branch), which contains DreamPi's DCNET support.
- DCNET enabled in `netlink_config.ini` (`[DCNet]` with `enabled = yes`).
- `/boot/noautoupdates.txt` must **not** exist, otherwise `netlink.py` skips its config and DCNET stays off.

If DCNET isn't available, the web page says so and every call goes to DCNow!.

## Phone numbers

| Phone number | Result |
|---|---|
| `111-1111` | Always directs to DCNow! for compatibility with openMenu and standard ISP configs. When **Auto reset** is enabled, dialing it also resets the network to the **default network**. |
| `222-2222` | Selects DCNow! / DreamPi and connects to it. Can be set in the Dreamcast ISP config to always connect to DCNow! |
| `333-3333` | Selects DCNET / FLYCAST and connects to it. Can be set in the Dreamcast ISP config to always connect to DCNET. |
| Any other number | Connects to the currently selected network. Set your Dreamcast ISP config to any 7-digit number to use this feature. |

- The numbers are matched on their last seven digits, so a leading `1` (long-distance prefix), an area code or an outside-line digit doesn't matter. DreamPi often hears an extra leading `1`, for example `13333333`.
- openMenu always dials `111-1111`, so it always gets DCNow! (DCNET wouldn't accept openMenu's login).
- Netlink/XBAND dial codes and DreamPi's built-in `*69` prefix ("this call to DCNET") keep working as before.

## Web page

`http://dreampi.local` updates live, every second.

- **Status box:** shows the **DreamPi** row. Tap it (the small arrow) to also show:
  - **Modem:** what the modem is doing right now, taken from DreamPi's own log: looking for the modem, dial tone on, number dialed, carrier speed, online via DCNow! or DCNET, call ended.
  - **Internet:** whether the Pi can reach the internet and resolve `dreamcast.online`, checked every 30 seconds.
- **Selected network** and the **DCNow! / DreamPi** (orange) and **DCNET / FLYCAST** (blue) buttons to change it.
- **Default network:** a switch, orange for DCNow! or blue for DCNET, that sets which network Auto reset goes back to. DCNow! unless changed.
- **Auto reset:** when ticked, dialing `111-1111` resets the selected network to the default network. Off by default.
- **Phone numbers:** the table above, as a reminder.
- **Debug log:** hidden until you click the button at the bottom (see below).

`http://dreampi.local/api` returns the status as JSON, and `http://dreampi.local/status` as plain text:
```
network=dcnet
default=dcnow
autoreset=off
dreampi=Ready for calls
modem=Dial tone on, waiting for a call
internet=Connected (18 ms)
```

## Status colours

The dot next to **DreamPi** on the web page and the optional NeoPixel use the same colours:

| Colour | DreamPi status |
|---|---|
| Green | Ready for calls |
| Yellow (blinks on the LED) | Starting up, not answering calls yet |
| Orange | In a call on DCNow! |
| Blue | In a call on DCNET |
| Purple | In another kind of call (e.g. Netlink) |
| Red (blinks on the LED) | DreamPi not running |
| Grey / dim white | State unknown |

## Status NeoPixel (optional)

A single WS2812 / NeoPixel LED can show the DreamPi status next to the Pi.

**Wiring:**
- Data in to **GPIO10** (physical pin 19).
- Power to **3.3 V** (pin 1).
- Ground to **GND** (pin 6).

Powering one pixel from 3.3 V keeps its data input compatible with the Pi's 3.3 V signal. The LED is driven through the Pi's SPI port, which gives accurate NeoPixel timing without special drivers or extra Python packages.

**Install:** run `sudo ./install.sh --led`. This switches on SPI (`dtparam=spi=on` in `config.txt`) and starts the `dreampi-netswitch-led` service. The first time, reboot once (`sudo reboot`) so SPI becomes active; the installer tells you when that's needed. Later updates keep the LED until you run `sudo ./install.sh --no-led`.

**Brightness:** set `NETSWITCH_LED_BRIGHTNESS` (0 to 1, default 0.15) in `/etc/systemd/system/dreampi-netswitch-led.service`, then run `sudo systemctl daemon-reload && sudo systemctl restart dreampi-netswitch-led`.

If the LED stays dark, `systemctl status dreampi-netswitch-led` shows why (for example, SPI not enabled yet).

## Debug log

The debug log is for tracking down calls that go wrong, such as misheard numbers. Click **Debug log** at the bottom of the web page to open it (click again to close it), make sure **Recording** is ticked, and dial. The panel shows one live timeline with millisecond timing:

- what the modem reports while DreamPi listens: each dialed digit (`DTMF 1`), dial tone underruns, calling tones, and its replies (`OK`, `CONNECT 33600`),
- every message DreamPi logs (heard, mode, answering, carrier speed, hang-up),
- the add-on's routing decisions and your button presses.

**Clear** empties it, **Open as text** shows the whole file (`http://dreampi.local/dtmf`), and unticking **Recording** stops recording.

## Checking it works

- The web page shows a red **Add-on not active** box if DreamPi hasn't loaded the add-on or isn't running, and a **DCNET unavailable** box if DreamPi's DCNET support is switched off.
- `sudo grep netswitch /var/log/messages` shows lines like `netswitch: routing 5551234 to DCNET`.
- `cat /tmp/dreampi-netswitch.active` should say `active pid=<DreamPi's process id>`.
