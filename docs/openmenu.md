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

The other direction: openMenu on the Dreamcast tells the Pi what is on its SD card, the Pi tells it what is going on online, and a phone page starts a game on the Dreamcast. Same transport as `/tag`: plain HTTP over the PPP link to the web service port. Nothing is pushed to the Dreamcast; a launch and the live info wait until openMenu asks. The module pairs with an openMenu build that has `dreampi_link.c` (`openMenu/src/openmenu/src/backend/dreampi_link.c`).

**Wire protocol (openMenu to the Pi)**

- `GET /openmenu/poll?v=1&n=<games>&h=<hash>` every 3 s. The answer is plain text, one line each:
  - `openmenu 1`
  - `LAUNCH <product>` once, when a launch is queued
  - `NEED games` when the Pi's copy of the game list does not match the hash (or there is none)
  - `NET dcnow` or `NET dcnet`: the selected network (`dcnet` only when DreamPi can use it, the same rule as `GET /tag`)
  - `DCNET ok` or `DCNET off <why>`: whether DCNET works at all (`NET` says `dcnow` both when DCNow! is selected and when DCNET is selected but cannot be used, so this line says which). `why` is `config` (no `netlink_config.ini`), `disabled` (`[DCNet] enabled = yes` missing), `noupdates` (`/boot/noautoupdates.txt`) or `inactive` (DreamPi is not running the add-on's hook); same checks as `GET /tag`.
  - `PLY 2:3 1:1 27:2`: the card's games that someone plays online right now, each as `<slot>:<players>` (the `slot` field the Dreamcast uploaded), the most played first, at most 16. A game without a slot is left out; the line is left out when nobody plays.
  - `EVENT <unix start> <due> <title>`: a DC99 event, the start as a Unix time, `due` 1 when its reminder is due right now (the events module's reminder window), else 0 for the soonest upcoming one; the title is one line of at most 60 characters. Left out when the events module is off or has nothing coming. Read from `event_reminders.json` (`items` = due, `upcoming` = the next few), never from the module's code.
  - Lines an older openMenu does not know should be ignored; the new ones come after the old ones.
- `POST /dcnow` / `POST /dcnet` with `X-Requested-With: openMenu`: openMenu's "Use DCNow!" / "Use DCNET" buttons. They are the same two requests as the page's network buttons, answered by the network switcher module (204; the debug log says "openMenu: DCNET selected"), and the choice applies from the next call. The Dreamcast addresses the Pi at the DNS server it got over PPP and sends no `Origin`, which the page's own checks accept. The next poll answers `NET dcnow` / `NET dcnet`, which openMenu uses to recolour its panel borders. These two paths must stay open (no PIN) because the Dreamcast cannot enter one.
- `POST /openmenu/games` with `X-Requested-With: openMenu`; body `#openmenu-games 1 <hash> <count>`, then one game per line, tab separated: product, slot, disc, region, folder, name. Kept in `openmenu_games.json` (`core.OPENMENU_GAMES`), at most 5000 games.

**Who is playing, and the table of online games.** Both come from the Online players module's file `players_cache.json` (`core.PLAYERS_CACHE`), never from its code: the players in a game (only while the list is under 5 minutes old) and the table of games that work online (Dreamcast Live: status *online* or *work in progress*; *offline* does not count). A player's game is matched to a card game by name (the same normalised name, else one inside the other, the shortest wins). While a Dreamcast is polling and that list is older than 45 s, the poll asks for a new one (`core.poke("players")`, at most every 30 s; the players module's watcher reads the list then if it is older than 20 s), so the live info is current with no page open.

**Announcing itself to the rest of the add-on.** `module.json` has `"launcher": {"title", "state", "games", "start"}`: the data sources that hold the link's state (`GET /openmenu/view`: `connected`, `busy`) and the card's games (`GET /openmenu/games`: every game with `"online": true/false`, `"filtered"`), and the path that starts one (`POST /openmenu/launch {"product"}`). The loader puts the announcement in the page layout while the module is on (`layout()["launcher"]`); a list row with `"start": {"game": field}` (or `{"game": field, "text": field}` for free text such as an event) then gets a **Join button** for a game that is announced as online, on the card and while the Dreamcast is connected: the Online players box (every game, and the players in it), and the DC99 events list (an event whose title or text names a game). Only the card games that are in the table of online games are announced as online; when the table is not known (the Online players module is off, or has not read it yet) every card game counts. With the module off no list has a button.

**The phone page:** the openMenu box (`layout.json`: an `infobox` over `GET /openmenu/view`, every 5 s) shows the connection (a Dreamcast counts as connected while it was heard in the last 15 s) and how many games are on the card. Opened, the custom widget `openmenu-games` (`page.js`) lists all the card's games (`S.om_games`, read again when the hash in `/openmenu/view` changes) with a search box, 60 rows at most, each with **Start**. Joining a player's game is the Join button in the Online players box. Start / play asks first, then `POST /openmenu/launch`; it is refused unless the game is on the card and the Dreamcast is connected, and a launch nobody collects expires after 60 s. The Join buttons are not shown while the Dreamcast is not connected and are off while a launch is waiting; the Start buttons in the openMenu box are off then.

DC99 events are not handled here: the events module owns them.

**Limits:** anyone who can open the page can start a game (there is no PIN on it, like selecting a network); a launch only works while openMenu is the running program and the link is up; joining a game here only starts it (its own dialing and lobby still apply). **Not run on a Dreamcast or a Pi**: the Pi side is tested off-hardware (`tests/test_openmenu.py`, `tests/test_players.py`, the page by `tests/ui/openmenu.js`); the openMenu side was only syntax-checked by its author and does not read `NET` / `DCNET` / `PLY` / `EVENT` yet.
