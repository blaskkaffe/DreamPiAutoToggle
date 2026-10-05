"""Demo server for looking at the page and for tests/ui/audit.js: the real web
service on a sandbox (all paths in a temp dir). Switches via environment:
LEDS=n (default 3), WIFI=1, WIFIDEMO=1 (dummy Wi-Fi networks + the setup loop),
BG=1 (the Dreamcast background module on), CLOCK=1 (the clock module on; off by default so the box counts are stable), EVENTS=1 (the DC99 events module on, with its sample events; EVENTSOON=1 adds a reminded event 5 minutes ahead), OPENMENU=1 (the openMenu link module on, with a made-up SD card of 72 games and a Dreamcast that polls every 3 s; OPENMENU=quiet: the Dreamcast never polls), FAKEUPDATE=1 (fake GitHub: an update is available; FAKELOG=1 adds a failed update with a messy log), FAKEPLAYERS=1 (made-up
players; PLAYERSFAST=1 makes the downloads slow and the list stale after 3 s), OFF=led,wifi,... (modules switched off in the module picker; OFF=all = every module the picker can switch, only the always-on ones stay), PIN=1234 (a PIN for update/restart/Wi-Fi; restart is faked), PORT=n (default 8734)."""
import sys, os, threading, time, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from support import web, core, sandbox
import netswitch_wifi_setup as wifi
tmp = sandbox(wifi)
with open(core.LED_COUNT, 'w') as f: f.write(os.environ.get('LEDS', '3'))
core.save_module_enabled("debuglog", True)     # off by default; on here so the page shows it (OFF=debuglog switches it off again)
if os.environ.get("BG"): core.save_module_enabled("background", True)
if not os.environ.get("CLOCK"): core.save_module_enabled("clock", False)      # the checks count the dashboard boxes: the clock box is only there with CLOCK=1
os.environ.setdefault("DC99_MOCK", "1")       # the events module reads its sample events, never dc99.net
if not os.environ.get("EVENTS"): core.save_module_enabled("events", False)    # likewise: the DC99 events box only with EVENTS=1
if os.environ.get("EVENTS"):
    import netswitch_events as ev
    ev.import_events()                        # the sample events (moved on so they lie ahead)
    if os.environ.get("EVENTSOON"):           # EVENTSOON=1: one reminded event starts in 5 minutes (banner, highlight)
        ev.store([dict(ev.normalize({"title": "Demo Game Night", "date": time.strftime("%Y-%m-%d %H:%M:00", time.gmtime(time.time() + 300 + (ev.tz.offset("America/New_York") or 0))),
                                     "source": "manual", "url": "/events/demo-game-night", "external": False}))] +
                 [r for r in (ev.normalize(e) for e in ev.sample_events()) if r])
        demo = ev.query("title=?", ("Demo Game Night",))[0]
        ev.save_config({"picked": [str(demo["id"])]}); ev.write_reminders()
if not os.environ.get("OPENMENU"): core.save_module_enabled("openmenu", False)      # likewise: the openMenu link box only with OPENMENU=1
if os.environ.get("OPENMENU"):
    import netswitch_openmenu as om
    card = "#openmenu-games 1 demo0001 72\n" + "".join("DEMO%03d\t%d\t1/1\tU\t\tDemo Game %02d\n" % (i, i, i) for i in range(1, 71)) + \
        "T1234N\t71\t1/1\tU\t\tQuake III Arena\nMK51035\t72\t1/2\tU\tRacing\tCrazy Taxi\n"
    om.save_games(*om.parse_games(card))
    if os.environ["OPENMENU"] != "quiet":
        def heartbeat():            # the Dreamcast's openMenu asks every 3 seconds
            while True:
                om.poll_reply("v=1&n=72&h=demo0001")
                time.sleep(3)
        threading.Thread(target=heartbeat, daemon=True).start()
if os.environ.get("WIFI"): core.save_module_enabled("wifi", True)
if os.environ.get("WIFIDEMO"):
    core.save_module_enabled("wifi", True); open(core.WIFI_DEMO, "w").close()
    wifi.SCAN_WAIT = 3
    def loop():     # what netswitch_wifi_service.py does
        while True:
            if wifi.start_requested():
                wifi.clear_flags()
                wifi.setup_cycle(wifi.wifi_iface())
            else:
                wifi.clear_flags(); wifi.set_state("idle")
            time.sleep(1)
    threading.Thread(target=loop, daemon=True).start()
if os.environ.get("FAKEUPDATE"):
    import subprocess
    import netswitch_update as up
    import netswitch_probes
    src = os.path.join(tmp, "DreamPiAutoToggle"); os.mkdir(src)
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=src)
    subprocess.check_call(["git", "remote", "add", "origin", "https://github.com/blaskkaffe/DreamPiAutoToggle.git"], cwd=src)
    open(os.path.join(src, "install.sh"), "w").write("#!/bin/sh\n")
    subprocess.check_call(["git", "add", "."], cwd=src); subprocess.check_call(["git", "commit", "-q", "-m", "x"], cwd=src, env=env)
    open(core.ADDON_SRC, "w").write(src); open(core.ADDON_COMMIT, "w").write("a"*40)
    open(netswitch_probes.ADDON_VERSION, "w").write("2026-09-30 12:00 (aaaaaaa)")
    dp = os.path.join(tmp, "dp"); os.mkdir(dp); netswitch_probes.DREAMPI_DIR = dp
    open(os.path.join(dp, "dreampi.py"), "w").write("#dreampi.py_version=202601010000\n")
    def fake(url):
        if "/commits/" in url: return json.dumps({"sha": "b"*40, "commit": {"committer": {"date": "2026-10-02T10:00:00Z"}}})
        if "/compare/" in url: return json.dumps({"status": "ahead", "ahead_by": 4})
        return "#dreampi.py_version=202608171113\n"
    up.fetch = fake
    up._spawn = lambda cmd: open(core.UPDATE_STATUS, "w").write("running")
    if os.environ.get("FAKELOG"):      # a finished update with a messy log: long lines, colour codes, progress
        open(core.UPDATE_STATUS, "w").write("failed")
        open(core.UPDATE_LOG, "w").write("Updating /home/pi/DreamPiAutoToggle from origin/main\nFrom https://github.com/blaskkaffe/DreamPiAutoToggle\n"
            " * branch            main       -> FETCH_HEAD\nReceiving objects:  10%\rReceiving objects: 100% (42/42), done.\n"
            "Updating 3baa024..21d1ad8\nFast-forward\n page/players.js | 84 ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++\n"
            " 4 files changed, 64 insertions(+), 37 deletions(-)\n\x1b[31mERROR\x1b[0m: could not write /etc/systemd/system/dreampi-netswitch.service (Read-only file system)\n"
            "A_very_long_unbroken_path_/opt/dreampi-netswitch/page/players_and_more_and_more_and_more_and_more.js\nfailed\n")
if os.environ.get("OFF"):         # modules switched off, as from the module picker (the always-on ones can't be)
    for name in (core.module_names() if os.environ["OFF"] == "all" else os.environ["OFF"].split(",")):
        core.save_module_enabled(name, False)
    web.refresh_page(force=True)
if os.environ.get("PIN"):
    import netswitch_security
    netswitch_security.set_pin(os.environ["PIN"])
    __import__("netswitch_rebootupdate")._spawn_reboot = lambda: None
if os.environ.get("FAKEPLAYERS"):
    import netswitch_players as pl
    feed = {"dreampi": {"users": [
                {"username": "Dave", "country": "US", "current_game_display": "Quake III Arena", "online": True},
                {"username": "Eve_with_a_really_long_gamertag", "country": "SE", "current_game_display": "Daytona USA 2001", "online": True},
                {"username": "Idle Ida", "country": "GB", "current_game_display": "", "online": True}]},
            "dcnet": {"online": True, "players": [
                {"name": "Alice", "gameName": "Phantasy Star Online", "geoloc": {"country": "DE"}},
                {"name": "Carol", "gameName": "Outtrigger", "geoloc": {"country": "FR"}}]}}
    feed["kosnet"] = {"online": True, "players": [{"name": "Kay", "gameName": "KOS Game", "geoloc": {"country": "JP"}}]}
    users = {"users": [{"username": "Dave", "country": "US", "current_game_display": "Quake III Arena", "online": True}]}
    games = {"games": [{"name": "Phantasy Star Online", "status": "green"}, {"name": "Quake III Arena", "status": "green"},
                       {"name": "Outtrigger", "status": "work in progress"}, {"name": "Dead Game Online", "status": "red"}]}
    def fake_fetch(url):
        if os.environ.get("PLAYERSFAST"): time.sleep(1.5)      # PLAYERSFAST=1: a slow download and a list that is stale after 3 s, to watch a refresh happen
        return json.dumps(games if "dreamcastlive" in url else users if "dreamcast.online" in url else feed)
    pl.fetch = fake_fetch      # the real default source (dc99.net) is used, only the download is faked
    if os.environ.get("PLAYERSFAST"): pl.CACHE_SECONDS = 3
print("state dir", tmp, flush=True)
srv = web.Server(('127.0.0.1', int(os.environ.get('PORT', '8734'))), web.Handler)
srv.serve_forever()
