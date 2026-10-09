# Offline install

Read before touching `offline/`. Back to [CLAUDE.md](../CLAUDE.md). Tested: the package closure, download and local-repository install of a small package (`ipxe`) on Ubuntu 24.04 with internet; **never run with the full list on a real offline computer**, and Firefox / Chromium on Ubuntu (snaps) are untested (see [hardware-status.md](hardware-status.md)).

## The idea
`install.sh` downloads nothing: it needs Python 3, `openssl` (for HTTPS) and, optionally, `git`. The network boot server needs `dnsmasq-base` and `ipxe` and an image. The browsers (Firefox ESR, Chromium) and `mpv` come from the distribution. So a computer without internet needs those packages, the repository and (for network boot) the image brought over.

1. **On a computer with internet, running the same distribution, release and CPU type as the offline one:**
   `sudo ./offline/prepare-offline.sh [--with-image] [--out=DIR]` makes the *bundle* (default `offline/bundle/`):
   - `debs/`: every package of `offline/packages.txt` and everything they depend on (`apt-cache depends --recurse`), as a local apt repository (`Packages.gz`);
   - `snaps/`: Ubuntu only (its Firefox and Chromium are snaps): `snap download` of both (`--no-snaps` leaves them out);
   - `repo/`: a copy of this repository (with `.git`, so the version shows);
   - `image/`: with `--with-image`, the network boot image (`pxe/build-image.sh`, needs `debootstrap` and about 1 GB of downloads);
   - `install-offline.sh`, `packages.txt`, `README.txt`.
2. **Copy the folder** to the offline computer (USB disk).
3. **There:** `sudo ./install-offline.sh [--board] [--pxe] [-- <install.sh options>]`. Without options it only installs the packages, from a temporary apt sources list that names the bundle's `debs/` (nothing else is read, nothing else is changed); `--board` then runs `repo/install.sh`; `--pxe` runs `repo/pxe/install-pxe.sh --image=<bundle>/image` (it skips `apt` when `dnsmasq` and the iPXE files are already installed).

Add or remove packages in `offline/packages.txt` (Debian names, one per line). The list has `python3 openssl git ca-certificates curl rsync`, **`firefox-esr chromium mpv`**, `dnsmasq-base ipxe` and, for building the image on that computer, `debootstrap squashfs-tools`.

Rules: the offline computer must match the online one (a Debian 12 bundle on a Debian 12 computer; the packages are the ones of the release the online computer runs, and an installed package that is already newer is kept). Updates afterwards: **Settings > System > Update from a USB stick** (see the README), not "Update now".

`mpv` is installed (host bundle and network-boot image) but nothing in the board uses it yet.

## Restart on crash
- **Browsers.** Host kiosk: `kiosk/kiosk-browser.sh` runs Chromium in a loop, so it starts again two seconds after it crashes or is closed (and with `--hide-crash-restore-bubble` / `--disable-session-crashed-bubble` there is no "restore pages" prompt). Network-booted screens: `kiosk-session` loops the same way for **Firefox** (default; the profile policy turns session restore off) and **Chromium** (`checkin_browser=chromium` on the kernel command line, or `CHECKIN_BROWSER` in `/etc/checkin-kiosk.conf`; a clean profile at every start). If X or the session script dies, `kiosk.service` (`Restart=always`) starts it again.
- **The web service** (`checkin-board.service`): `Restart=always`, no start limit (as before).
- **The computer.** `install.sh` (and the image, and a local install made by its wizard) set `kernel.panic = 10` and `kernel.panic_on_oops = 1` (a kernel panic restarts the computer after 10 s; `panic=10` is also on the kernel command line of the image) and `RuntimeWatchdogSec=60`, `RebootWatchdogSec=10min` for systemd (it feeds `/dev/watchdog`; if systemd hangs for a minute the computer restarts). The watchdog only works where the hardware has one; the image also loads `softdog` as a software fallback. The host does not load `softdog` by itself. `uninstall.sh` removes the host's settings (they apply from the next boot).
