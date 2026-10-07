"""Demo server for looking at the page and for the browser checks (audit.js, functional.js ...): the real web service on a sandbox (all paths
in a temp dir), with the 25 people of tests/ui/people.csv imported. Switches via environment:
IN=n (the first n people start checked in, one of them with a status),
FAKEUPDATE=1 (fake GitHub: an update is available; FAKELOG=1 adds a failed update with a messy log),
IMGBG=1 (the Background image module on), CLOCK=1 (the clock module on; off by default so the box counts are stable), EMPTY=1 (no people imported), PEOPLE=file.csv (another roster),
OFF=clock,... (modules switched off in the module picker; OFF=all = every module the picker can switch, only the always-on ones stay),
PIN=1234 (a PIN for update / restart / import; restart is faked), PORT=n (default 8734)."""
import sys, os, threading, time, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from support import web, core, sandbox
import netswitch_contacts as contacts
import netswitch_checkin as checkin
tmp = sandbox(contacts, checkin)
if not os.environ.get("CLOCK"): core.save_module_enabled("clock", False)      # the checks count the dashboard boxes: the clock box is only there with CLOCK=1
if not os.environ.get("EMPTY"):
    with open(os.environ.get("PEOPLE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "people.csv"), encoding="utf-8") as f:
        contacts.import_csv(f.read())
    n = int(os.environ.get("IN", "0"))
    if n:
        people = [p for g in checkin.snapshot()["groups"] for p in g["people"]]
        for p in people[:n]: checkin.toggle(p["id"])
        if n > 2: checkin.set_status(people[1]["id"], "LATE", "08:15"); checkin.set_status(people[2]["id"], "SICK")
if os.environ.get("IMGBG"): core.save_module_enabled("imagebg", True)
if os.environ.get("FAKEUPDATE"):
    import subprocess
    import netswitch_update as up
    import netswitch_probes
    src = os.path.join(tmp, "checkout"); os.mkdir(src)
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=src)
    subprocess.check_call(["git", "remote", "add", "origin", "https://github.com/blaskkaffe/DreamPiAutoToggle.git"], cwd=src)
    open(os.path.join(src, "install.sh"), "w").write("#!/bin/sh\n")
    subprocess.check_call(["git", "add", "."], cwd=src); subprocess.check_call(["git", "commit", "-q", "-m", "x"], cwd=src, env=env)
    open(core.ADDON_SRC, "w").write(src); open(core.ADDON_COMMIT, "w").write("a"*40)
    open(netswitch_probes.ADDON_VERSION, "w").write("2026-09-30 12:00 (aaaaaaa)")
    def fake(url):
        if "/commits/" in url: return json.dumps({"sha": "b"*40, "commit": {"committer": {"date": "2026-10-02T10:00:00Z"}}})
        if "/compare/" in url: return json.dumps({"status": "ahead", "ahead_by": 4})
        return ""
    up.fetch = fake
    up._spawn = lambda cmd: open(core.UPDATE_STATUS, "w").write("running")
    if os.environ.get("FAKELOG"):      # a finished update with a messy log: long lines, colour codes, progress
        open(core.UPDATE_STATUS, "w").write("failed")
        open(core.UPDATE_LOG, "w").write("Updating /home/pi/checkout from origin/main\nFrom https://github.com/blaskkaffe/DreamPiAutoToggle\n"
            " * branch            main       -> FETCH_HEAD\nReceiving objects:  10%\rReceiving objects: 100% (42/42), done.\n"
            "Updating 3baa024..21d1ad8\nFast-forward\n page/widgets.js | 84 ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++\n"
            " 4 files changed, 64 insertions(+), 37 deletions(-)\n\x1b[31mERROR\x1b[0m: could not write /etc/systemd/system/dreampi-netswitch.service (Read-only file system)\n"
            "A_very_long_unbroken_path_/opt/dreampi-netswitch/page/widgets_and_more_and_more_and_more_and_more.js\nfailed\n")
if os.environ.get("OFF"):         # modules switched off, as from the module picker (the always-on ones can't be)
    for name in (core.module_names() if os.environ["OFF"] == "all" else os.environ["OFF"].split(",")):
        core.save_module_enabled(name, False)
    web.refresh_page(force=True)
if os.environ.get("PIN"):
    import base_security
    base_security.set_pin(os.environ["PIN"])
    __import__("netswitch_rebootupdate")._spawn_reboot = lambda: None
print("state dir", tmp, flush=True)
srv = web.Server(('127.0.0.1', int(os.environ.get('PORT', '8734'))), web.Handler)
srv.serve_forever()
