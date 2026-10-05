# Telling openMenu which network this DreamPi runs (`GET /tag`)

Read before changing `/tag`, `core.tag()` / `core.TAGS` or the web port handling. Back to [CLAUDE.md](../CLAUDE.md).

**Goal:** a small message from the DreamPi that openMenu can notice ("Running DCNet!") without touching game traffic. openMenu keeps its own list of what each code means.

## How it travels

The Dreamcast is connected to the Pi by PPP, and the Pi's own services are reachable over that link. From DreamPi's `dreampi.py` (master, checked while writing this):

- `autoconfigure_ppp()` gives the Pi the PPP address `this_ip` (next unused address `.100` of the LAN subnet; with a VPN `tun0` up it is derived from that instead) and the Dreamcast `dc_ip`, and writes `ms-dns {this_ip}` into `/etc/ppp/options`: **the Dreamcast's DNS server is the Pi's own end of the link**, so openMenu can find the Pi's address from the DNS server / PPP peer it was given instead of a fixed IP.
- The INPUT firewall rules DreamPi adds only concern `tun0`; nothing blocks the Dreamcast from reaching the Pi's own port 80/the add-on's web port over `ppp0`.

So openMenu can do a plain HTTP request to the Pi. Nothing is sent to games: the Pi never pushes anything, it only answers when asked, and no DreamPi file or game-facing setting is touched.

**Not verified:** that openMenu (KallistiOS) can read the DNS-server/peer address this way, and the request itself from a real Dreamcast. Only the Pi side exists and is tested.

## The request

`GET /tag` (also `/tag?text`) on the web service port (80 by default; `--` any other port given to `install.sh` is in `/opt/dreampi-netswitch/install_ports`). Use HTTP/1.0 or 1.1 with `Connection: close`; the answer is plain text, one line, no caching:

```
GET /tag HTTP/1.0\r\n\r\n   ->   200 OK ... \r\n\r\nDCNET\n
```

| Code | Meaning | Suggested text (`/tag?text` returns it) |
|---|---|---|
| `DCNET` | DCNET is selected and available: other calls go to DCNET | Running DCNet! |
| `DCNOW` | DCNow! is selected | Running DCNow! |
| `DCNET_OFF` | DCNET is selected but DreamPi can't use it (not enabled in `netlink_config.ini`); calls go to DCNow! | DCNet is selected but not available |
| `INACTIVE` | DreamPi isn't running the add-on, nothing is being switched | (empty) |

Unknown future codes should be ignored by openMenu. The same code is in `GET /status` as `tag=` and the whole thing is `core.tag()`. Note that openMenu's own call (`111-1111`) always goes to DCNow! regardless of the selection, so the tag tells the player what *other* calls will use.

## Alternatives considered

- **DNS name** (a hostname only openMenu asks for, answered by the Pi's dnsmasq with a different address per code): needs no known Pi address, but needs an extra dnsmasq config line and a dnsmasq reload; a mistake there would take the Dreamcast's DNS down, so it was not done. Possible later as an opt-in.
- Anything at modem level (CONNECT string, tones): not controllable from here.

## The openMenu link module (`modules/openmenu/`)

The other direction: openMenu on the Dreamcast tells the Pi what is on its SD card, and a phone page starts a game on the Dreamcast. Same transport as `/tag`: plain HTTP over the PPP link to the web service port. Nothing is pushed to the Dreamcast; a launch waits until openMenu asks. The module pairs with an openMenu build that has `dreampi_link.c` (`openMenu/src/openmenu/src/backend/dreampi_link.c`).

**Wire protocol (openMenu to the Pi)**

- `GET /openmenu/poll?v=1&n=<games>&h=<hash>` every 3 s answers `openmenu 1`, then `NEED games` if the Pi's copy does not match the hash (or there is none), and `LAUNCH <product>` once when a launch is queued.
- `POST /openmenu/games` with `X-Requested-With: openMenu`; body `#openmenu-games 1 <hash> <count>`, then one game per line, tab separated: product, slot, disc, region, folder, name. Kept in `openmenu_games.json` (`core.OPENMENU_GAMES`), at most 5000 games.

**The phone page:** the box (`layout.json`: an `infobox` over `GET /openmenu/view`, every 5 s) shows the connection (a Dreamcast counts as connected while it was heard in the last 15 s) and how many games are on the card. Opened, the custom widget `openmenu-games` (`page.js`) lists
- the online players whose game is on the card, each with **Join** (the players come from the Online players module's data in the page, `S.players.list`, so the list is empty while that module is off; the game is matched by name: the same normalised name, else one name inside the other, the shortest wins);
- the card's games (`GET /openmenu/games`, read again when the hash in `/openmenu/view` changes) with a search box, 60 rows at most, each with **Start**.

Start / Join asks first, then `POST /openmenu/launch {"product"}`; it is refused unless the game is on the card and the Dreamcast is connected, and a launch nobody collects expires after 60 s. The buttons are off while the Dreamcast is not connected or a launch is waiting.

DC99 events are not handled here: the events module owns them.

**Limits:** anyone who can open the page can start a game (there is no PIN on it, like selecting a network); a launch only works while openMenu is the running program and the link is up; joining a game here only starts it (its own dialing and lobby still apply). **Not run on a Dreamcast or a Pi**: the Pi side is tested off-hardware (`tests/test_openmenu.py`, the page by `tests/ui/openmenu.js`) and the openMenu side was only syntax-checked by its author.
