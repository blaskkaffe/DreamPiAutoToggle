# DC99 events module

Read before changing `modules/events/`. Back to [CLAUDE.md](../CLAUDE.md).

## Where the events come from (checked October 2026)

The calendar on <https://dc99.net/community/> (tabs DC99, Sega Online Discord, DreamcastLive; an Upcoming list) was opened in a
browser and its network requests and scripts were read:

1. **What the calendar does:** a script in the page draws the month grid and the list in the browser. While loading, the page asks
   for its stylesheet, two logos and `/online/dcnet_status.php` (the player counts) and nothing else: **there is no events API**.
2. **The data:** the list is written into the page itself, in a script: `const EVENTS = [ ... ];` (JSON). The calendar draws from it.
3. **The source the module uses:** `GET https://dc99.net/community/` (no parameters, about 84 KB of HTML); the JSON after
   `const EVENTS =` is read with a JSON decoder (`extract_events()`). There is no other structured source, so nothing is scraped from
   the drawn calendar.
4. **One event:**

```json
{"title": "US Game Night", "date": "2026-10-08 21:00:00", "endDate": null, "allDay": false, "location": null,
 "summary": "Join hawkzero for Thursday night dreamcastin'", "source": "discord",
 "url": "/events/us-game-night-2026-10-08", "external": false}
```

- **Sources:** `discord` (shown as "Sega Online Discord", 112 events at the time), `dreamcastlive` ("DreamcastLive", 96, with an
  `endDate`) and `manual` ("DC99", 1). The page's own `SOURCE_LABELS` gives the names.
- **Range:** about a year ahead, all in one list; no paging, and no separate "upcoming" endpoint (the home page renders its upcoming
  list on the server).
- **Ids:** none. A `discord` or `manual` event has a page, `/events/<slug>`, and the slug is used as its id. Every DreamcastLive event
  links to the same schedule page (`external: true`), so their id is made from source, title and time: an event that DreamcastLive
  moves to another time becomes a new event, and the old one is marked removed.
- **Times:** `"YYYY-MM-DD HH:MM:SS"`, no time zone. DC99's code says they are "normalized to one timezone server-side", but they
  are not all in one zone: DreamcastLive's own schedule says *Game Night, Wednesdays 9:00 PM Eastern* and *Game Night UK, Sundays
  8:00 PM UK*, and DC99 lists them at 21:00 and 20:00. So a time is read as **US Eastern** (`America/New_York`, with its summer
  time) and as **UK time** (`Europe/London`) for an event with "UK" as a word in its title (`source_zone()`). The Discord events are
  "Thursday night" US games at 21:00, which fits Eastern. If DC99 starts writing real time zones, this is the one place to change.

## The importer and the store

`import_events()` fetches the page (10 s timeout, two more tries 4 s apart on a network error; a page without the list is not
retried), normalizes each event (`normalize()`: source, source_event_id, title, game, description, start and end as unix times,
the source's time zone, location, network, absolute url, the raw JSON) and stores them in SQLite, `core.EVENTS_DB`
(`/opt/dreampi-netswitch/events.db`, table `events`, unique on `(source, source_event_id)`, plus `meta` for the last sync):

- new events are added, events whose raw data or time changed are updated in place (`last_updated`), every seen event gets
  `last_seen`;
- a **future** event that is no longer in the list is marked `removed` (and comes back if it is seen again); past events stay as
  history;
- a failed download, a page without the list or an empty list is recorded (`last_error`) and **changes nothing else**: the stored
  events stay.

`game` is only filled when the title names the game the way DreamcastLive does (*Game Night: Sega Tetris*, *Game Night UK: F355
Challenge*); `network` is always empty (DC99 does not say). Nothing is guessed.

The sync runs in the web service's background (`start()`): every hour by default, set in Settings (15 minutes to 12 hours) or by
the environment, `DC99_SYNC_INTERVAL=15m` (`s`, `m`, `h` or plain minutes; it wins over the setting). **Sync now** and
`POST /api/sync` start one at once. With `DC99_MOCK=1` (or `"mock": true` in `events.json`) the module reads
`modules/events/sample_events.json` instead: twelve real events copied from the page in October 2026 (the DC99 one moved from
23 September to 12 October), moved on by whole weeks so they lie ahead. The demo server uses it (`EVENTS=1`, and `EVENTSOON=1` adds
a reminded event five minutes ahead).

The importer logs one line per sync to the service's journal (`journalctl -u dreampi-netswitch`): `events: synced ... (n new, n
changed, n removed)` or `events: sync failed, the stored events are kept: ...`.

## Reminders

- **One event:** the bell in the box (`POST /events/remind {"id", "on"}`). **A series:** Settings > DC99 events > *Always remind
  me of* (`GET`/`POST /events/series`, a picker with the titles of the coming events as choices; up to 12).
- `write_reminders()` writes the reminded events of the next 30 days to `core.EVENT_REMINDERS` (`event_reminders.json`: `lead`,
  `after`, `items` `[{"id", "title", "start"}]`, `upcoming` (the next 5 coming events, reminded or not, same shape; read by `core.next_event()` for the openMenu link's `EVENT` line), `dismissed`), after every change and every minute from the background loop.
  `core.event_reminder(now)` reads it: an item is due from `lead` minutes before its start (5 to 60, default 15) until `after`
  (10) minutes after, unless dismissed.
- While one is due: the module's `api()` adds a **notice** (the banner; its ✕ is `POST /events/dismiss`) and **highlights** the
  `clock` box and its own `events` box (the base's highlight, see [modules.md](modules.md)); the LED service's `gather()` asks
  `core.event_reminder()` too and lights **Event starting soon** (`event-soon`), so the LED works without the page open.
- Picks of events that are gone, and dismissals of past events, are dropped by `write_reminders()`.

## The JSON API

For other programs on the network (an openMenu companion, a second dashboard). Times are ISO 8601 with the offset of the display
zone: the common time zone (Settings > About, `core.time_zone()`; default the Pi's own) or `?tz=<IANA zone>`.

| Request | Answer |
|---|---|
| `GET /api/events` | `{"timezone", "count", "events": [...]}`; filters `source`, `game`, `network` (exact, any case), `from` / `to` (`YYYY-MM-DD` in the display zone, `to` includes that whole day), `limit` (default 1000), `removed=1` (include removed ones), `tz` |
| `GET /api/events/upcoming` | the same, from now on, sorted by time, `limit` default 20 |
| `GET /api/events/<id>` | one event, with its `raw_data` from DC99; 404 when unknown |
| `GET /api/sources` | `{"sources": [{"id", "label", "events"}]}` |
| `GET /api/games` | `{"games": [{"game", "events"}]}` (only the games named in titles) |
| `GET /api/status` | `{"database", "source": "dc99", "url", "mock", "events", "upcoming", "last_import", "last_import_utc", "last_attempt", "last_error", "syncing", "sync_interval_minutes", "timezone"}` |
| `POST /api/sync` | starts a sync in the background; answers the status plus `"started"` (false when one is running). Like every POST it needs the page's `X-Requested-With` header (see the security notes in [web.md](web.md)) |

An event: `id`, `source`, `source_label`, `source_event_id`, `title`, `game`, `description`, `start_time`, `end_time`, `all_day`,
`timezone`, `source_timezone`, `location`, `network`, `url`, `removed`, `reminded`, `last_seen`, `last_updated`.

The API answers only while the module is on (404 otherwise, like every module path).

## Files

`modules/events/`: `netswitch_events.py` (everything above), `layout.json`, `page.js` (the `events-list` widget), `page.css`,
`sample_events.json`. Settings in `/opt/dreampi-netswitch/events.json` (`lead`, `interval`, `picked`, `series`,
`dismissed`, `mock`), the store in `events.db`, the reminders in `event_reminders.json`. Tests: `tests/test_events.py` (parsing,
time zones with and without `zoneinfo`, duplicates, updates, removed events, failed imports, mock mode, API filters, reminders,
banner, highlight, LED message, settings) and `tests/ui/events.js` (the box, bells, banner, highlight, settings in a browser).
