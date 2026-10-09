# Network-booted kiosk screens (PXE)

Read before touching `pxe/`. Back to [CLAUDE.md](../CLAUDE.md). **Not verified on hardware** (see [hardware-status.md](hardware-status.md)): the generated files, the boot logic, the boot server over HTTP, the admin tool, the kiosk session's address handling and the per-screen settings are unit-tested (`tests/test_pxe.py`, `tests/test_screens.py`); the image build, the boot on real BIOS / UEFI hardware, Firefox in kiosk mode and the local-install wizard have never been run.

## What it is
A screen with no disk and nothing installed: it boots from its network card, shows a boot menu (or goes straight on), loads a small Debian image into memory and shows the board in Firefox kiosk mode, full screen. A reboot is a fresh start. The host (the computer that ran `install.sh`) keeps the people and statuses as before; a screen only opens its address, and **each screen's layout and settings are kept on the host under the screen's serial number**, so they are there again after a reload or a reboot.

## Parts
- `pxe/build-image.sh` (run once, on any Debian / Ubuntu computer with internet): debootstrap of Debian (`SUITE`, default bookworm) with `live-boot`, Xorg, Openbox, `firefox-esr`, the install wizard's tools and GRUB; overlay from `pxe/image/`; writes `vmlinuz`, `initrd.img`, `filesystem.squashfs` to `pxe/out/` (about 500-700 MB; a screen needs about 2 GB of memory because the image is loaded into RAM).
- `pxe/image/` (copied over the root file system): `kiosk.service` (user `kiosk`, `xinit` on tty1, restarted if it dies), `checkin-install.service` and `checkin-shell.service` (they run instead of the kiosk when the kernel command line has `checkin_install` / `checkin_shell`), `usr/local/bin/kiosk-session` (Firefox kiosk on the board), `usr/local/share/checkin-kiosk/loading.html` + `logo.png` (the loading screen), `usr/local/bin/checkin-install` (the wizard), Firefox `policies.json`, systemd-networkd DHCP.
- `pxe/pxe_config.py` renders `dnsmasq.conf` (proxy DHCP + TFTP) and the first iPXE script `boot.ipxe`; `pxe/pxe_boot.py` is the logic (machine names, the registry, the images, the boot script); `pxe/pxe_server.py` is the boot server (stdlib HTTP); `pxe/pxectl.py` is the admin tool `checkin-pxe`.
- `pxe/install-pxe.sh` (on the server, usually the host): installs `dnsmasq-base` and `ipxe`, copies the image to `/opt/checkin-board-pxe/www/images/kiosk/`, writes the config and two systemd units: `checkin-board-pxe` (its own dnsmasq, **proxy DHCP** and TFTP, so the router stays the DHCP server) and `checkin-board-pxe-http` (`pxe_server.py`, port 8069). `--remove` undoes it.

## How a screen boots
1. The firmware asks for DHCP. The router answers as usual; dnsmasq (proxy mode) adds "boot from here". BIOS gets `undionly.kpxe`, UEFI gets `ipxe.efi` (TFTP); iPXE asks again, is recognised (option 175) and gets `boot.ipxe`.
2. `boot.ipxe` **reports the computer to the boot server**: `GET /boot?serial=${serial}&mac=${net0/mac}&product=..&ip=..` (iPXE reads the serial number from the BIOS). The server always remembers it (`data/registry.json`: serial, MAC, address, first / last seen, boots: the **"has connected" list**), then checks the **whitelist** (`data/access.json`):
   - **Not on it (pending) or blocked:** no boot script. The screen prints "This computer is not approved yet" with its serial number, MAC address and name (or "has been blocked"), waits 15 s and boots its own disk. It stays in the list so the admin can allow or block it.
   - **On it** (its name / serial **or** its MAC is allowed; a block wins): the server gives its address a 30 minute pass to fetch the images, the screen prints "Connected to the check-in boot server: approved (...)" and the script below follows.
3. The script depends on the computer:
   - **Set to an image** (`checkin-pxe assign`): no menu. It says what it boots and waits 3 s: **press I to install on the local disk** (only when the image can be installed), else it boots the image.
   - **Installed on its own disk**: boots the disk after 3 s; press **N** for the network menu.
   - **Otherwise a menu** (20 s, then the first image): every image (`1`, `2` ...), **Install ... on the local disk** (`i`) and **Linux shell** (`s`) for the images that allow them, **iPXE shell**, **Boot from the local disk**.
4. A Linux image gets a command line with `checkin_url=` (the board), `checkin_server=`, `checkin_screen=` (the computer's name, below) and `checkin_location=`. `live-boot` downloads the squashfs, `kiosk.service` starts X and `kiosk-session` shows the **chicken logo** (`feh` on the X background at once, then Firefox opens `loading.html#<board address>`), which asks the board's `/ping` every 2 s and opens `<board>/?screen=<id>&location=...` as soon as it answers; so there is one loading screen from X starting to the board appearing, also when the board is slow after a power cut. The logo is copied from the CheckinChicken repository (`public/logo.png`). There is no boot splash before X (the text of the kernel and live-boot shows first); a Plymouth splash is not built.

## Computer names, the whitelist, per-computer settings
A computer is named by its serial number in lower case (other characters become `_`); a computer with no usable serial number ("To Be Filled By O.E.M.", all zeros, ...) is named `mac-<mac without dashes>`. Computers that share one serial number share one name (and one layout) - give them different ones by assigning from the MAC-named list or fix the BIOS.

```
checkin-pxe pending                               # connected but not decided (the "has connected" list, only the waiting ones)
checkin-pxe list                                  # everybody: status (allowed / PENDING / blocked), MAC, address, last seen, settings
checkin-pxe allow <serial or MAC> ...             # whitelist (also for a computer that has not connected yet)
checkin-pxe block <serial or MAC> ...             # never boots; wins over the whitelist
checkin-pxe clear <serial or MAC> ...             # off both lists (pending again)
checkin-pxe mode whitelist | open                 # whitelist is the default; open = everybody boots (the old behaviour, no checks)
checkin-pxe images                                # what the menu offers
checkin-pxe assign <id> kiosk --location "Område A,Område B" --board-url http://other/ --args "foo=bar"
                                                  # this computer's boot settings: skip the menu, boot that image, show those buildings,
                                                  # another board address, extra kernel arguments (letters, digits and _.=,:/+%@- only)
checkin-pxe unassign <id>                         # the menu again
checkin-pxe reinstall <id>                        # an installed computer boots from the network again
checkin-pxe forget <id>                           # off the has-connected list
```
Settings are in `data/assignments.json`, the whitelist in `data/access.json`, both read at every boot. There is no web page for this yet.

## More images
A folder `/opt/checkin-board-pxe/www/images/<id>/` with the files and an `image.json` appears in the menu at the next boot: `name`, `kernel`, `initrd` (file names), `args` (the kernel command line), optional `install_args` (the command line that starts its installer: if it is there the image can be installed on the local disk; the menu and the I key offer it), `shell_args` (a command line that opens a shell), `order`. In the command lines `{base}` (the image's folder on the server), `{server}`, `{board}`, `{screen}` and `{location}` are filled in. The check-in image's own manifest is `pxe/kiosk-image.json`.

## Local install (the wizard)
`checkin-install` (whiptail, on the console): choose the disk, the computer's name, the board's address and the buildings, confirm twice, then it makes a GPT (a BIOS-boot partition, a 512 MB EFI partition, ext4 root), copies the running system with `rsync` (from the squashfs live-boot mounted, kernel included), writes `fstab`, hostname and `/etc/checkin-kiosk.conf`, installs GRUB for BIOS and UEFI (removable path, so no firmware boot entry is needed), tells the boot server (`GET /installed?id=`) and restarts. The computer then boots the kiosk from its disk (`kiosk-session` reads the config file instead of the kernel command line). Run `checkin-pxe reinstall <id>` to network-boot it again. The wizard can also be started by hand from the shell entry.

## The shell
**Linux shell** in the menu boots the image with `checkin_shell`: a root shell on the console instead of the kiosk (no password; anyone at the keyboard of a network-booted computer has that anyway). `exit` starts the shell again; `reboot` restarts.

## Per-screen layout and settings
The page sends `X-Screen: <id>` (from `?screen=<id>` in its address, kept in `sessionStorage`). `base_core` then reads and writes `screens/<id>/screen.json` (columns, stretch, scale, theme ..., and `locations`: the buildings the screen shows) and `screens/<id>/tile_layout.json` (where the tiles are), starting from the shared files until the screen changes something. At most 200 screens; a plain browser (no id) uses the shared files as before. Module colours, the palette, the module order and the roster itself stay shared. The roster keeps its building choice in the browser, and for a screen with an id also on the host (`POST /screen/locations`): `?location=` in the address is the starting choice, else the browser's, else the host's.

## Rules
- The whitelist keeps strangers from booting from the server and from fetching the image (files are only served to the address of an approved computer for 30 minutes after its `/boot` request). It is **not strong authentication**: the serial number and MAC address are what the computer says they are, so somebody who copies an approved computer's numbers on the same network gets in; and the DHCP / TFTP part (the small iPXE program) is offered to every computer. The image holds no secrets and the board's PIN protects its settings, but anybody on the network can open the board's address in a browser anyway.
- Do not run another DHCP server for this; the router stays the DHCP server.
- A screen that is told no address uses `http://checkinchicken.local/` (the image has avahi / nss-mdns; `install.sh --hostname=checkinchicken` makes the host answer to it). The address given to the screens is `--board-url` (default `http://<server ip>/`, the plain HTTP port; the kiosk does not need the self-signed HTTPS certificate).
- A computer that gets no script boots its own disk; it is never locked out of the machine itself.
- Firewall: UDP 67, 69 and 4011 (proxy DHCP), TCP 8069 on the server.
