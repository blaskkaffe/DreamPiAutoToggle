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

The other direction: openMenu on the Dreamcast tells the Pi what is on its SD card, and a phone page starts a game on the Dreamcast. The module came with an openMenu build (`openMenu/src/openmenu/src/backend/dreampi_link.c`) and was ported to the add-on's module system. Same transport as `/tag`: plain HTTP over the PPP link to the web service port. Nothing is pushed to the Dreamcast; a launch waits until openMenu asks.

**Wire protocol (openMenu to the Pi)**

- `GET /openmenu/poll?v=1&n=<games>&h=<hash>` every 3 s answers `openmenu 1`, then `NEED games` if the Pi's copy does not match the hash (or there is none), and `LAUNCH <product>` once when a launch is queued.
- `POST /openmenu/games` with `X-Requested-With: openMenu`; body `#openmenu-games 1 <hash> <count>`, then one game per line, tab separated: product, slot, disc, region, folder, name. Kept in `openmenu_games.json` (`core.OPENMENU_GAMES`), at most 5000 games.

**The phone page** (`layout.json`): the box shows the connection (a Dreamcast counts as connected while it was heard in the last 15 s), the players who can be joined, DC99 events and the games, each with **Start** / **Join** that asks first. `POST /openmenu/launch {"product"}` is refused unless the game is on the card and the Dreamcast is connected, expires after 60 s, and needs the PIN when one is set (it is a `PROTECTED` path; the Dreamcast's own paths cannot ask for one).

- **Join:** the online players in a game (from `players_cache.json`, the file the Online players module keeps; only while that module is on and its list is under 5 minutes old) whose game matches one on the card by name (same normalised name, else one name inside the other, the shortest wins).
- **Events:** the module downloads `https://dc99.net/community/` itself (at most every 10 minutes while the page is open) and reads the `const EVENTS = [ ... ]` list, as the DC99 events module does (see [events.md](events.md)); a Start button shows when a card game's name appears in an event's title or summary. Times are shown as DC99 gives them. If DC99 changes the page the box says so and keeps the events it had.
- **Games:** all games come as rows; the list widget's search box narrows them and 60 rows are drawn at most.

**Limits:** anyone who can open the page (and enters the PIN, if set) can start a game; a launch only works while openMenu is the running program and the link is up; joining a game here only starts it (its own dialing and lobby still apply). **Not run on a Dreamcast or a Pi**: the Pi side is tested off-hardware (`tests/test_openmenu.py`, the page by `tests/ui/openmenu.js`) and the openMenu side was only syntax-checked by its author.

