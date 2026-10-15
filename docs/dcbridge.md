# DC Bridge: the Dreamcast serial-port bridge

Read before touching `modules/dcbridge/`, `firmware/dcbridge/` or the bridge's part of `install.sh`. Back to [CLAUDE.md](../CLAUDE.md).
Brought in from the `dcbridge-stage4` package (firmware, the Pi's save manager and the routing scripts) and made a module of the dashboard.

## In the dashboard (the module)

`modules/dcbridge/` (off by default). **Install and uninstall from the module itself:** switch the module on (Settings > System > Modules), then in
Settings > **DC Bridge** press **Install** (the box also shows the state, and the setup's log while it runs); **Uninstall** takes the Pi's side out again.
Both ask first and ask for the PIN when one is set. The same can be done from the command line with `sudo ./install.sh --dcbridge` / `--no-dcbridge`
(which also switch the module on / off). Either way the work is `system/dcbridge-setup`. An update of the add-on re-installs the bridge only if it is
installed (the unit `/etc/systemd/system/dcbridge-saves.service` exists); a module that is on but not installed is left alone.

- `netswitch_dcbridge.py` = the dashboard's side. `start()` looks at the bridge service every 2 s (a thread, so `/api` never waits for it) and
  `api()` puts `dcbridge` into `/api` (`view()`: the Dreamcast's link mode, the virtual SD card, the Dreamcast's addresses on the two network
  links; a warning box while the service is not running). `GET /dcbridge-view` is the same as JSON.
- **The save manager is passed on:** `GET /dcbridge/` (the page) and `/dcbridge/api/...` go to the service on `127.0.0.1:8085`, so the saves need no
  port of their own on the LAN. The service only takes the page's own paths (`api/...` without `..`). The dashboard's web service only takes POST,
  so the page sends PUT and DELETE as `POST ...?_method=PUT|DELETE` (the module turns them back), says it comes from a page (`X-Requested-With`) and,
  while Settings is locked with the PIN, asks for the PIN once (`X-Pin`). Another site's form is refused like everywhere else.
- `layout.json`: the dashboard box **Dreamcast bridge** (the Dreamcast, the SD card and the network as status rows, a link to the save manager) and
  Settings > **DC Bridge** (links to the save manager and to the zip of all saves) and the box colour in Appearance.
- **Install / Uninstall:** `POST /dcbridge-setup/install` and `/remove` (PIN-protected) start `system/dcbridge-setup install|remove` as root with
  `systemd-run` (outside the web service, which is sandboxed and may not write to `/etc` or `/usr`; a transient unit survives the restart that the
  service's own units get). One at a time; the script writes `running` / `ok` / `failed` to `/tmp/dreampi-netswitch.dcbridge` and its output to
  `.dcbridge.log`, which the box shows (`dcbridge.setup`: `installed`, `state`, `text`, `log`; a `running` older than 30 minutes counts as failed).
  Install = apt packages (a second try after `apt-get update`), `/var/lib/dcbridge`, pppd options, `/etc/default/dcbridge` (only if missing), dhcpcd /
  NetworkManager entries, the sysctl file, udev rules, the three units, dnsmasq file and `DCB-*` firewall chains, then it enables and starts
  `dcbridge-saves`. Uninstall = the reverse; **`/var/lib/dcbridge` (the saves) and `/etc/default/dcbridge` stay**. While it is not installed the
  dashboard box says so and has no save manager link, and no "service is not running" warning is raised.
- `dcbridge_saves/` = the Pi's service (below), `system/` = what the installer puts into the Pi (units, udev rules, `dcbridge-net`, the pppd options
  and the settings file) and `dcbridge-setup` (install / remove, below), `install.sh` / `remove.sh` = this module's installer (they call `dcbridge-setup`).
- Switching the module off in the picker only hides the box and the save manager; the services keep running until Uninstall / `--no-dcbridge`.
- Files: `/var/lib/dcbridge/` (the card image `sdcard.img`, `saves/` with the history and the queued edits; kept when the module is removed),
  `/etc/default/dcbridge` (the network settings, also kept), `/run/dcbridge/dcnet-ip`.
- Tests: `tests/test_dcbridge.py` (the dashboard's side with a stand-in service), `tests/test_dcbridge_saves.py` (the Pi's side: image, store, disk
  server, web API; needs `mtools` and `dosfstools`, skipped without them), `tests/dcbridge/test_net.sh` (as root, in network namespaces; not in
  `tests/run.sh`), and the firmware's own host tests below.

## Status

| Part | State |
|---|---|
| Composite USB (3× CDC-ACM + CDC-ECM), descriptors, udev names | done, builds |
| Auto-sense SENSE ⇄ UART ⇄ SPI, exact SCIF auto-baud, RTS/CTS | done, builds, baud logic unit-tested |
| PIO SPI slave tuned to KOS `scif-spi.c` bit-banging | done, cycle-simulated |
| Virtual W5500 (MACRAW socket 0, as KOS uses it) ⇄ ECM frames | done, tested against a byte-exact replay of the KOS driver |
| Virtual SD card (KOS `sd.c` command set, CRC16, multi-block, busy) | done, tested against a byte-exact replay of KOS `sd.c` and end to end through the real Pi daemon |
| Pi save manager: image, history, queued edits, web page, JSON API, CLI | done, unit-tested, Python 3.5+ |
| Pi routing for PPP (`ppp10`) and the W5500 link (`dcnet0`): DHCP, DNS, NAT, port forwards | done. NAT/DHCP/DNS/forwards tested in network namespaces; pppd options checked against the binary (no kernel PPP in the test box) |

**None of this has run on real hardware yet** (see [hardware-status.md](hardware-status.md)). The first bring-up checklist is at the end.

## Wiring

Physical chain: **Dreamcast serial port → serial-to-SD adapter → SD-to-microSD
adapter → microSD pads → RP2040 → USB → Raspberry Pi 2.** The RP2040 sits where
the memory card would be, so each microSD pad carries one of the Dreamcast's
serial lines (the adapter just renames them, the way KOS `scif-spi.c` uses
them). All pin numbers live in `firmware/dcbridge/src/config.h`. The build fails if two
functions share a pin.

| microSD pin | SD name | Dreamcast line (UART / SPI) | RP2040 | Pico board pin |
|---|---|---|---|---|
| 1 | DAT2 | — | not connected | |
| 2 | DAT3 / CS | RTS / /CS | GP5 | 7 |
| 3 | CMD | TXD / MOSI | GP3 | 5 |
| 4 | VDD | adapter's 3.3 V | **not connected** (correct: the RP2040 has its own USB power) | |
| 5 | CLK | CTS / SCLK | GP2 | 4 |
| 6 | VSS | GND | GND | 3 |
| 7 | DAT0 | RXD / MISO | GP4 | 6 |
| 8 | DAT1 | — | not connected | |
| (optional) | | CTS drive | GP6 → 1 kΩ → the CLK line | 9 |

The pins don't have to be consecutive. The PIO program's clock and
chip-select waits are rewritten to these GPIO numbers when it loads.

Why PIO and not the hardware UART/SPI blocks: the Dreamcast's TXD needs a
pin that is UART RX in one mode and SPI RX in the other, and no RP2040 pin is
both. The PL022 SPI slave also needs /CS to toggle between bytes in mode 0,
which KOS never does.

Notes:
- **Optional 1 kΩ from GP6 to the CLK line** (GP2 stays wired straight to it).
  It only matters for PPP/UART mode, where the RP2040 drives the Dreamcast's
  CTS for flow control on the same wire the Dreamcast uses as SCLK in SPI
  mode. Without it the firmware uses the ~50 kΩ internal pulls on GP2. That
  works unless the adapter has a stronger pull-up on CLK. If you leave it out,
  set `PIN_DC_CTS_DRIVE` to `-1`.
- Check whether your serial-to-SD adapter has resistors in series or pull-ups
  on these lines. That's fine for SPI. For UART mode the CLK line is the only
  one that matters (see the previous note).
- If the Dreamcast is switched on while the RP2040 has no USB power, the
  Dreamcast drives into unpowered pins. Power the Pi first, or add
  100–220 Ω series resistors on the four lines.

## How auto-sense works (`firmware/dcbridge/src/dcbus.c`)

Everything on the Dreamcast side runs on core1 with no interrupts, from RAM.

- **SENSE** (power-on): the PIO SPI slave is armed, with MISO idling high so a
  UART receiver on the Dreamcast just sees an idle line. A second PIO program
  measures low pulses on DC TXD. CTS is asserted so a Dreamcast in UART mode
  can start talking.
- **→ UART** after ≥24 low pulses with no SCLK activity, when their widths are
  whole multiples of one SCIF bit (640 ns × n). The rate snaps to what the SH4
  can actually generate. For example, KOS "115200" really runs at
  **120192 baud** because of integer maths in `scif.c`, and the bridge matches
  that exactly. Flow control: the TX program waits for DC RTS low, and the
  firmware holds the Dreamcast off through CTS when the Pi isn't reading.
- **→ back to SENSE/SPI** when the Dreamcast starts clocking its CTS pin
  (`scif_spi_init()`), or after a burst of framing errors or much shorter
  pulses (a baud change).
- **SPI target**, latched from what KOS actually does on the wire:
  - **SD:** SCLK clocks while /CS is high. `sd_init()` sends 80 of them.
  - **W5500:** a frame of `00 00 04 80` (`w5500_soft_reset()`).

  KOS lets only one driver own SCIF-SPI at a time (`scif_spi_init()` refuses a
  second user), so a single program uses either the SD card or the W5500,
  never both. openMenu uses the card, then hands over to the game.

### The one hard real-time spot

On a W5500 read, the first data bit must already be on MISO when the Dreamcast
raises SCLK after the 3-byte header. The PIO program waits until either the
data arrives or that edge comes, whichever is first. If it's late it sends
filler and flags an *underrun* (shown in the status JSON). In
`firmware/dcbridge/test/sim_spi_pio.py`, a cycle-level run of the shipped PIO code against the
KOS bit-bang sequence, core1 has **≈42–100 cycles at 250 MHz** depending on
SH4 bus timing. The real handler is roughly 20–30 cycles. That's why the
firmware runs at 250 MHz from RAM. The PIO keeps up down to 24 ns SCLK
half-periods; KOS manages about 60 ns.

### A KOS quirk the emulator reproduces

`w5500_exec_cmd()` keeps /CS low after writing `Sn_CR` and then clocks what
looks like a new header plus a status read. A real W5500 treats all of it as
continued (VDM) writes and returns `0x00`, which is what ends KOS's poll loop.
The emulator behaves the same way: write phases return the 0x00 filler.
Parsing those bytes as a new header would break `SEND`/`RECV`.

## Virtual SD card and save manager

### How openMenu's serial VMU uses the card

openMenu (Virtual Folder Bundle) calls KOS `sd_init()` and mounts FAT
partition 1. Each game gets `/OPENMENU/SAVES/<serial>/` holding
`SLOT1.VMU`–`SLOT5.VMU` (raw 128 KB VMU images), optional `SLOTn.TXT` labels and
`TITLE.TXT`. `/OPENMENU/LASTDISC.TXT` (e.g. `T-36802N-1`) tells the next boot
which slot to copy the physical VMU back into. Each slot file is exactly 128 KB.

### Firmware (`firmware/dcbridge/src/sd_emu.c`, `sd_link.c`)

- core1 answers the SD protocol itself: CMD0/8/55+41/58/59/9/10/12/13/16/17/18/23/24/25,
  as SDHC (block addressing) with CRC16 on every data block, because KOS checks it.
- Sectors come from a 64-sector cache in RAM, filled from the Pi in 8-sector
  read-ahead batches. Each read is streamed straight out of the cache, with no
  copy on core1. KOS waits up to ~50 ms for each sector; a USB round trip to the
  Pi takes a few ms.
- Writes go into 16 slots and are sent to the Pi in order. Each slot is freed
  only once the Pi confirms the sector is in the image file. If all slots are
  full the card signals *busy*, which KOS waits out. Nothing is acknowledged to
  the Dreamcast that isn't already in a slot.
- The card only finishes initialising (ACMD41) after the Pi answers. If the
  daemon isn't running, openMenu reports no SD card instead of seeing garbage.

### Pi daemon (`modules/dcbridge/dcbridge_saves`, systemd service `dcbridge-saves`)

- Serves `/var/lib/dcbridge/sdcard.img` (created on first start: 128 MiB, MBR +
  FAT32) over `/dev/dcbridge-disk`.
- **History:** 4 s after the Dreamcast stops writing, it rescans the card and
  copies every new or changed slot to
  `/var/lib/dcbridge/saves/history/<serial>/SLOTn/` (newest 30 kept). Uploads,
  restores and deletes also store the card's previous copy first, so no version
  is ever lost.
- **Edits are queued:** uploads, restores, labels and deletes are written into
  the image only when the Dreamcast starts the card after a *cold boot* (bus
  silent > 5 s before CMD0). KOS caches the FAT while the card is mounted, so
  editing it then would corrupt it. KOS's own retry-after-error re-init is
  recognised (bus not silent) and never triggers edits. When edits were
  applied, the RP2040 drops its sector cache.
- One thing to know: openMenu copies the physical VMU into the *last played*
  slot on its next boot. Uploading into that slot will be overwritten then. The
  page warns you, and both versions stay in history.

### Using it

- Web page: in the dashboard, Settings > DC Bridge > Save manager (`/dcbridge/`); the service itself listens on `127.0.0.1:8085` only. It lists games and slots, with Download,
  Replace…, Label, History (download or restore any version), Delete,
  Download all (zip), and Upload save for a new game.
- JSON API: listed at the top of `modules/dcbridge/dcbridge_saves/web.py`, under `/dcbridge/` in the dashboard (`api/saves`,
  `api/saves/<serial>/<slot>`, …).
- CLI: `PYTHONPATH=/opt/dreampi-netswitch/modules/dcbridge python3 -m dcbridge_saves list | download | upload | label | delete |
  history | restore | pending | cancel` (works while the service runs).
- In the dashboard: the module passes the page and the API on under `/dcbridge/` (all URLs in the page are relative).

Install on the Pi: Settings > DC Bridge > Install, or `sudo ./install.sh --dcbridge` (the add-on's installer; both run `dcbridge-setup`, which installs `mtools`, `dosfstools`, `ppp`, `dnsmasq` and `iptables`,
the udev rules and the service, and switches the module on).

### The dashboard says the board is not connected

The Dreamcast row tells which step is missing (the service adds `usb` and `devices` to `GET /api/bridge` while it has no status line):
- **Board not on USB**: `lsusb | grep 1209:0001` shows nothing: cable (data, not charge-only), firmware not flashed, or the board is in BOOTSEL.
- **Board on USB, but no udev names**: `ls -l /dev/dcbridge-*` is empty although `lsusb` lists it. Check `udevadm info -a -n /dev/ttyACM0 | grep -E 'manufacturer|idVendor|ID_USB_INTERFACE_NUM'`
  (the rules need manufacturer `dcbridge`) and run `sudo udevadm control --reload && sudo udevadm trigger`.
- **Board found, no status from it**: `/dev/dcbridge-ctl` exists but sends nothing: `sudo systemctl stop dcbridge-saves; cat /dev/dcbridge-ctl` should print one JSON line a second.

## Networking (`modules/dcbridge/system`, installed by the module's `install.sh`)

Both Dreamcast links get their own small NAT'd subnet on the Pi. Nothing on
your LAN changes, and DreamPi's modem link keeps `ppp0` and its LAN address.

| Link | Pi side | Dreamcast gets | Started by |
|---|---|---|---|
| W5500 (KOS `w5500_adapter`) | `dcnet0` 192.168.170.1/24 | DHCP from dnsmasq, 192.168.170.2–20 | udev → `dcbridge-dcnet.service` |
| Serial PPP (KOS `ppp_scif_init`) | `ppp10` 192.168.171.1 | 192.168.171.2 via IPCP | udev → `dcbridge-ppp.service` |

- **DNS:** both links use the Pi's own dnsmasq, i.e. DreamPi's configuration
  with the dreamcast.online server redirects. Set `DNS_SERVER` to bypass it.
- **NAT:** traffic leaves through whatever the default route is: eth0, wlan0,
  or DreamPi's VPN tun0. DreamPi's `dcnatrules` redirects for dead game
  servers sit in PREROUTING, so they apply to these links too.
- **Coexisting with DreamPi:**
  - All rules live in separate `DCB-*` chains. `dcbridge-net firewall-down` (`system/dcbridge-net`)
    removes exactly those.
  - pppd uses unit 10, because dreampi.py hard-codes `ppp0` in its rules.
  - Our pppd options add `noproxyarp` on top of the `/etc/ppp/options` that
    dreampi.py rewrites.
  - dreampi.py runs `killall pppd` when it starts. systemd restarts ours two
    seconds later.
- **pppd stays `silent`:** it doesn't transmit anything until the Dreamcast
  sends an LCP request, so programs that only use the serial console never
  see PPP noise. If you need the raw console yourself (dcload, picocom), run
  `sudo systemctl stop dcbridge-ppp`.
- **Inbound ports** (only for games that accept incoming connections): add them
  to `FORWARD_PORTS` in `/etc/default/dcbridge`, e.g.
  `FORWARD_PORTS="udp:7648-7649:ppp"`, and forward the same ports on your
  router to the Pi. A dnsmasq hook keeps W5500 forwards pointed at whatever
  address the Dreamcast was given.
- **Settings:** edit `/etc/default/dcbridge` (subnets, TTL fix, DNS, forwards),
  then run `sudo /opt/dreampi-netswitch/modules/dcbridge/system/dcbridge-net reload`. To see what's up, run
  `sudo /opt/dreampi-netswitch/modules/dcbridge/system/dcbridge-net status`, or open `api/bridge` on the save
  manager (also shown in its header).

## USB device

| Interface | Linux | Purpose |
|---|---|---|
| CDC 0 "dcbridge UART" | `/dev/dcbridge-uart` | Dreamcast SCIF bytes. Pi→DC data is only forwarded while the DC is in UART mode, so DreamPi's `wvdialconf` modem probe (it sends AT commands to every ttyACM) can't leak onto the Dreamcast. |
| CDC 1 "dcbridge control" | `/dev/dcbridge-ctl` | One JSON status line per second and on every mode change. Commands: `status`, `reboot`, `bootsel` (reflash from the Pi without touching the board). |
| CDC-ECM "dcbridge net" | `dcnet0` | Ethernet wire of the virtual W5500. ECM, not RNDIS: Linux's `cdc_ether` binds it natively. |
| CDC 2 "dcbridge disk" | `/dev/dcbridge-disk` | Virtual SD card sectors. A framed protocol, documented in `sd_link.h`. |

VID:PID is the pid.codes test pair `1209:0001`, which is fine for a private
device. The udev rules also match the manufacturer string. Install
`modules/dcbridge/system/99-dcbridge.rules` so the bridge always gets these names and the DreamPi
modem keeps its own ttyACM.

DreamPi note: `dreampi.py` finds the modem with `wvdialconf` and falls back to
`/dev/ttyACM0` if that fails. The bridge never answers `AT`, so it isn't
chosen as the modem. If your modem detection is flaky, though, the fallback
could land on whichever device enumerated first.

## Build

The firmware is in `firmware/dcbridge/` (not installed on the Pi), with a prebuilt `firmware/dcbridge/dcbridge.uf2` from the package it came in (not
rebuilt or checked by this repository: build your own with the commands below if you want to be sure what is on the board).

```sh
export PICO_SDK_PATH=~/pico-sdk          # tested with SDK 2.1.1 (bundled TinyUSB)
cmake -S firmware/dcbridge -B firmware/dcbridge/build && cmake --build firmware/dcbridge/build -j
# flash firmware/dcbridge/build/dcbridge.uf2 (hold BOOTSEL, or: echo bootsel > /dev/dcbridge-ctl)
```

Host tests (no hardware needed):

```sh
cd firmware/dcbridge/test
cc -O2 -I../src test_w5500.c ../src/w5500_emu.c -o t_w5500 && ./t_w5500
cc -O2 -I../src test_baud.c  ../src/baud.c      -o t_baud  && ./t_baud
cc -O2 -I../src test_sd.c ../src/sd_emu.c ../src/sd_link.c -o t_sd && ./t_sd
cc -O2 -I../src test_e2e.c ../src/sd_emu.c ../src/sd_link.c -o t_e2e && python3 e2e.py ./t_e2e
python3 sim_spi_pio.py ../build/dcbus.pio.h             # needs the generated header: build first (pioasm comes with the Pico SDK)
cd ../../.. && sh tests/run.sh                          # the Pi's side is part of the add-on's tests (tests/test_dcbridge_saves.py)
sudo tests/dcbridge/test_net.sh                         # namespaces: DHCP, DNS, NAT, port forward, clean removal
```

`test_sd` runs a byte-exact port of KOS `sd.c` against the emulator and a fake
Pi with configurable delays. It covers init with and without an image, CSD
size, random single and multi-block reads and writes, busy back-pressure, a Pi
too slow for one read (KOS re-inits and recovers), and an edit applied at a
cold start. `e2e.py` does the same through a pty and the real Python daemon:
reads run at about 880 KB/s at Dreamcast bus speed.

## First bring-up checklist

1. Flash the board, plug it into the Pi and install the bridge (Settings > DC Bridge > Install, or `sudo ./install.sh --dcbridge`). Check
   that `ls -l /dev/dcbridge-*` and `ip link show dcnet0` both exist.
2. Run `watch -n1 'curl -s localhost:8085/api/bridge'` (or `cat /dev/dcbridge-ctl`
   with the service stopped). With the Dreamcast off it should show
   `"mode":"sense"`.
3. Boot any KOS program that prints to serial: the mode should flip to `uart`
   with a sensible `baud`. Run `sudo systemctl stop dcbridge-ppp`, then
   `picocom -b 115200 /dev/dcbridge-uart` (the USB-side baud doesn't matter),
   and you should see the KOS banner. Start the service again afterwards.
4. Start the save manager (`sudo systemctl status dcbridge-saves`), then boot
   openMenu with serial VMU enabled. The status should show `"spi":"sd"`, and
   `"sd":{"daemon":true,"ready":true,...}`. The first time, openMenu offers to
   create the game folder. After a game boot and a return to openMenu, the save
   appears on the web page with one version in history.
5. Boot a W5500-enabled KOS build: `"spi":"w5500"`, `"open":true`, and
   `underruns` should stay at **0**. If it climbs, put a logic analyser on
   SCLK/MISO and send me the trace, because that's the timing budget above.
   `dcbridge-net status` should show a DHCP lease for the Dreamcast on
   `dcnet0`, and the KOS program should resolve names and reach the internet.
6. Boot a KOS program that uses `ppp_scif_init()` (any baud): the bridge
   switches to `uart`, `journalctl -u dcbridge-ppp` shows LCP/IPCP completing,
   and `ppp10` comes up with the Dreamcast at 192.168.171.2.

Note: the save manager reads `/dev/dcbridge-ctl` itself (for the dashboard's status and `api/bridge`). For the raw JSON, use `curl localhost:8085/api/bridge`,
or stop `dcbridge-saves` before running `cat` on the port.
