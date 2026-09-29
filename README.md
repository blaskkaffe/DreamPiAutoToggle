# DreamPi Netswitch

An add-on for [DreamPi](https://github.com/Kazade/dreampi), the Raspberry Pi bridge that takes a Sega Dreamcast online through its modem. It needs a working DreamPi and doesn't do anything on its own.

Switch a DreamPi between **DCNow!** (the normal DreamPi / Dreamcast Live network) and **DCNET** (Flycast's network) from a web page, or by dialing special numbers from the Dreamcast.

It changes no DreamPi files, so DreamPi's auto-updates keep working and uninstalling leaves DreamPi exactly as it was.

What you get:
- A live status page at `http://dreampi.local` (also over HTTPS) with buttons to pick the network.
- Special phone numbers that switch the network straight from the Dreamcast.
- Optional status LEDs on GPIO18: one NeoPixel, several, or a strip. They show DreamPi's status and network or internet problems, with colours, effects and LED sections per message.
- An optional animated Dreamcast-style background for the page.
- A debug log for tracking down calls that go wrong.

**Tested so far:** DreamPi 2.1 on a Raspberry Pi 3 with openMenu 1.7.0. The add-on loads under DreamPi's Python 2.7, and switching to DCNET with `333-3333` works end to end. A single NeoPixel on GPIO18 works too. Several LEDs or a strip haven't been tried on real hardware yet; feedback is welcome.

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
- `sudo ./install.sh --led` adds one status NeoPixel, and `--leds=30` a chain or strip of 30 (see [Status NeoPixels](#status-neopixels-optional)). `--no-led` removes the LED service again.

Options can be combined, for example `sudo ./install.sh --leds=8 --no-https`.

### Update

```
cd ~/DreamPiAutoToggle && git pull && sudo ./install.sh
```
Your settings are kept: selected network, default network, Auto reset, the LED setup and its colours, and the HTTPS certificate. You don't need to repeat `--led` or `--leds=N`; the installer remembers them until `--no-led`. If the page still looks old afterwards, reload it in the browser.

### Uninstall

```
sudo /opt/dreampi-netswitch/uninstall.sh
```
This removes the web page and LED services, the hook, all settings and the certificate, and restarts DreamPi.

## Requirements

- A working [DreamPi](https://github.com/Kazade/dreampi) 2.x on a Raspberry Pi, with the Dreamcast already able to connect through it.
- The current `netlink.py` ([eaudunord/Netlink](https://github.com/eaudunord/Netlink), `dpi2` branch), which DreamPi 2.x downloads itself and which contains DreamPi's DCNET support.
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
  - **Internet:** whether the Pi can reach the internet and resolve `dreamcast.online`, and whether it's connected by Ethernet or Wi-Fi. A red warning box appears at the top of the page when the internet is down.
- **Selected network**, orange for DCNow! or blue for DCNET, and the **DCNow! / DreamPi** and **DCNET / FLYCAST** buttons to change it.
- **Debug log:** hidden unless switched on in the settings (see below).

### Settings (cogwheel)

The cogwheel in the top right corner opens the settings. Changes are saved straight away; close them with the ✕ or Esc.

**Network**

- **Default network:** a switch, orange for DCNow! or blue for DCNET, that sets which network Auto reset goes back to. DCNow! unless changed.
- **Auto reset:** when ticked, dialing `111-1111` resets the selected network to the default network. Off by default.
- **Debug log:** when ticked, the **Debug log** bar appears at the bottom of the main page. Off by default and remembered per browser.

**Phone numbers:** the table above, as a reminder.

**Appearance**
- **Dreamcast background:** an animated background in the style of the Dreamcast menu (see [Credits](#credits)). Off by default, and remembered per browser, so a phone can leave it off while a PC has it on. It pauses while the page is hidden. The Pi serves the files itself (about 600 KB, fetched once), so it works without internet; browsers without WebGL just show the blue gradient. The buttons are slightly see-through so the background shows through them.

**Status LED** (only shown when LEDs are installed with `--led` or `--leds=N`; the title shows the number of LEDs for a strip)

- **Global brightness** of the LEDs, 0 to 100% (default 8%). The slider is logarithmic: its left half covers 0 to 9%, the range that suits an indicator LED best, and the right half goes up to full brightness for enclosures that need it.
- Two tabs, **DCNow! selected** and **DCNET selected**, each with the full list of LED messages, grouped into **Errors** and **Information** (see [LED messages](#led-messages)). For example, "Ready for calls" can be green with DCNow! selected and blue with DCNET selected.
- Per message:
  - A **tick box** to use it or not. When no ticked message applies, the LED is off.
  - **Colour.**
  - **Effect:** tap it for a small menu. **Solid**, **Blink**, **Breathe** (fading up and down) and **RGB** (cycles through all colours, ignoring the colour set) work on any LED. With a strip there are also **Rainbow**, **Scanner** (a dot sweeping back and forth), **Comet**, **Chase** and **Twinkle**. Every effect except Solid has a **Slow** and a **Fast** speed. With a strip, the same menu sets which **LEDs** the message uses: **All**, or a range such as 1 to 1 or 2 to 8.
  - **Level:** the brightness for that message. Grey means it uses the global brightness; tap it to give the message its own brightness with a slider, and tap **Use global** to go back.
- **Reset LED settings to defaults** restores the defaults in [LED messages](#led-messages) and the 8% global brightness.

The status dot next to DreamPi on the main page previews that status's colour and effect. Network problems show as red warning boxes at the top of the page instead.

`http://dreampi.local/api` returns the status as JSON, and `http://dreampi.local/status` as plain text:
```
network=dcnet
default=dcnow
autoreset=off
dreampi=Ready for calls
modem=Dial tone on, waiting for a call
internet=Connected via Ethernet (18 ms)
```

## LED messages

The LEDs show messages about DreamPi and the network. **Errors always have higher priority than information**, and within each group the list is in order of importance (highest priority first):

| Message | Group | Default look | On by default |
|---|---|---|---|
| No network | Error | Red | Yes |
| No internet | Error | Orange, blinking slowly | Yes |
| DreamPi not running | Error | Red, blinking slowly | Yes |
| State unknown | Error | Dim grey | Yes |
| Starting up | Information | Yellow, blinking slowly | Yes |
| In a call on DCNow! | Information | Orange | Yes |
| In a call on DCNET | Information | Blue | Yes |
| In another call (Netlink) | Information | Purple | Yes |
| Ready for calls | Information | Green | Yes |
| Ethernet connected | Information | White | No |
| Wi-Fi connected | Information | Light blue | No |

- **No network:** the Pi has no route to your router, for example because the cable is unplugged or Wi-Fi isn't connected. You can't open the web page then, so the LED is the only thing that can tell you.
- **No internet:** the Pi reaches your router, but not the internet, or name lookups (DNS) fail.
- **Checking speed:** cables, Wi-Fi and the route are checked every 2 seconds. The internet is checked every 30 seconds while it works, every 5 seconds while it doesn't, and straight away when a connection changes.
- **Several messages at once:**
  - On a single LED, or when messages all use all LEDs, the most important one shows.
  - With a strip, each message draws on its own LEDs, less important ones first, so an error on "All" takes over the whole strip.
  - Give the errors LED 1 and "Ready for calls" LEDs 2 to 8, and LED 1 stays dark until something goes wrong while 2 to 8 keep showing DreamPi.
  - LEDs that no active message covers stay dark.

## Status NeoPixels (optional)

A single WS2812 / NeoPixel LED, several of them in a chain, or a WS2812 strip can show DreamPi's status and network problems next to the Pi.

**Wiring, single LED:**
- Data in to **GPIO18** (physical pin 12).
- Power to **3.3 V** (pin 1).
- Ground to **GND** (pin 6).

Powering one pixel from 3.3 V keeps its data input compatible with the Pi's 3.3 V signal.

**Wiring, several LEDs or a strip:**
- Data in (DIN) to **GPIO18** (pin 12), ideally through a 300-500 ohm resistor.
- Power the strip from **5 V**. A few LEDs at the low default brightness can use the Pi's 5 V pin (pin 2). Longer strips need their own 5 V supply, since each LED can draw up to 60 mA at full white.
- Connect the strip's ground to the Pi's **GND** (pin 6) in every case.
- Strips powered from 5 V usually accept the Pi's 3.3 V data signal. If yours flickers or shows wrong colours, add a 3.3 V to 5 V level shifter (for example a 74AHCT125).

**Install:**
- One LED: `sudo ./install.sh --led`
- Several LEDs or a strip: `sudo ./install.sh --leds=30` (the number of LEDs, 1 to 300)

This starts the `dreampi-netswitch-led` service; no reboot is needed. Later updates keep the LED setting until you run `sudo ./install.sh --no-led`. If an older version switched on SPI for the LED, the installer removes that setting again.

**How it works:** the LEDs are driven by the Pi's PWM hardware on GPIO18, clocked from the crystal, which gives accurate NeoPixel timing without special drivers, extra Python packages or config changes. A single LED is fed directly; a strip is fed by a DMA channel from memory shared with the GPU, the same method the rpi_ws281x library uses. PWM is also what the Pi's analog (3.5 mm jack) audio uses, so don't play sound through the jack while the LEDs are running; DreamPi doesn't use it.

**Brightness, colours and effects:** set in the web page's settings (cogwheel). Effects run at 50 frames per second, and changes show up within a quarter of a second. They're stored in `/opt/dreampi-netswitch/led.json`.

If the LEDs stay dark, `systemctl status dreampi-netswitch-led` shows why.

## Debug log

The debug log is for tracking down calls that go wrong, such as misheard numbers. Tick **Debug log** under Network in the settings, then click the **Debug log** bar at the bottom of the main page to open it (click again to close it), press **Recording off** so it changes to **Recording**, and dial. The panel shows one live timeline with millisecond timing:

- what the modem reports while DreamPi listens: each dialed digit (`DTMF 1`), dial tone underruns, calling tones, and its replies (`OK`, `CONNECT 33600`),
- every message DreamPi logs (heard, mode, answering, carrier speed, hang-up),
- the add-on's routing decisions and your button presses.

**Clear** empties it, and pressing **Recording** again stops recording. **Newest 256 KB** and **Full log** open the log as plain text in a new tab (`http://dreampi.local/dtmf` and `http://dreampi.local/dtmf?all`). While recording, the log keeps its newest 500 KB to 1 MB, so it can't fill the SD card or get slow to open.

## Checking it works

- The web page shows red warning boxes at the top when something is wrong:
  - **Add-on not active:** DreamPi hasn't loaded the add-on or isn't running. Restart DreamPi or reboot.
  - **DCNET unavailable:** DreamPi's DCNET support is switched off (see [Requirements](#requirements)).
  - **No internet:** the Pi reaches your router but not the internet, or name lookups fail.
- If the page doesn't open at all, the Pi may have no network connection. With LEDs installed, **No network** shows as solid red.
- `sudo grep netswitch /var/log/messages` shows lines like `netswitch: routing 5551234 to DCNET`.
- `cat /tmp/dreampi-netswitch.active` should say `active pid=<DreamPi's process id>`.

## Credits

This add-on is built for [DreamPi](https://github.com/Kazade/dreampi) by Luke Benstead (Kazade), with DCNET and Netlink support from [eaudunord/Netlink](https://github.com/eaudunord/Netlink). It doesn't include or change any of their code; it only hooks into it while DreamPi runs.

The page's tab icon is the DreamPi logo (without its text) while DCNow! is selected, and a purple Dreamcast swirl while DCNET is selected. The DreamPi logo belongs to the DreamPi project, and the Dreamcast swirl is a trademark of SEGA; they're used here only to identify what the page is for.

The optional **Dreamcast background** comes from the [VMU Icon Maker](http://dcvmuicons.net/maker/) by **Robert Dale Smith** ([source on GitHub](https://github.com/RobertDaleSmith/vmu-icon-maker), MIT License), part of his [DC VMU Icons](http://dcvmuicons.net/) site. The animated scene, its texture, the waves and the cylinder are his work; this add-on only wraps it so it can be switched on and off (`static/dc-background.js`). It runs on [Three.js](https://threejs.org) r128 (MIT License). The licence texts are in `static/LICENSES.txt`.
