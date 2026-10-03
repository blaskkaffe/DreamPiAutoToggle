# DreamPi Netswitch

An add-on for [DreamPi](https://github.com/Kazade/dreampi), the Raspberry Pi bridge that takes a Sega Dreamcast online through its modem. It needs a working DreamPi and doesn't do anything on its own.

Switch a DreamPi between **DCNow!** (the normal DreamPi / Dreamcast Live network) and **DCNET** (Flycast's network) from a web page, or by dialing special numbers from the Dreamcast.

It changes no DreamPi files, so DreamPi's auto-updates keep working and uninstalling leaves DreamPi exactly as it was.

<p align="center"><img src="docs/images/main-page.jpg" alt="The main page on a phone, with the Dreamcast background module on: selected network, the two network buttons and the online players box" width="320"></p>

What you get:
- A live status page at `http://dreampi.local` (also over HTTPS) with buttons to pick the network.
- Special phone numbers that switch the network straight from the Dreamcast.
- Optional status LEDs, on GPIO18 by default or GPIO10/12/21: one NeoPixel, several, or a strip. They show DreamPi's status and network or internet problems, with colours, effects, LED sections per message and a quick white-balance calibration.
- Two GPIO buttons (always installed, each with its own pin and function, such as toggling the network), and optional Wi-Fi setup (`--wifi`): hold a button for 3 seconds and the Pi hosts a temporary "DreamPi WiFi Config" Wi-Fi network with a page to pick and connect to your home Wi-Fi, no keyboard or monitor needed.
- An optional animated Dreamcast-style background for the page.
- An online players box (who is on DCNow! and DCNET, and in which games), and a debug log for tracking down calls that go wrong.
- Update and reboot buttons on the page, and an optional PIN for them.
- Modem plugged-in detection and its make/model, with a warning if it's not a modem known to work with DreamPi.

**Tested so far:** DreamPi 2.1 on a Raspberry Pi 3 with openMenu 1.7.0. The add-on loads under DreamPi's Python 2.7, and switching to DCNET by dialing a number (`555-0002` in that test; it is no longer a default) works end to end. The Toggle numbers (switch only, with the busy tone) haven't been tried on hardware yet. A single NeoPixel on GPIO18 works too. Several LEDs or a strip, the new LED colour calibration/wire order/dithering, the GPIO10/12/21 output pins, and the Wi-Fi setup button (including the newer second button, per-button function and combined-hold assignment), haven't been tried on real hardware yet; feedback is welcome.

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
- Every install makes sure `hostapd` and `dnsmasq` are installed (with `apt`, only if missing), because Wi-Fi setup needs them to host its temporary access point. `sudo ./install.sh --wifi` switches Wi-Fi setup on: the temporary access point for joining a network without a keyboard, plus its Settings controls and the button hold that starts it (see [Wi-Fi setup button](#buttons-and-wi-fi-setup)); you can also switch it on in Settings > Modules. `--no-wifi` switches it off again. To try the Wi-Fi flow without any Wi-Fi hardware, `--wifi-demo` runs Wi-Fi setup on dummy networks (password `demo` connects, anything else fails) without touching the Pi's network; `--no-wifi-demo` ends it. The two buttons themselves (GPIO17 and GPIO4 by default) are always installed.

- `sudo ./install.sh --pin` asks for a PIN (`--pin=1234` gives it on the command line, which shows in the shell history); `--no-pin` removes it. See [Safety](#safety).

Options can be combined, for example `sudo ./install.sh --leds=8 --no-https`.

### Update

The page can do it for you while the **Reboot and Update** module is on (see [Modules](#modules)): **Settings > System** (the last rows of the System card) checks GitHub for a newer version of this add-on (and tells you if DreamPi has newer scripts), and **Update now** fetches and installs it from the checkout you installed from (settings and ports are kept; the page is gone for a few seconds). By hand, which is what the rest of this section describes:

```
cd ~/DreamPiAutoToggle && git pull && sudo ./install.sh
```
DreamPi itself needs no manual update: it updates its own scripts when the Pi starts and has internet (restart the Pi to get a newer version). If `/boot/noautoupdates.txt` exists it does not update itself; remove that file first.

Your settings are kept: which modules are on, the LED setup and its colours, and the HTTPS certificate. An install from before the modules were folders is converted by the update: its old flat files are removed and the modules are installed from `modules/` (an old Wi-Fi setup install stays on). You don't need to repeat `--leds=N`, `--wifi` or the port options; the installer remembers them (`--leds=0` / `--no-wifi` switch them off, `--https-port=443` turns HTTPS back on after `--no-https`). If the page still looks old afterwards, reload it in the browser.

### Safety

The web page runs on the Pi as root, because it has to restart DreamPi, reboot the Pi and run the updater. There are no user accounts: **anybody who can reach the page on your network can use it**, so only put the Pi on a network you trust, and don't forward its ports from the internet. What the add-on does to limit the risk:

- **PIN (optional).** `sudo ./install.sh --pin` sets a PIN that the page asks for (once per page load) before **Update now**, **Reboot** and **Wi-Fi connect**. It is stored only as a salted hash, can only be set or removed from the Pi itself (`--pin` / `--no-pin`, never from the page), and five wrong tries lock those three actions for a minute. Use the `https://` address when you use a PIN: over plain `http://` the PIN travels unencrypted. Forgot it? `sudo ./install.sh --no-pin`. Without a PIN, anybody on your network can update or reboot the Pi.
- **Other websites can't use it.** Every change (all `POST`s) must come from the page itself: a request from another site (a form or script on a web page you have open in your browser) is refused, and so is a request that reaches the Pi under a name that isn't the Pi's (the trick used to attack devices on a home network from a web page). The page answers to IP addresses, `dreampi.local`-style names and the Pi's own host name; if your router gives it another domain name and the page says "Unknown host name", list that name in `/opt/dreampi-netswitch/allowed_hosts` (one per line). The page can't be shown inside another site's frame.
- **Update now is limited to GitHub.** It only pulls from the git address the checkout had when the add-on was installed (it must be a GitHub address, and a changed one is refused), fetches from exactly that address, and only fast-forwards, so it can't pull in changes that don't continue your copy.
- **The web service is fenced in** (systemd: no new privileges, read-only `/usr`, `/boot` and `/etc`, no kernel-module or cgroup changes) and the add-on's files in `/opt/dreampi-netswitch` are root-owned.
- **Not covered:** someone who is already logged in on the Pi (or can run code on it) can do more than this add-on ever could, and the status files in `/tmp` are guessable names (the update's status file is not written through a planted link). The Wi-Fi setup access point is open by design while you set up Wi-Fi: it closes itself after 10 minutes if nobody picks a network, but don't start it where you don't want others to join.

### Modules

The add-on is a small **base** plus **modules**. The base is the web page with the Selected-network box, the two network buttons, the buttons' GPIO settings, Modules and System, and the hook inside DreamPi that does the routing. Everything else is a module, a folder in `modules/`:

| Module | Folder | Adds | On by default |
|---|---|---|---|
| **Special phone numbers** | `modules/numbers/` | Settings > Special phone numbers, to edit the numbers the Dreamcast dials. Without it the built-in default numbers are used | yes |
| **Online players** | `modules/players/` | the Online players box on the main page | yes |
| **Wi-Fi setup** | `modules/wifi/` | joining a Wi-Fi network without a keyboard (a temporary access point), and the Wi-Fi rows in Settings | no |
| **Status LEDs** | `modules/led/` | the NeoPixel service, the Status LED settings (including the calibration pop-up), and the LED count / GPIO pin / wire order | yes |
| **Dreamcast background** | `modules/background/` | the animated Dreamcast menu background behind the page (see [Credits](#credits)) | no |
| **Reboot and Update** | `modules/rebootupdate/` | the Updates rows (check GitHub, **Update now**) in the System card and the Reboot card | yes |
| **Debug log** | `modules/debuglog/` | the Debug log bar and live log on the main page, and its recording inside DreamPi | no |

- **Switch one on or off:** Settings > **Modules**. It takes effect at once: the page reloads without the module's parts, and its endpoints and background work stop (the LED service goes dark while Status LEDs is off). Nothing is deleted, so switching it on again brings your settings back.
- **Remove one for good:** delete its folder in the folder you installed from and run `sudo ./install.sh`. The installer removes the installed copy (and, for the LEDs and Wi-Fi setup, their `dreampi-netswitch-led` and `dreampi-netswitch-wifi` services and, for the LEDs, the SPI setting they added); settings files such as `led.json`, the LED count and pin, and `numbers.json` stay for when it comes back.
- **Add one:** put its folder in `modules/` and run `sudo ./install.sh`. A module you wrote or got from someone only needs a `module.json` and its files: see `docs/modules.md`. Modules are built from a shared page kit (rows, buttons, pop-ups, colours defined once in the main stylesheet), so a visual change there changes every module and new ones look the same.
- **Without running the installer:** the page follows the folders in `/opt/dreampi-netswitch/modules` while it runs, so copying or deleting a module folder and reloading the page is enough for the page and its endpoints. The LED and Wi-Fi services are only installed or removed by the installer; if their files are deleted from `/opt/dreampi-netswitch`, systemd just skips it instead of failing.
- `--leds=N`, `--led-gpio=N` and `--no-led` do nothing without the LED module, and `--wifi`, `--no-wifi` and `--wifi-demo` do nothing without the Wi-Fi module. `--wifi` switches the Wi-Fi module on, the same as its switch in Settings > Modules (hostapd and dnsmasq are installed by every install, not only with `--wifi`).

### Uninstall

```
sudo /opt/dreampi-netswitch/uninstall.sh
```
This removes all the add-on's services (page, buttons, LEDs, Wi-Fi setup), the hook, all settings and the certificate (and an SPI setting it added to `config.txt`), and restarts DreamPi.

## Requirements

- A working [DreamPi](https://github.com/Kazade/dreampi) 2.x on a Raspberry Pi, with the Dreamcast already able to connect through it.
- The current `netlink.py` ([eaudunord/Netlink](https://github.com/eaudunord/Netlink), `dpi2` branch), which DreamPi 2.x downloads itself and which contains DreamPi's DCNET support.
- DCNET enabled in `netlink_config.ini` (`[DCNet]` with `enabled = yes`).
- `/boot/noautoupdates.txt` must **not** exist, otherwise `netlink.py` skips its config and DCNET stays off.

If DCNET isn't available, the web page says so and every call goes to DCNow!.

## Phone numbers

Four actions, each with its own list of numbers that you edit in **Settings > Special phone numbers** (each block has an **Add** button that opens a small box for the number, remove a number with its ✕, **Restore default numbers** at the bottom puts the list below back):

| Action | What it does | Default number |
|---|---|---|
| **Toggle DCNow!** | Select DCNow! / DreamPi and hang up | none (add one to use it) |
| **Toggle DCNET** | Select DCNET / FLYCAST and hang up | none (add one to use it) |
| **Call DCNow!** | Select DCNow! / DreamPi **and** connect | `11111`, `111111`, `1111111` |
| **Call DCNET** | Select DCNET / FLYCAST **and** connect | none (add one to use it) |

Any other number connects to the currently selected network. `111-1111` is also in the default **Call DCNow!** list, so dialing it (openMenu does) selects DCNow! again, which is how you get back to DCNow! by phone. If you remove it from the list, it still always directs to DCNow! for compatibility with openMenu and standard ISP configs, but the selected network is not changed. The shorter `11111` and `111111` are there because a repeated digit is easy for the modem to mishear. If you already had numbers saved, they are kept; **Restore default numbers** brings these back.

**Hang-up actions** (Toggle): DreamPi doesn't answer. The add-on changes the selection and plays a busy tone for 4 seconds, which is meant to make the Dreamcast give up straight away instead of waiting for an answer (not yet confirmed on real hardware). After that the normal dial tone comes back and the next call goes to the newly selected network. Use it to change networks from the Dreamcast without opening the web page.

**What counts as a number:** digits, `*` and `#`, 3 to 12 characters, either a whole number or just an ending, for example `*61#` or `0002`. A number counts when what the Dreamcast dialed **ends with** it, so a leading `1` (long-distance prefix), an area code, an outside-line digit or other digits the ISP config puts in front don't matter (DreamPi often hears an extra leading `1`, for example `15550002`), and the longest matching number wins. A number can only belong to one action, and a short ending can't take over openMenu's `111-1111`. Take care with very short endings: anything the Dreamcast dials that ends with it will trigger the action.

- A run of identical digits is the hardest pattern for a DTMF decoder to count correctly (no frequency change marks a digit boundary, only a timing gap), so the modem may hear one digit too many or too few. That is why the default **Call DCNow!** list has `11111` and `111111` as well as `1111111`. The [Debug log](#debug-log) helps track down misheard numbers. For your own numbers, `555-0001`-style numbers (the North American fictional-exchange prefix) work well.
- openMenu always dials `111-1111`, so it always gets DCNow! (DCNET wouldn't accept openMenu's login).
- Netlink/XBAND dial codes and DreamPi's built-in `*69` prefix ("this call to DCNET") keep working as before.

## Telling openMenu which network runs

`GET /tag` on the web port answers with one short code (`DCNET`, `DCNOW`, `DCNET_OFF`, `INACTIVE`; `/tag?text` gives "Running DCNet!" and so on) for openMenu to read over the PPP link when it is connected through the Pi, so it can show a small "Running DCNet!" tag. Nothing is pushed to the Dreamcast and games are unaffected. The Pi side is done; openMenu has to ask for it. Details, the code table and what is not verified yet: `docs/openmenu.md`.

## Web page

`http://dreampi.local` updates live, every second.

- **Network box:** the selected network (orange for DCNow!, blue for DCNET) with DreamPi's status and its dot underneath, for example "Ready for calls". Tap the box (the small arrow) to show all status rows:
  - **Modem:** what the modem is doing right now, taken from DreamPi's own log: looking for the modem, dial tone on, number dialed, carrier speed, online via DCNow! or DCNET, call ended. A red warning box appears if the modem's USB connection goes away, or if it's a modem not known to work with DreamPi (its make/model, read from its USB info - nothing is ever sent to the modem itself - shows in the **System** card in Settings, with a note if it isn't a known-working one).
  - **Pi:** CPU use, RAM and temperature on one line (for example "CPU 3%, RAM 128/923MB, 43°C"), with the uptime and the Pi's IP address underneath, plus the Pi's own power and heat warnings (under-voltage, throttling) now and since boot. A weak power supply is a common cause of an unstable Pi, so a red warning box appears at the top of the page while the Pi is short of power or overheating.
  - **Internet:** whether the Pi can reach the internet and resolve `dreamcast.online`, and whether it's connected by Ethernet or Wi-Fi. A red warning box appears at the top of the page when the internet is down.
  - **Hang up** (at the bottom when the box is open, only while DreamPi is in a call): ends a call that got stuck and gets the modem ready again. Tap it twice to confirm. It ends the call the way DreamPi ends one itself, by stopping `pppd` for DCNow! or `dcnet.rpi` for DCNET, after which DreamPi hangs up the modem and starts the dial tone. If DreamPi isn't ready for calls within 30 seconds, or the call process is already gone, it restarts the DreamPi service.
- The **DCNow! / DreamPi** and **DCNET / FLYCAST** buttons change the selected network.
- **Online players** (optional module): a box under the two network buttons that looks exactly like the Selected-network box (same classes, so it follows the same colours and the Dreamcast background). Closed, it shows "Online players:", the player count per network ("DCNow! 3  DCNET 2", each in its button colour) and a line of the games being played with the number of players in each ("Daytona USA 2001 (2) • Quake III Arena (1)"). When the line is too long for the box it scrolls like a carousel, looping without a gap. Tap it and it extends like the network box: Games (the same text, wrapped), the player list (name, game, network), a Status line and the links to DC99, Dreamcast.online, the DCNET status page, Dreamcast Live and DreamPi on GitHub. It is always shown while the module is on; switch the module off in Settings > Modules to hide it. By default it reads two feeds: `https://dc99.net/online/dcnet_status.php` (dc99.net's combined status page: DCNow!, DCNET and other networks such as KOSnet, one section each) and `https://dreamcast.online/now/api/users.json` (dreamcast.online's own DCNow! list). Players found in both are shown once (a missing game is filled in from the other copy). The Pi fetches them itself (at most once a minute, and only while the page is open; if HTTPS fails it tries plain HTTP). The Status line says what each feed contained, for example `DC99: dreampi 3/340, dcnet 5, kosnet 2` (shown/listed when some are offline), which helps when a network seems to be missing. You can change or add sources in `/opt/dreampi-netswitch/players_sources.json` (a file containing `[]` switches the list off):

  ```
  [{"name": "DC99", "url": "https://.../players.json", "network": "DCNET"},
   {"name": "Dreamcast.online", "url": "https://.../online.json"}]
  ```

  `network` is only used for entries that don't say which network they are on. Besides the two feeds above it understands a list of player objects, an object with a `players` list, or games that list their players (field names like `name`/`player`/`username`, `game`/`title`, `network`). Without sources the list says so and the links still work. To remove the feature, switch the module off, or delete `modules/players/` (see [Modules](#modules)).
- **Debug log:** the Debug log bar at the bottom (see below).

### Settings (cogwheel)

The cogwheel in the top right corner opens the settings. Changes are saved straight away; close them with the ✕ or Esc. On a wide screen the sections flow into as many columns as fit (up to four), so there is less scrolling; a phone keeps the single column. The sections, in the order they appear (a section that belongs to a module is only there while that module is on):

- **Special phone numbers** (module): the four lists described in [Phone numbers](#phone-numbers), with a short instruction and **Restore default numbers** at the bottom.
- **GPIO:** the physical wiring settings, one row per device.
  - **Button 1** / **Button 2:** each button's **function** and **pin**. Two kinds of function, in two groups in the list: **Push button** (acts on a short press) - **Off**, **Toggle network** (switches between DCNow! and DCNET, the default for button 1), **Select DCNow!** or **Select DCNET** (the default for button 2 is **Off**) - and **Toggle switch** (a latching on/off switch wired between the pin and GND, **closed = on**, which decides the state by its position, also when the Pi starts): **On = DCNET** (closed: DCNET, open: DCNow!), **On = DCNow!** (the other way round) and, while the Wi-Fi setup module is on, **On = Wi-Fi setup** (closed: Wi-Fi setup, open: normal) or **Off = Wi-Fi setup** (the opposite). A text under each row spells out the chosen function. Pick two different pins; a change takes effect within a couple of seconds, no reinstall needed. The physical wiring and the defaults (GPIO17 and GPIO4) are under [Buttons and Wi-Fi setup](#buttons-and-wi-fi-setup).
  - **Wi-Fi setup** (Wi-Fi module): which push button, or **Button 1 + 2** held together, starts Wi-Fi setup with a 3-second hold ("Hold button 1 for 3 s to start Wi-Fi setup"). A button set to a toggle switch function can't be held, so it's ignored here. A button's own short-press function still works normally; only a press that is held long enough to start Wi-Fi setup skips it.
  - **LED** (Status LEDs module): **LEDs connected** (1 to 300, just where the count starts out), **wire order** (`RGB`, `RBG`, `GRB` - most WS2812 strips, `GBR`, `BRG` or `BGR`; a wrong order shows the right brightness with the wrong colour, for example a red status looking green) and **output pin** (GPIO10, 12, 18 or 21; the pin picker is last in the row, like the buttons' pin pickers). All three take effect within a second.
- **Status LED** (Status LEDs module; only shown when the LED count is above 0 - `--leds=0` hides it; the title shows the number of LEDs for a strip): how the LEDs look. One box with the **Calibration** row at the top, the list of messages, and **Reset LED settings to defaults** at the bottom.
  - **Calibration** has an **Adjust** button that opens a small pop-up (**Done**, Esc or a tap outside closes it, which also ends the white preview). **White balance:** three sliders, **Red**, **Green** and **Blue** (0 to 255, all at 255 by default - no correction). Tap **Preview on LED** to hold the LED at solid white, then turn down whichever channel looks too strong until it looks neutral white rather than tinted - leave at least one at 255, don't turn any of them up. Tap **Stop preview** when you're done; it also stops automatically if you close the pop-up or Settings. **Reset to neutral** sets all three back to 255. This corrects every colour the LEDs show, not just white, and takes about 30 to 60 seconds - there's no need to calibrate individual colours. **Brightness** (the maximum brightness) is in the same pop-up: 0 to 100% (default 8%), applied after the white balance as a ceiling on the whole strip regardless of colour. The slider is logarithmic: its left half covers 0 to 9%, the range that suits an indicator LED best, and the right half goes up to full brightness for enclosures that need it.
  - **The list of messages**, grouped into **System**, **Network**, **Call — DCNow!**, **Call — DCNET**, **Call — Netlink** and **Wi-Fi setup** (see [LED messages](#led-messages)). Every message is separate, so DCNow! and DCNET can look completely different, or the same. Per message: a **tick box** to use it or not (a message that is off shows nothing; when no ticked message applies, the LED is off), its **colour**, its **effect** and its **level**.
  - **Effect:** tap it for a small menu. **Solid**, **Blink**, **Breathe** (fading up and down), **Ping** (two quick pulses, then a longer pause) and **RGB** (cycles through all colours, ignoring the colour set: one round every 20 seconds when slow, every 10 when fast) work on any LED. With a strip there are also **Rainbow** (flowing towards the last LED), **Scanner** (a bright dot sweeping back and forth with a fading trail, like KITT or a Cylon), **Comet** (a bright head with a fading tail running round the strip), **Chase** (every third LED, stepping forward) and **Twinkle** (random sparkles). Every effect except Solid has a **Slow** and a **Fast** speed. With a strip, the same menu sets which **LEDs** the message uses: **All**, **One LED**, or a **Range** such as 2 to 5.
  - **Level:** the brightness for that message. Grey means it uses the maximum brightness from Calibration; tap it to give the message its own brightness with a slider, and tap **Use global** to go back.
  - **Reset LED settings to defaults** restores the defaults in [LED messages](#led-messages) and the 8% maximum brightness (not the white balance or the wire order - those describe your LEDs, not a look to reset).
- **Modules:** every installed module with a switch (see [Modules](#modules)).
- **System:**
  - **Wi-Fi setup** (Wi-Fi module): at the top. Starts or stops the same setup the button does, and while it's scanning or hosting, lists the networks it found right here too, as rows with a name, "Secured" or "Open" and the signal strength; tap **Connect** on one, enter its password in the small box if it needs one, and connect (**Other network** is for a hidden one) - which also works if this page is still reachable some other way (for example over Ethernet) while the Wi-Fi is being set up.
  - The add-on's version (date and commit it was installed from), the versions of DreamPi's own scripts `dreampi.py`, `netlink.py` and `dcnow.py` (the dates in their `_version=` lines, which DreamPi's auto-update compares), the Raspberry Pi model, the operating system, whether a PIN is set, a link to this project on GitHub, and - once a modem has been detected - its make/model, with a note if it isn't a known-working one.
  - **Updates** (Reboot and Update module): checks GitHub for a newer version of this add-on and for newer DreamPi scripts, with an **Update now** button (when installed from a git checkout).
- **Reboot DreamPi** (Reboot and Update module; last card): reboots the whole Raspberry Pi after a confirmation; a call in progress is cut. The page comes back by itself when the Pi is up again (about a minute).

The selected network is DCNow! after every reboot (there is no default-network setting; to go back to DCNow! by phone use a **Toggle DCNow!** or **Call DCNow!** number).

The status dot next to DreamPi on the main page previews that status's colour and effect. Network problems show as red warning boxes at the top of the page instead.

`http://dreampi.local/api` returns the status as JSON, and `http://dreampi.local/status` as plain text:
```
network=dcnet
tag=DCNET
dreampi=Ready for calls
modem=Dial tone on, waiting for a call
internet=Connected via Ethernet (18 ms)
pi=CPU 7%, RAM 142/926MB, 48°C. Uptime 2 h 5 min, IP: 192.168.1.55.
```

## LED messages

Every message is configured on its own in **Settings > Status LED**: on or off, colour, effect (and speed), level (brightness) and, with a strip, which LEDs it uses (all, one LED, or a range). Many messages start out with the same look on purpose; they are separate so you can change just one or send it to its own LED. The settings are grouped as System, Network, Call — DCNow!, Call — DCNET, Call — Netlink, plus Wi-Fi setup. The global (maximum) brightness is not on this list; it is in the Calibration pop-up at the top of Settings > Status LED.

**Colours mean something:** orange is DCNow!, blue is DCNET, purple is Netlink, and **red means something is wrong**, so a failed call is red, not the network's own colour. You can change any colour.

| Message | Default look | On by default |
|---|---|---|
| **System** | | |
| Starting up | Amber, breathing slowly | Yes |
| DreamPi not running | Red, blinking slowly | Yes |
| Power or heat problem | Red, blinking fast | Yes |
| State unknown | Dim grey, solid | Yes |
| **Network** | | |
| No network | Red, solid | Yes |
| No internet | Amber, blinking slowly | Yes |
| Ethernet connected | Green, solid | No |
| Wi-Fi connected | Light blue, solid | No |
| Network switching | White, Ping | No |
| **Call — DCNow!** | | |
| Ready for calls | Orange, breathing slowly | Yes |
| Connecting | Orange, blinking slowly | Yes |
| In a call | Orange, solid | Yes |
| Call failed | Red, blinking fast | Yes |
| **Call — DCNET** | the same with blue | Yes |
| **Call — Netlink** | the same with purple | No |
| **Wi-Fi setup** (choose a network / connected / couldn't connect) | Light blue breathing (scanning, on a strip) / green / red blinking | Yes |

- **What the add-on can tell today:** *Ready for calls* (for the selected network), *In a call* (DCNow!, DCNET, and Netlink for DreamPi's other calls), *Starting up*, *DreamPi not running*, *State unknown*, the network messages except *Network switching*, and Wi-Fi setup. **Connecting, Call failed, Ready for calls — Netlink and Network switching can be set up but never show yet**: DreamPi's state file doesn't say when they happen, and the page marks them *not detected yet* instead of guessing.
- **Priority** (highest first): Wi-Fi setup, errors (no network, no internet, power or heat, DreamPi not running, call failed), network switching, starting up, in a call, connecting, ready for calls, Ethernet / Wi-Fi connected. **State unknown is the last resort**: it only shows when no other message applies. A message that is switched off shows nothing.
- **Effects:** Solid, Blink, Breathe, **Ping** (two quick pulses, then a longer pause, like a double ping), RGB and, with a strip, Rainbow, Scanner, Comet, Chase and Twinkle. Ping uses the message's own level, and on a strip it pulses only the LEDs the message is set to use.
- **No network:** the Pi has no route to your router, for example because the cable is unplugged or Wi-Fi isn't connected. You can't open the web page then, so the LED is the only thing that can tell you.
- **No internet:** the Pi reaches your router, but not the internet, or name lookups (DNS) fail.
- **Power or heat problem:** the Pi reports under-voltage or throttling right now, or is at 80 °C or more.
- **Checking speed:** cables, Wi-Fi and the route are checked every 2 seconds. The internet is checked every 30 seconds while it works, every 5 seconds while it doesn't, and straight away when a connection changes.
- **Several messages at once:**
  - On a single LED, or when messages all use all LEDs, the most important one shows.
  - With a strip, each message draws on its own LEDs, less important ones first, so an error on "All" takes over the whole strip.
  - Give the errors LED 1 and "Ready for calls" LEDs 2 to 8, and LED 1 stays dark until something goes wrong while 2 to 8 keep showing DreamPi. Or give Ethernet LED 1, Wi-Fi LED 2, DCNow! calls LED 3 and DCNET calls LED 4, and each lights on its own.
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

**Other pins:** the same wiring, just to a different data pin - **GPIO10** (pin 19), **GPIO12** (pin 32) or **GPIO21** (pin 40) - and, for GPIO10 only, with SPI switched on, which the add-on does itself (see Install below). Use another pin if GPIO18 is wanted for something else, or to keep the analog audio jack free (it also uses PWM, which GPIO12 and GPIO18 both drive the LEDs through; GPIO21 uses a different peripheral, PCM, instead).

**Install:**
- One LED on the default pin (GPIO18): nothing to do, it's on by default
- Several LEDs or a strip: `sudo ./install.sh --leds=30` (the number of LEDs, 0 to 300; only the starting count, it can be changed later in Settings > GPIO; `0` turns the LED off and hides the LED settings)
- A different pin: add `--led-gpio=10`, `--led-gpio=12` or `--led-gpio=21` (GPIO18 is the default; can be combined with `--leds=N`). **GPIO10 uses the Pi's SPI**, which the add-on switches on itself: it adds `dtparam=spi=on` to `config.txt` and asks the running system to enable SPI right away. If SPI doesn't show up (`/dev/spidev0.0`) after that, a reboot applies the setting, and the LEDs stay on the old pin until then.

This starts the `dreampi-netswitch-led` service. Later updates keep the LED count and pin. The LED count and pin can also be changed later from the page (Settings > GPIO) without rerunning the installer, GPIO10 included: choosing it switches SPI on in `config.txt` (the LED service runs as root and does it), choosing another pin takes the line out again. Only a line the add-on added itself is ever removed, never an SPI setting you made yourself, and uninstalling or removing the LED module takes it out too. Whether the live switch-on works without a reboot depends on the Pi OS version; this has not been tried on a real Pi (see `docs/hardware-status.md`).

**How it works:** GPIO12 and GPIO18 are driven by the Pi's PWM hardware, clocked from the crystal, which gives accurate NeoPixel timing without special drivers, extra Python packages or config changes; GPIO21 uses the PCM peripheral the same way, so the LEDs don't need the PWM hardware (and therefore not the analog audio jack) at all. A single LED on GPIO12/18 is fed directly; anything else on GPIO12/18/21 is fed by a DMA channel from memory shared with the GPU, the same method the rpi_ws281x library uses. GPIO10 instead goes through the kernel's own SPI driver (`dtparam=spi=on`), one SPI byte per NeoPixel bit - what this add-on used by default in its very first versions, before it moved to GPIO18.

**Brightness, colours and effects:** set in the web page's settings (cogwheel). Effects run at 50 frames per second and start from the beginning whenever a message appears or changes (a blink starts lit, a breathe starts bright), and changes show up within a quarter of a second. They're stored in `/opt/dreampi-netswitch/led.json`.

If the LEDs stay dark, `systemctl status dreampi-netswitch-led` shows why.

## Buttons and Wi-Fi setup

Two momentary push buttons are always installed, as quick network switches and (with `--wifi`) a way to join a Wi-Fi network without a keyboard, monitor or SSH: **button 1** on **GPIO17 (physical pin 11)**, function **Toggle network** by default, and **button 2** on **GPIO4 (physical pin 7)**, **Off** by default. Wire each between its GPIO pin and a **GND** pin. Pins and functions (and, with `--wifi`, which button or both together starts Wi-Fi setup) are all editable later from Settings > GPIO (see [Settings](#settings-cogwheel)) - no reinstall needed.

- **A short press** on a button runs its own function: **Off** (nothing), **Toggle network** (switches between DCNow! and DCNET, the same as the web page's two buttons or dialing a Toggle DCNow!/Toggle DCNET number), **Select DCNow!** or **Select DCNET** (selects that network outright, whatever was selected before).
- **Holding the assigned button(s) for 3 seconds** starts Wi-Fi setup (only while the Wi-Fi setup module is on; without it a long press is just a slow short press) - by default that's button 1 alone, but Settings > GPIO can assign it to button 2 instead, or to both buttons held down together. Whichever button(s) that is, their own short-press function above still works normally on a short press; only a press that's actually held long enough to start Wi-Fi setup skips it. Once started, the Pi:

1. Scans for Wi-Fi networks and hosts a temporary, unencrypted Wi-Fi network called **"DreamPi WiFi Config"**, styled like the main page.
2. Connect a phone or PC to it and open `http://192.168.4.1` (most phones prompt for this automatically) - or, if the Pi's regular page is still reachable some other way (for example over Ethernet), open its Settings instead; the same network list appears there too (see [Settings](#settings-cogwheel)). Pick a network from the list (or enter one manually, for a hidden network), enter its password if it needs one, and tap **Connect**.
3. The temporary network closes and the Pi tries to join the network you chose.
4. If it gets online, the status LED (if installed) goes solid **green** for a few seconds and everything returns to normal; DreamPi keeps using this Wi-Fi network (and any others saved this way) after a reboot too. If it can't get online, the LED goes **red** for a few seconds and the Pi goes back to step 1, hosting "DreamPi WiFi Config" again so you can try another network or password.

While it's scanning or hosting the setup network, a status LED shows a breathing blue light (a scanning animation instead, with a strip). Holding the assigned button(s) again, or the **Wi-Fi setup** control at the top of System in the settings, cancels it at any point and returns the Pi to its normal Wi-Fi connection.

**Wiring:** no resistor needed; the Pi's internal pull-up is used on each pin, so it reads high normally and low while that button is held. GPIO17 and GPIO4 were picked as the defaults because neither has any other function on any Raspberry Pi model (an earlier version of this add-on defaulted the single button to GPIO15, which doubles as the Pi's UART RX pin and could pick up noise from the serial console/Bluetooth if that's in use). A pin or function change from Settings > GPIO takes effect within a couple of seconds, with no service restart. A toggle switch is wired the same way, between the pin and GND (any simple on/off switch; closed = on).

**Install:** the buttons come with every install and run as the `dreampi-netswitch-buttons` service. The Wi-Fi setup module has its own `dreampi-netswitch-wifi` service, layered on top of the buttons. Every install installs `hostapd` and `dnsmasq` with `apt` if they aren't already present (needed to host the setup network); `sudo ./install.sh --wifi` (or the switch in Settings > Modules) turns Wi-Fi setup on, `--no-wifi` turns it off again.

**Not yet verified on real Wi-Fi hardware:** it assumes the classic Raspberry Pi OS network stack (`wpa_supplicant` + `dhcpcd`), and hosting the setup network takes the Wi-Fi interface away from its normal connection while it's up (Ethernet, if connected, keeps working throughout). If your Pi's networking is set up differently (for example NetworkManager), this feature likely won't work; everything else in this add-on is unaffected either way. A single button on GPIO17 was tried on real hardware in an earlier version of this add-on; the two-button, per-button-function and combined-hold generalisation described above has not been.

## Debug log

The debug log is for tracking down calls that go wrong, such as misheard numbers. It is off by default: switch the **Debug log** module on in Settings > Modules first. Then click the **Debug log** bar at the bottom of the main page to open it (click again to close it), press **Recording off** so it changes to **Recording**, and dial. The panel shows one live timeline with millisecond timing:

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
- `journalctl -u dreampi-netswitch-buttons -n 50` shows what the buttons are doing; `journalctl -u dreampi-netswitch-wifi -n 50` shows Wi-Fi setup (scanning, hosting, connecting) and any error.
- `sudo grep netswitch /var/log/messages` shows lines like `netswitch: routing 5551234 to DCNET`.
- `cat /tmp/dreampi-netswitch.active` should say `active pid=<DreamPi's process id>`.

## Credits

This add-on is built for [DreamPi](https://github.com/Kazade/dreampi) by Luke Benstead (Kazade), with DCNET and Netlink support from [eaudunord/Netlink](https://github.com/eaudunord/Netlink). It doesn't include or change any of their code; it only hooks into it while DreamPi runs.

The page's tab icon is the DreamPi logo (without its text) while DCNow! is selected, and the [Flycast](https://github.com/flyinghead/flycast) logo while DCNET (Flycast's network) is selected. The logos belong to the DreamPi and Flycast projects and are used here only to show which network is selected.

The optional **Dreamcast background** module comes from the [VMU Icon Maker](http://dcvmuicons.net/maker/) by **Robert Dale Smith** ([source on GitHub](https://github.com/RobertDaleSmith/vmu-icon-maker), MIT License), part of his [DC VMU Icons](http://dcvmuicons.net/) site. The animated scene, its texture, the waves and the cylinder are his work; this add-on only wraps it so it can be switched on and off as a module (`modules/background/dc-background.js`). It runs on [Three.js](https://threejs.org) r128 (MIT License). The licence texts are in `modules/background/LICENSES.txt`.
