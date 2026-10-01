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
