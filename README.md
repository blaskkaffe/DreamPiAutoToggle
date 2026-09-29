# DreamPi Netswitch

An add-on for [DreamPi](https://github.com/Kazade/dreampi), the Raspberry Pi bridge that takes a Sega Dreamcast online through its modem. It needs a working DreamPi and doesn't do anything on its own.

Switch a DreamPi between **DCNow!** (the normal DreamPi / Dreamcast Live network) and **DCNET** (Flycast's network) from a web page, or by dialing special numbers from the Dreamcast.

It changes no DreamPi files, so DreamPi's auto-updates keep working and uninstalling leaves DreamPi exactly as it was.

What you get:
- A live status page at `http://dreampi.local` (also over HTTPS) with buttons to pick the network.
- Special phone numbers that switch the network straight from the Dreamcast.
- Optional status LEDs on GPIO18: one NeoPixel, several, or a strip. They show DreamPi's status and network or internet problems, with colours, effects and LED sections per message.
- An optional Wi-Fi setup button: hold it for 3 seconds and the Pi hosts a temporary "DreamPi WiFi Config" Wi-Fi network with a page to pick and connect to your home Wi-Fi, no keyboard or monitor needed.
- An optional animated Dreamcast-style background for the page.
- A debug log for tracking down calls that go wrong.

**Tested so far:** DreamPi 2.1 on a Raspberry Pi 3 with openMenu 1.7.0. The add-on loads under DreamPi's Python 2.7, and switching to DCNET with `333-3333` works end to end. A single NeoPixel on GPIO18 works too. Several LEDs or a strip, and the Wi-Fi setup button, haven't been tried on real hardware yet; feedback is welcome.

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
- `sudo ./install.sh --wifi-button=17` adds a Wi-Fi setup button on GPIO17 (see [Wi-Fi setup button](#wi-fi-setup-button-optional)). `--no-wifi-button` removes it again.

Options can be combined, for example `sudo ./install.sh --leds=8 --no-https`.

### Update

```
cd ~/DreamPiAutoToggle && git pull && sudo ./install.sh
```
Your settings are kept: selected network, default network, Auto reset, the LED setup and its colours, and the HTTPS certificate. You don't need to repeat `--led`, `--leds=N` or `--wifi-button=N`; the installer remembers them until `--no-led` / `--no-wifi-button`. If the page still looks old afterwards, reload it in the browser.

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

- **Network box:** the selected network (orange for DCNow!, blue for DCNET) with DreamPi's status and its dot underneath, for example "Ready for calls". Tap the box (the small arrow) to show all status rows:
  - **Modem:** what the modem is doing right now, taken from DreamPi's own log: looking for the modem, dial tone on, number dialed, carrier speed, online via DCNow! or DCNET, call ended.
  - **Pi:** CPU use, RAM and temperature on one line (for example "CPU 3%, RAM 128/923MB, 43°C"), with the uptime and the Pi's IP address underneath, plus the Pi's own power and heat warnings (under-voltage, throttling) now and since boot. A weak power supply is a common cause of an unstable Pi, so a red warning box appears at the top of the page while the Pi is short of power or overheating.
  - **Internet:** whether the Pi can reach the internet and resolve `dreamcast.online`, and whether it's connected by Ethernet or Wi-Fi. A red warning box appears at the top of the page when the internet is down.
- The **DCNow! / DreamPi** and **DCNET / FLYCAST** buttons change the selected network.
- **Debug log:** hidden unless switched on in the settings (see below).

### Settings (cogwheel)

The cogwheel in the top right corner opens the settings. Changes are saved straight away; close them with the ✕ or Esc.

**Network**

- **Default network:** a switch, orange for DCNow! or blue for DCNET, that sets which network Auto reset goes back to. DCNow! unless changed.
- **Auto reset:** when ticked, dialing `111-1111` resets the selected network to the default network. Off by default.
- **Debug log:** when ticked, the **Debug log** bar appears at the bottom of the main page. Off by default and remembered per browser.
- **Wi-Fi setup:** only shown when installed with `--wifi-button=N` (see [Wi-Fi setup button](#wi-fi-setup-button-optional)). Starts or stops the same setup the button does.

**Phone numbers:** the table above, as a reminder.

**Appearance**
- **Dreamcast background:** an animated background in the style of the Dreamcast menu (see [Credits](#credits)). Off by default, and remembered per browser, so a phone can leave it off while a PC has it on. It pauses while the page is hidden. The Pi serves the files itself (about 600 KB, fetched once), so it works without internet; browsers without WebGL just show the blue gradient. The buttons are slightly see-through so the background shows through them.

**About:** the add-on's version (date and commit it was installed from), the versions of DreamPi's own scripts `dreampi.py`, `netlink.py` and `dcnow.py` (the dates in their `_version=` lines, which DreamPi's auto-update compares), the Raspberry Pi model and the operating system.

**Status LED** (only shown when LEDs are installed with `--led` or `--leds=N`; the title shows the number of LEDs for a strip)

- **Global brightness** of the LEDs, 0 to 100% (default 8%). The slider is logarithmic: its left half covers 0 to 9%, the range that suits an indicator LED best, and the right half goes up to full brightness for enclosures that need it.
- Two tabs, **DCNow! selected** and **DCNET selected**, each with the full list of LED messages, grouped into **Errors** and **Information** (see [LED messages](#led-messages)). For example, "Ready for calls" can be green with DCNow! selected and blue with DCNET selected.
- Per message:
  - A **tick box** to use it or not. When no ticked message applies, the LED is off.
  - **Colour.**
  - **Effect:** tap it for a small menu. **Solid**, **Blink**, **Breathe** (fading up and down) and **RGB** (cycles through all colours, ignoring the colour set: one round every 20 seconds when slow, every 10 when fast) work on any LED. With a strip there are also **Rainbow**, **Scanner** (a dot sweeping back and forth), **Comet**, **Chase** and **Twinkle**. Every effect except Solid has a **Slow** and a **Fast** speed. With a strip, the same menu sets which **LEDs** the message uses: **All**, or a range such as 1 to 1 or 2 to 8.
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
pi=CPU 7%, RAM 142/926MB, 48°C. Uptime 2 h 5 min, IP: 192.168.1.55.
```

## LED messages

The LEDs show messages about DreamPi and the network. **Wi-Fi setup always outranks everything else** (see [Wi-Fi setup button](#wi-fi-setup-button-optional)), then **errors always have higher priority than information**, and within each group the list is in order of importance (highest priority first):

| Message | Group | Default look | On by default |
|---|---|---|---|
| Wi-Fi setup: choose a network | Wi-Fi setup | Blue, breathing (scanning, on a strip) | Yes |
| Wi-Fi setup: connected | Wi-Fi setup | Green | Yes |
| Wi-Fi setup: couldn't connect | Wi-Fi setup | Red, blinking slowly | Yes |
| No network | Error | Red | Yes |
| No internet | Error | Orange, blinking slowly | Yes |
| Power or heat problem | Error | Pink, breathing slowly | Yes |
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
- **Power or heat problem:** the Pi reports under-voltage or throttling right now, or is at 80 °C or more.
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

**Brightness, colours and effects:** set in the web page's settings (cogwheel). Effects run at 50 frames per second and start from the beginning whenever a message appears or changes (a blink starts lit, a breathe starts bright), and changes show up within a quarter of a second. They're stored in `/opt/dreampi-netswitch/led.json`.

If the LEDs stay dark, `systemctl status dreampi-netswitch-led` shows why.

## Wi-Fi setup button (optional)

A momentary push button gives the Pi a way to join a Wi-Fi network without a keyboard, monitor or SSH: wire it between a GPIO pin and a **GND** pin, hold it for **3 seconds**, and the Pi:

1. Scans for Wi-Fi networks and hosts a temporary, unencrypted Wi-Fi network called **"DreamPi WiFi Config"**, styled like the main page.
2. Connect a phone or PC to it and open `http://192.168.4.1` (most phones prompt for this automatically). Pick a network from the list (or enter one manually, for a hidden network), enter its password if it needs one, and tap **Connect**.
3. The temporary network closes and the Pi tries to join the network you chose.
4. If it gets online, the status LED (if installed) goes solid **green** for a few seconds and everything returns to normal; DreamPi keeps using this Wi-Fi network (and any others saved this way) after a reboot too. If it can't get online, the LED goes **red** for a few seconds and the Pi goes back to step 1, hosting "DreamPi WiFi Config" again so you can try another network or password.

While it's scanning or hosting the setup network, a status LED shows a breathing blue light (a scanning animation instead, with a strip). Holding the button again, or the **Wi-Fi setup** control under Network in the settings, cancels it at any point and returns the Pi to its normal Wi-Fi connection.

**Wiring:** the button between a GPIO pin of your choice (its BCM number is what you pass to `--wifi-button=`) and any **GND** pin. No resistor needed; the Pi's internal pull-up is used, so the pin reads high normally and low while the button is held.

**Install:** `sudo ./install.sh --wifi-button=17` (GPIO17, physical pin 11, is just an example - most free GPIO pins work). This installs `hostapd` and `dnsmasq` with `apt` if they aren't already present (needed to host the setup network) and starts the `dreampi-netswitch-wifi` service. Remove it again with `sudo ./install.sh --no-wifi-button`.

**Not yet verified on real Wi-Fi hardware:** it assumes the classic Raspberry Pi OS network stack (`wpa_supplicant` + `dhcpcd`), and hosting the setup network takes the Wi-Fi interface away from its normal connection while it's up (Ethernet, if connected, keeps working throughout). If your Pi's networking is set up differently (for example NetworkManager), this feature likely won't work; everything else in this add-on is unaffected either way.

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
  - **Wi-Fi setup:** shown while the setup button (or the settings) is scanning, hosting "DreamPi WiFi Config", connecting, or after a failed attempt.
- If the page doesn't open at all, the Pi may have no network connection. With LEDs installed, **No network** shows as solid red.
- If the page is unreachable now and then, or slow to open the first time:
  - Try the Pi's IP address instead of `dreampi.local`. Looking up `.local` names can take a few seconds on some phones and PCs, or fail now and then.
  - Wi-Fi power saving is a common cause of a Pi dropping off the network. The page service switches it off for every Wi-Fi adapter each time it starts; the setting resets on reboot, and the service switches it off again.
  - `journalctl -u dreampi-netswitch -n 50` shows whether the page service restarted or logged an error. It restarts itself within seconds if it ever stops answering.
- With the Wi-Fi setup button installed, `journalctl -u dreampi-netswitch-wifi -n 50` shows what it's doing (scanning, hosting, connecting) and any error.
- `sudo grep netswitch /var/log/messages` shows lines like `netswitch: routing 5551234 to DCNET`.
- `cat /tmp/dreampi-netswitch.active` should say `active pid=<DreamPi's process id>`.

## Credits

This add-on is built for [DreamPi](https://github.com/Kazade/dreampi) by Luke Benstead (Kazade), with DCNET and Netlink support from [eaudunord/Netlink](https://github.com/eaudunord/Netlink). It doesn't include or change any of their code; it only hooks into it while DreamPi runs.

The page's tab icon is the DreamPi logo (without its text) while DCNow! is selected, and the [Flycast](https://github.com/flyinghead/flycast) logo while DCNET (Flycast's network) is selected. The logos belong to the DreamPi and Flycast projects and are used here only to show which network is selected.

The optional **Dreamcast background** comes from the [VMU Icon Maker](http://dcvmuicons.net/maker/) by **Robert Dale Smith** ([source on GitHub](https://github.com/RobertDaleSmith/vmu-icon-maker), MIT License), part of his [DC VMU Icons](http://dcvmuicons.net/) site. The animated scene, its texture, the waves and the cylinder are his work; this add-on only wraps it so it can be switched on and off (`static/dc-background.js`). It runs on [Three.js](https://threejs.org) r128 (MIT License). The licence texts are in `static/LICENSES.txt`.
