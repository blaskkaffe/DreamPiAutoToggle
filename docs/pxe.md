# Network-booted kiosk screens (PXE)

Read before touching `pxe/`. Back to [CLAUDE.md](../CLAUDE.md). **Not verified on hardware** (see [hardware-status.md](hardware-status.md)): the generated files and the kiosk session's address handling are unit-tested (`tests/test_pxe.py`); the image build, the boot and Firefox on a real screen have never been run.

## What it is
A screen with no disk and nothing installed: it boots from its network card, loads a small Debian image into memory and shows the board in Firefox kiosk mode, full screen. A reboot is a fresh start; nothing on the screen is ever changed. The host (the computer that ran `install.sh`) keeps the people and statuses as before; the screens only open its address.

## Parts
- `pxe/build-image.sh` (run once, on any Debian / Ubuntu computer with internet): debootstrap of Debian (`SUITE`, default bookworm) with `live-boot`, Xorg, Openbox, `firefox-esr`; overlay from `pxe/image/`; writes `vmlinuz`, `initrd.img`, `filesystem.squashfs` to `pxe/out/` (about 400-600 MB; a screen needs about 2 GB of memory because the image is loaded into RAM).
- `pxe/image/` (copied over the root file system): `kiosk.service` (autologin user `kiosk`, `xinit` on tty1, restarted if it dies), `usr/local/bin/kiosk-session` (reads `checkin_url=` and `checkin_location=` from the kernel command line, waits until the board answers, runs `firefox-esr --kiosk`, starts it again if it quits), Firefox `policies.json` (no updates, telemetry, first-run pages), systemd-networkd DHCP, the Xorg wrapper config.
- `pxe/install-pxe.sh` (run on the server, usually the host): installs `dnsmasq-base` and `ipxe`, copies the image to `/opt/checkin-board-pxe/`, writes the config with `pxe/pxe_config.py` and two systemd units: `checkin-board-pxe` (its own dnsmasq: **proxy DHCP** and TFTP) and `checkin-board-pxe-http` (`python3 -m http.server` on port 8069 for the kernel and the image). `--remove` undoes it.

## How a screen boots
1. The screen's firmware asks for DHCP. The router answers as usual; dnsmasq (proxy mode) adds "boot from here". No second DHCP server, so the router needs no change.
2. BIOS gets `undionly.kpxe`, UEFI gets `ipxe.efi` (TFTP). iPXE asks again, is recognised (DHCP option 175) and gets `boot.ipxe`.
3. `boot.ipxe` tries `screens/<mac-with-dashes>.ipxe` (may `set location ...`), then loads `vmlinuz` + `initrd.img` over HTTP with `fetch=.../filesystem.squashfs ip=dhcp checkin_url=<board> checkin_location=<buildings>`.
4. `live-boot` downloads the squashfs, systemd starts `kiosk.service`, `kiosk-session` opens `<board>/?location=...`.

## Per-building screens
`pxe/screens/<mac>.ipxe` (see `pxe/screens/README.txt`) sets `location`, spelled as on the board's building buttons (spaces `+`, several separated by a comma, non-ASCII percent-encoded). Re-run `install-pxe.sh` to copy new files. A screen without a file shows everybody.

## Rules
- The image knows no secrets; the board's PIN is for its settings only, and a screen only reads the board. Use it on a network you trust: anybody on it can boot from the server (and see the board).
- Do not run another DHCP server for this; the router stays the DHCP server.
- The board's address given to the screens is `--board-url` (default `http://<server ip>/`, the plain HTTP port; the kiosk does not need the self-signed HTTPS certificate).
- Firewall: UDP 67, 69 and 4011 (proxy DHCP), TCP 8069 on the server.
