# DreamPi Netswitch

An add-on for [DreamPi](https://github.com/Kazade/dreampi), the Raspberry Pi bridge that takes a Sega Dreamcast online through its modem. It needs a working DreamPi and doesn't do anything on its own.

Switch a DreamPi between **DCNow!** (the normal DreamPi / Dreamcast Live network) and **DCNET** (Flycast's network) from a web page, or by dialing special numbers from the Dreamcast.

It changes no DreamPi files, so DreamPi's auto-updates keep working and uninstalling leaves DreamPi exactly as it was.

What you get:
- A live status page at `http://dreampi.local` (also over HTTPS) with buttons to pick the network.
- Special phone numbers that switch the network straight from the Dreamcast.
- Optional status LEDs, on GPIO18 by default or GPIO10/12/21: one NeoPixel, several, or a strip. They show DreamPi's status and network or internet problems, with colours, effects, LED sections per message and a quick white-balance calibration.
- Two GPIO buttons (always installed, each with its own pin and function, such as toggling the network), and optional Wi-Fi setup (`--wifi`): hold a button for 3 seconds and the Pi hosts a temporary "DreamPi WiFi Config" Wi-Fi network with a page to pick and connect to your home Wi-Fi, no keyboard or monitor needed.
- An optional animated Dreamcast-style background for the page.
- A debug log for tracking down calls that go wrong.
- Modem plugged-in detection and its make/model, with a warning if it's not a modem known to work with DreamPi.

**Tested so far:** DreamPi 2.1 on a Raspberry Pi 3 with openMenu 1.7.0. The add-on loads under DreamPi's Python 2.7, and switching to DCNET with `555-0002` works end to end. A single NeoPixel on GPIO18 works too. Several LEDs or a strip, the new LED colour calibration/wire order/dithering, the GPIO10/12/21 output pins, and the Wi-Fi setup button (including the newer second button, per-button function and combined-hold assignment), haven't been tried on real hardware yet; feedback is welcome.

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
- The status NeoPixel is on by default (1 LED on GPIO18). `sudo ./install.sh --leds=30` sets the starting count for a chain or strip of 30 (the count can also be changed later in Settings), and `--leds=0` turns the LEDs off and hides the LED settings; `--led-gpio=10`/`12`/`21` uses a different pin than the default GPIO18 (see [Status NeoPixels](#status-neopixels-optional)). The older `--led`, `--led=N` and `--no-led` still work.
- `sudo ./install.sh --wifi` adds Wi-Fi setup: the temporary access point for joining a network without a keyboard (installs `hostapd` and `dnsmasq`), plus its Settings controls and the button hold that starts it (see [Wi-Fi setup button](#buttons-and-wi-fi-setup)). `--no-wifi` removes it again. The two buttons themselves (GPIO17 and GPIO4 by default) are always installed.

Options can be combined, for example `sudo ./install.sh --leds=8 --no-https`.

### Update

```
cd ~/DreamPiAutoToggle && git pull && sudo ./install.sh
```
Your settings are kept: selected network, default network, Auto reset, the LED setup and its colours, and the HTTPS certificate. You don't need to repeat `--leds=N` or `--wifi`; the installer remembers them (`--leds=0` / `--no-wifi` switch them off). If the page still looks old afterwards, reload it in the browser.

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

Five actions, each with its own list of numbers that you edit in **Settings > Phone numbers** (add with the field and **Add**, remove with the ✕, **Restore default numbers** puts the list below back):

| Action | What it does | Default number |
|---|---|---|
| **Reset** | Selects the **default network** and hangs up | `111-1111#` |
| **Toggle to DCNow!** | Selects DCNow! / DreamPi and hangs up | `555-0001#` |
| **Toggle to DCNET** | Selects DCNET / FLYCAST and hangs up | `555-0002#` |
| **Call DCNow!** | Selects DCNow! / DreamPi **and** connects to it | `555-0001` |
| **Call DCNET** | Selects DCNET / FLYCAST **and** connects to it | `555-0002` |

Fixed, not editable: `111-1111` always directs to DCNow! for compatibility with openMenu and standard ISP configs (when **Auto reset** is enabled, dialing it also resets the network to the default network), and any other number connects to the currently selected network (set your Dreamcast ISP config to any 7-digit number to use this feature).

**Hang-up actions** (Reset, Toggle): DreamPi doesn't answer. The add-on changes the selection and plays a busy tone for 4 seconds, so the Dreamcast gives up straight away instead of waiting for an answer. After that the normal dial tone comes back and the next call goes to the newly selected network. Use it to change networks from the Dreamcast without opening the web page.

**What counts as a number:** digits, `*` and `#`, 3 to 24 characters, either a whole number or just an ending, for example `*61#` or `0002`. A number counts when what the Dreamcast dialed **ends with** it, so a leading `1` (long-distance prefix), an area code, an outside-line digit or other digits the ISP config puts in front don't matter (DreamPi often hears an extra leading `1`, for example `15550002`), and the longest matching number wins. A number can only belong to one action, and a short ending can't take over openMenu's `111-1111`. Take care with very short endings: anything the Dreamcast dials that ends with it will trigger the action.

- `555-0001` and `555-0002` (the North American fictional-exchange prefix) replace the older `222-2222`/`333-3333`: a run of seven identical digits is the hardest pattern for a DTMF decoder to count correctly (no frequency change marks a digit boundary, only a timing gap), the same kind of issue the [Debug log](#debug-log) helps track down for misheard numbers. If you had `222-2222` or `333-3333` set in a Dreamcast ISP config, update it to the new numbers.
- openMenu always dials `111-1111`, so it always gets DCNow! (DCNET wouldn't accept openMenu's login).
- Netlink/XBAND dial codes and DreamPi's built-in `*69` prefix ("this call to DCNET") keep working as before.

## Web page

`http://dreampi.local` updates live, every second.

- **Network box:** the selected network (orange for DCNow!, blue for DCNET) with DreamPi's status and its dot underneath, for example "Ready for calls". Tap the box (the small arrow) to show all status rows:
  - **Modem:** what the modem is doing right now, taken from DreamPi's own log: looking for the modem, dial tone on, number dialed, carrier speed, online via DCNow! or DCNET, call ended. A red warning box appears if the modem's USB connection goes away, or if it's a modem not known to work with DreamPi (its make/model, read from its USB info - nothing is ever sent to the modem itself - shows in the **About** card in Settings, with a note if it isn't a known-working one).
  - **Pi:** CPU use, RAM and temperature on one line (for example "CPU 3%, RAM 128/923MB, 43°C"), with the uptime and the Pi's IP address underneath, plus the Pi's own power and heat warnings (under-voltage, throttling) now and since boot. A weak power supply is a common cause of an unstable Pi, so a red warning box appears at the top of the page while the Pi is short of power or overheating.
  - **Internet:** whether the Pi can reach the internet and resolve `dreamcast.online`, and whether it's connected by Ethernet or Wi-Fi. A red warning box appears at the top of the page when the internet is down.
  - **Hang up** (at the bottom when the box is open, only while DreamPi is in a call): ends a call that got stuck and gets the modem ready again. Tap it twice to confirm. It ends the call the way DreamPi ends one itself, by stopping `pppd` for DCNow! or `dcnet.rpi` for DCNET, after which DreamPi hangs up the modem and starts the dial tone. If DreamPi isn't ready for calls within 30 seconds, or the call process is already gone, it restarts the DreamPi service.
- The **DCNow! / DreamPi** and **DCNET / FLYCAST** buttons change the selected network.
- **Debug log:** hidden unless switched on in the settings (see below).

### Settings (cogwheel)

The cogwheel in the top right corner opens the settings. Changes are saved straight away; close them with the ✕ or Esc. On a wide screen the sections flow into as many columns as fit (up to four), so there is less scrolling; a phone keeps the single column.

**Network**

- **Default network:** a switch, orange for DCNow! or blue for DCNET, that sets which network Auto reset goes back to. DCNow! unless changed.
- **Auto reset:** when ticked, dialing `111-1111` resets the selected network to the default network. Off by default.
- **Debug log:** when ticked, the **Debug log** bar appears at the bottom of the main page. Off by default and remembered per browser.
- **Wi-Fi setup:** only shown when Wi-Fi setup was installed with `--wifi` (see [Wi-Fi setup button](#buttons-and-wi-fi-setup)). Starts or stops the same setup the button does, and while it's scanning or hosting, lists the networks it found right here too - tap one, enter its password if it needs one, and connect - which also works if this page is still reachable some other way (for example over Ethernet) while the Wi-Fi is being set up.

**Phone numbers:** the five lists above, editable here, plus the two fixed rows as a reminder.

**Appearance**
- **Dreamcast background:** an animated background in the style of the Dreamcast menu (see [Credits](#credits)). Off by default, and remembered per browser, so a phone can leave it off while a PC has it on. It pauses while the page is hidden. The Pi serves the files itself (about 600 KB, fetched once), so it works without internet; browsers without WebGL just show the blue gradient. The buttons are slightly see-through so the background shows through them.

**GPIO** (shown when LEDs are installed and not hidden, buttons are installed, or both) - all the physical/wiring settings, in one card, one row per device:

- **LED:** **LEDs connected** (1 to 300, just where the count starts out), **output pin** (GPIO10, 12, 18 or 21) and **wire order** (`RGB`, `RBG`, `GRB` - most WS2812 strips, `GBR`, `BRG` or `BGR`; wrong order shows the right brightness with the wrong colour, for example a red status looking green). All three take effect within a second.
- **Button 1** / **Button 2:** each button's **function** and **pin**. Two kinds of function, in two groups in the list: **Push button** (acts on a short press) - **Off**, **Toggle network** (switches between DCNow! and DCNET, the default for button 1), **Select DCNow!** or **Select DCNET** (the default for button 2 is **Off**) - and **Toggle switch** (a latching on/off switch wired between the pin and GND, **on = closed**, which decides the state by its position, also when the Pi starts): **On = DCNET** (on selects DCNET, off selects DCNow!), **On = DCNow!** (the other way round), and, with Wi-Fi setup installed, **On = Wi-Fi setup** (flip it on to start Wi-Fi setup, off to end it and go back to normal) or **Off = Wi-Fi setup** (the opposite position starts it). A text under the row spells out the chosen function. For example: button 1 as a push button that toggles the network (hold it for Wi-Fi setup), or button 1 as an on/off network switch and button 2 as a Wi-Fi setup switch. The pin (see [Wi-Fi setup button](#buttons-and-wi-fi-setup) for the physical wiring and defaults, GPIO17 and GPIO4). Pick two different pins; a change takes effect within a couple of seconds, no reinstall needed.
- **Wi-Fi setup:** which push button, or **Button 1 + 2** held together, starts Wi-Fi setup with a 3-second hold (a button set to a toggle switch function can't be held, so it's ignored here). A button's own short-press function above still works normally either way - only a press that's actually held long enough to start Wi-Fi setup skips it.

**NeoPixel calibration** and **Status LED** (only shown when the LED count is above 0 - `--leds=0` hides them - and not hidden, see below; the Status LED title shows the number of LEDs for a strip) - how the LEDs look, separate from the GPIO wiring settings above. The calibration box holds the white-balance sliders and the brightness:

- **White balance:** three sliders, **Red**, **Green** and **Blue** (0 to 255, all at 255 by default - no correction). Tap **Preview on LED** to hold the LED at solid white, then turn down whichever channel looks too strong until it looks neutral white rather than tinted - leave the others at 255, don't turn any of them up. Tap **Preview on LED** again (now labelled **Stop preview**) when you're done; it also stops automatically if you close Settings. **Reset to neutral** sets all three back to 255. This corrects every colour the LEDs show, not just white, and takes about 30 to 60 seconds - there's no need to calibrate individual colours.
- **Brightness** (the maximum brightness) of the LEDs, in the same box as the white balance, 0 to 100% (default 8%), applied after white balance as a ceiling on the whole strip regardless of colour. The slider is logarithmic: its left half covers 0 to 9%, the range that suits an indicator LED best, and the right half goes up to full brightness for enclosures that need it.
- Two tabs, **DCNow! selected** and **DCNET selected**, each with the full list of LED messages, grouped into **Errors** and **Information** (see [LED messages](#led-messages)). For example, "Ready for calls" can be green with DCNow! selected and blue with DCNET selected.
- Per message:
  - A **tick box** to use it or not. When no ticked message applies, the LED is off.
  - **Colour.**
  - **Effect:** tap it for a small menu. **Solid**, **Blink**, **Breathe** (fading up and down) and **RGB** (cycles through all colours, ignoring the colour set: one round every 20 seconds when slow, every 10 when fast) work on any LED. With a strip there are also **Rainbow**, **Scanner** (a dot sweeping back and forth), **Comet**, **Chase** and **Twinkle**. Every effect except Solid has a **Slow** and a **Fast** speed. With a strip, the same menu sets which **LEDs** the message uses: **All**, or a range such as 1 to 1 or 2 to 8.
  - **Level:** the brightness for that message. Grey means it uses the maximum brightness above; tap it to give the message its own brightness with a slider, and tap **Use global** to go back.
- **Reset LED settings to defaults** restores the defaults in [LED messages](#led-messages) and the 8% maximum brightness (not the white balance - that describes your LEDs, not a look to reset).
- **Hide these settings:** removes the whole Status LED section from Settings, for shipping a Pi with the LEDs already set up and keeping them from being changed by accident. There's a confirmation, because the only way back is deleting `led_hidden` in `/opt/dreampi-netswitch` on the Pi itself (or reinstalling).

**About:** the add-on's version (date and commit it was installed from), the versions of DreamPi's own scripts `dreampi.py`, `netlink.py` and `dcnow.py` (the dates in their `_version=` lines, which DreamPi's auto-update compares), the Raspberry Pi model, the operating system, and - once a modem has been detected - its make/model, with a note if it isn't a known-working one.

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

The LEDs show messages about DreamPi and the network. **Wi-Fi setup always outranks everything else** (see [Wi-Fi setup button](#buttons-and-wi-fi-setup)), then **errors always have higher priority than information**, and within each group the list is in order of importance (highest priority first):

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

A single WS2812 / NeoPixel LED, several of them in a chain, or a WS2812 strip can show DreamPi's status and network problems next to the Pi, on any of four GPIO pins.

**Wiring, single LED, on GPIO18 (physical pin 12, the default):**
- Data in to **GPIO18** (pin 12).
- Power to **3.3 V** (pin 1).
- Ground to **GND** (pin 6).

Powering one pixel from 3.3 V keeps its data input compatible with the Pi's 3.3 V signal.

**Wiring, several LEDs or a strip, on GPIO18:**
- Data in (DIN) to **GPIO18** (pin 12), ideally through a 300-500 ohm resistor.
- Power the strip from **5 V**. A few LEDs at the low default brightness can use the Pi's 5 V pin (pin 2). Longer strips need their own 5 V supply, since each LED can draw up to 60 mA at full white.
- Connect the strip's ground to the Pi's **GND** (pin 6) in every case.
- Strips powered from 5 V usually accept the Pi's 3.3 V data signal. If yours flickers or shows wrong colours, add a 3.3 V to 5 V level shifter (for example a 74AHCT125).

**Other pins:** the same wiring, just to a different data pin - **GPIO10** (pin 19), **GPIO12** (pin 32) or **GPIO21** (pin 40) - and, for GPIO10 only, with SPI enabled first (see Install below). Use another pin if GPIO18 is wanted for something else, or to keep the analog audio jack free (it also uses PWM, which GPIO12 and GPIO18 both drive the LEDs through; GPIO21 uses a different peripheral, PCM, instead).

**Install:**
- One LED on the default pin (GPIO18): nothing to do, it's on by default
- Several LEDs or a strip: `sudo ./install.sh --leds=30` (the number of LEDs, 0 to 300; only the starting count, it can be changed later in Settings > GPIO; `0` turns the LED off and hides the LED settings)
- A different pin: add `--led-gpio=10`, `--led-gpio=12` or `--led-gpio=21` (GPIO18 is the default; can be combined with `--leds=N`). **GPIO10 needs a reboot**: the installer enables SPI in `config.txt` for it, which only takes effect after rebooting, so the LEDs stay dark on that pin until then.

This starts the `dreampi-netswitch-led` service; other than switching to GPIO10, no reboot is needed. Later updates keep the LED count and pin. If an older version switched on SPI for the LED, the installer removes that setting again unless GPIO10 is still selected. The LED count and pin can both be changed later from the page's settings too (Settings > GPIO), without rerunning the installer - except switching *to* GPIO10 that way still needs SPI already enabled by `--led-gpio=10` beforehand, since enabling it needs root and a reboot that the page can't do itself; switching to it without that just leaves the LEDs dark until either SPI is enabled or another pin is picked again.

**How it works:** GPIO12 and GPIO18 are driven by the Pi's PWM hardware, clocked from the crystal, which gives accurate NeoPixel timing without special drivers, extra Python packages or config changes; GPIO21 uses the PCM peripheral the same way, so the LEDs don't need the PWM hardware (and therefore not the analog audio jack) at all. A single LED on GPIO12/18 is fed directly; anything else on GPIO12/18/21 is fed by a DMA channel from memory shared with the GPU, the same method the rpi_ws281x library uses. GPIO10 instead goes through the kernel's own SPI driver (`dtparam=spi=on`), one SPI byte per NeoPixel bit - what this add-on used by default in its very first versions, before it moved to GPIO18.

**Brightness, colours and effects:** set in the web page's settings (cogwheel). Effects run at 50 frames per second and start from the beginning whenever a message appears or changes (a blink starts lit, a breathe starts bright), and changes show up within a quarter of a second. They're stored in `/opt/dreampi-netswitch/led.json`.

If the LEDs stay dark, `systemctl status dreampi-netswitch-led` shows why.

## Buttons and Wi-Fi setup

Two momentary push buttons are always installed, as quick network switches and (with `--wifi`) a way to join a Wi-Fi network without a keyboard, monitor or SSH: **button 1** on **GPIO17 (physical pin 11)**, function **Toggle network** by default, and **button 2** on **GPIO4 (physical pin 7)**, **Off** by default. Wire each between its GPIO pin and a **GND** pin. Pins and functions (and, with `--wifi`, which button or both together starts Wi-Fi setup) are all editable later from Settings > GPIO (see [Settings](#settings-cogwheel)) - no reinstall needed.

- **A short press** on a button runs its own function: **Off** (nothing), **Toggle network** (switches between DCNow! and DCNET, the same as the web page's two buttons or dialing `555-0001`/`555-0002`), **Select DCNow!** or **Select DCNET** (selects that network outright, whatever was selected before).
- **Holding the assigned button(s) for 3 seconds** starts Wi-Fi setup (only if installed with `--wifi`; without it a long press is just a slow short press) - by default that's button 1 alone, but Settings > GPIO can assign it to button 2 instead, or to both buttons held down together. Whichever button(s) that is, their own short-press function above still works normally on a short press; only a press that's actually held long enough to start Wi-Fi setup skips it. Once started, the Pi:

1. Scans for Wi-Fi networks and hosts a temporary, unencrypted Wi-Fi network called **"DreamPi WiFi Config"**, styled like the main page.
2. Connect a phone or PC to it and open `http://192.168.4.1` (most phones prompt for this automatically) - or, if the Pi's regular page is still reachable some other way (for example over Ethernet), open its Settings instead; the same network list appears there too (see [Settings](#settings-cogwheel)). Pick a network from the list (or enter one manually, for a hidden network), enter its password if it needs one, and tap **Connect**.
3. The temporary network closes and the Pi tries to join the network you chose.
4. If it gets online, the status LED (if installed) goes solid **green** for a few seconds and everything returns to normal; DreamPi keeps using this Wi-Fi network (and any others saved this way) after a reboot too. If it can't get online, the LED goes **red** for a few seconds and the Pi goes back to step 1, hosting "DreamPi WiFi Config" again so you can try another network or password.

While it's scanning or hosting the setup network, a status LED shows a breathing blue light (a scanning animation instead, with a strip). Holding the assigned button(s) again, or the **Wi-Fi setup** control under Network in the settings, cancels it at any point and returns the Pi to its normal Wi-Fi connection.

**Wiring:** no resistor needed; the Pi's internal pull-up is used on each pin, so it reads high normally and low while that button is held. GPIO17 and GPIO4 were picked as the defaults because neither has any other function on any Raspberry Pi model (an earlier version of this add-on defaulted the single button to GPIO15, which doubles as the Pi's UART RX pin and could pick up noise from the serial console/Bluetooth if that's in use). A pin or function change from Settings > GPIO takes effect within a couple of seconds, with no service restart. A toggle switch is wired the same way, between the pin and GND (any simple on/off switch; closed = on).

**Install:** the buttons come with every install and run as the `dreampi-netswitch-buttons` service. `sudo ./install.sh --wifi` additionally enables Wi-Fi setup and installs `hostapd` and `dnsmasq` with `apt` if they aren't already present (needed to host the setup network); remove just that again with `sudo ./install.sh --no-wifi`.

**Not yet verified on real Wi-Fi hardware:** it assumes the classic Raspberry Pi OS network stack (`wpa_supplicant` + `dhcpcd`), and hosting the setup network takes the Wi-Fi interface away from its normal connection while it's up (Ethernet, if connected, keeps working throughout). If your Pi's networking is set up differently (for example NetworkManager), this feature likely won't work; everything else in this add-on is unaffected either way. A single button on GPIO17 was tried on real hardware in an earlier version of this add-on; the two-button, per-button-function and combined-hold generalisation described above has not been.

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
- `journalctl -u dreampi-netswitch-buttons -n 50` shows what the buttons and Wi-Fi setup are doing (scanning, hosting, connecting) and any error.
- `sudo grep netswitch /var/log/messages` shows lines like `netswitch: routing 5551234 to DCNET`.
- `cat /tmp/dreampi-netswitch.active` should say `active pid=<DreamPi's process id>`.

## Credits

This add-on is built for [DreamPi](https://github.com/Kazade/dreampi) by Luke Benstead (Kazade), with DCNET and Netlink support from [eaudunord/Netlink](https://github.com/eaudunord/Netlink). It doesn't include or change any of their code; it only hooks into it while DreamPi runs.

The page's tab icon is the DreamPi logo (without its text) while DCNow! is selected, and the [Flycast](https://github.com/flyinghead/flycast) logo while DCNET (Flycast's network) is selected. The logos belong to the DreamPi and Flycast projects and are used here only to show which network is selected.

The optional **Dreamcast background** comes from the [VMU Icon Maker](http://dcvmuicons.net/maker/) by **Robert Dale Smith** ([source on GitHub](https://github.com/RobertDaleSmith/vmu-icon-maker), MIT License), part of his [DC VMU Icons](http://dcvmuicons.net/) site. The animated scene, its texture, the waves and the cylinder are his work; this add-on only wraps it so it can be switched on and off (`static/dc-background.js`). It runs on [Three.js](https://threejs.org) r128 (MIT License). The licence texts are in `static/LICENSES.txt`.
