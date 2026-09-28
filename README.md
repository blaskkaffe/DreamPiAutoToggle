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
Then open **http://dreampi.local** or **https://dreampi.local** in a browser on the same network. If `dreampi.local` doesn't resolve on a device, use the Pi's IP address instead.

### HTTPS

Some browsers refuse or keep upgrading plain `http://` pages, so the page is also served over HTTPS on port 443. A Pi on a home network can't get a certificate from a public authority, so the installer makes its own (self-signed) certificate:

- The first time you open `https://dreampi.local`, the browser warns that the connection isn't private. Choose **Advanced** and **Proceed** (the wording varies); most browsers remember that choice for the site.
- The traffic is still encrypted; the warning only means no public authority vouches for the certificate.
- The certificate is valid for about 2 years (Apple devices won't accept longer). Running the installer renews it when it has less than 30 days left.
- `http://` keeps working as before.

Options:
- `sudo ./install.sh 8080` puts the HTTP page on another port, if port 80 is taken.
- `sudo ./install.sh --https-port=8443` puts the HTTPS page on another port, and `--no-https` turns it off.
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
This removes the services and the hook, and restarts DreamPi.

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
- **Debug log:** hidden until you click the button at the bottom (see below).

### Settings (cogwheel)

The cogwheel in the top right corner opens the settings. Changes are saved straight away; close them with the ✕ or Esc.

- **Default network:** a switch, orange for DCNow! or blue for DCNET, that sets which network Auto reset goes back to. DCNow! unless changed.
- **Auto reset:** when ticked, dialing `111-1111` resets the selected network to the default network. Off by default.
- **Phone numbers:** the table above, as a reminder.
- **Status LED:**
  - **Brightness** of the NeoPixel, 0 to 100% (default 15%).
  - A **colour** and **blink** setting for every DreamPi status, set separately for when DCNow! is selected and when DCNET is selected. For example, "Ready for calls" can be green with DCNow! selected and blue with DCNET selected.
  - **Reset LED settings to defaults** restores the table below.

  The status dot on the page uses the same colours, so it works as a preview even without an LED.

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

The dot next to **DreamPi** on the web page and the optional NeoPixel show the same colour, set in the settings. The defaults are the same for both networks:

| Colour | DreamPi status |
|---|---|
| Green | Ready for calls |
| Yellow, blinking | Starting up, not answering calls yet |
| Orange | In a call on DCNow! |
| Blue | In a call on DCNET |
| Purple | In another kind of call (e.g. Netlink) |
| Red, blinking | DreamPi not running |
| Dim grey | State unknown |

## Status NeoPixel (optional)

A single WS2812 / NeoPixel LED can show the DreamPi status next to the Pi.

**Wiring:**
- Data in to **GPIO18** (physical pin 12).
- Power to **3.3 V** (pin 1).
- Ground to **GND** (pin 6).

Powering one pixel from 3.3 V keeps its data input compatible with the Pi's 3.3 V signal. The LED is driven by the Pi's PWM hardware on GPIO18, clocked from the crystal, which gives accurate NeoPixel timing without special drivers, extra Python packages or config changes. PWM is also what the Pi's analog (3.5 mm jack) audio uses, so don't play sound through the jack while the LED is running; DreamPi doesn't use it.

**Install:** run `sudo ./install.sh --led`. This starts the `dreampi-netswitch-led` service; no reboot is needed. Later updates keep the LED until you run `sudo ./install.sh --no-led`. If an older version switched on SPI for the LED, the installer removes that setting again.

**Brightness and colours:** set in the web page's settings (cogwheel); the LED picks up changes within half a second. They're stored in `/opt/dreampi-netswitch/led.json`.

If the LED stays dark, `systemctl status dreampi-netswitch-led` shows why.

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
