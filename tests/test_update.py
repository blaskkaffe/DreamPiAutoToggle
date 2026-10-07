"""Update check and the page's Update now (GitHub is faked; no network)."""
import json
import os
import subprocess
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen, Request

from support import core, probes, web, sandbox, cleanup
import rebootupdate_update as up

LOCAL = "a" * 40
REMOTE = "b" * 40


def fake_github(head=REMOTE, status="ahead", compare_error=False, down=False):
    def fetch(url):
        if down:
            raise IOError("no internet")
        if "/commits/" in url:
            return json.dumps({"sha": head, "commit": {"committer": {"date": "2026-10-02T10:00:00Z"}}})
        if "/compare/" in url:
            if compare_error:
                raise IOError("404")
            return json.dumps({"status": status, "ahead_by": 3})
        return ""
    return fetch


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox(up)
        self._fetch = up.fetch
        with open(core.ADDON_COMMIT, "w") as f:
            f.write(LOCAL)
        with open(probes.ADDON_VERSION, "w") as f:
            f.write("2026-09-30 12:00 (aaaaaaa)")
        up._info.update({"time": 0, "started": 0, "checking": False, "addon": None, "error": None})

    def tearDown(self):
        up.fetch = self._fetch
        cleanup(self.tmp)

    def test_up_to_date(self):
        up.fetch = fake_github(head=LOCAL)
        a = up.check_addon()
        self.assertIs(a["available"], False)
        self.assertEqual(a["branch"], "main")
        self.assertEqual(a["repo"], up.DEFAULT_REPO)

    def test_newer_version_available(self):
        up.fetch = fake_github(status="ahead")
        a = up.check_addon()
        self.assertTrue(a["available"])
        self.assertEqual((a["behind"], a["latest"]), (3, REMOTE[:7]))
        self.assertEqual(a["latest_date"], "2026-10-02T10:00:00Z")

    def test_local_ahead_of_github_is_not_an_update(self):
        up.fetch = fake_github(status="behind")
        a = up.check_addon()
        self.assertIs(a["available"], False)
        self.assertIn("ahead", a["note"])

    def test_diverged_counts_as_available(self):
        up.fetch = fake_github(status="diverged")
        self.assertTrue(up.check_addon()["available"])

    def test_commit_unknown_to_github(self):
        up.fetch = fake_github(compare_error=True)
        a = up.check_addon()
        self.assertIsNone(a["available"])
        self.assertIn("local changes", a["note"])

    def test_no_recorded_commit(self):
        os.remove(core.ADDON_COMMIT)
        up.fetch = fake_github()
        self.assertIsNone(up.check_addon()["available"])

    def test_offline_gives_an_error_not_an_exception(self):
        up.fetch = fake_github(down=True)
        up.check()
        self.assertIn("Couldn't reach GitHub", up._info["error"])
        self.assertTrue(up._info["time"])
        self.assertFalse(up._info["checking"])

    def test_pressing_check_says_checking_at_once_and_never_runs_two(self):
        gate, started = threading.Event(), []
        def slow(url):
            started.append(url)
            gate.wait(5)
            raise IOError("down")
        up.fetch = slow
        up.check_in_background()
        self.assertTrue(up.status()["checking"])          # no gap before the thread runs: the page's next question already sees it
        up.check_in_background()                           # a second press while one runs starts nothing
        gate.set()
        for _ in range(100):
            if not up._info["checking"]:
                break
            time.sleep(0.05)
        self.assertFalse(up._info["checking"])
        self.assertTrue(up._info["time"])
        self.assertEqual(len([u for u in started if "api.github.com" in u]), 1)

    def test_a_new_check_replaces_the_result_of_the_last_update(self):
        with open(core.UPDATE_STATUS, "w") as f:
            f.write("ok\n")
        os.utime(core.UPDATE_STATUS, (time.time() - 5, time.time() - 5))
        up.fetch = fake_github(down=True)
        self.assertEqual(up.update_state(), "ok")                 # right after the update: announced
        up.check()
        self.assertEqual(up.update_state(), "idle")               # checking again takes over
        self.assertIn("Couldn't reach GitHub", up.status()["error"])
        with open(core.UPDATE_STATUS, "w") as f:                  # a later update announces itself again
            f.write("failed\n")
        self.assertEqual(up.update_state(), "failed")

    def test_nothing_checks_for_updates_by_itself(self):
        calls = []
        saved = up.check, up.check_in_background
        up.check = up.check_in_background = lambda *a, **k: calls.append(1)      # whoever would start a check is counted, nothing runs
        try:
            up.status()                                       # the page asking for the status must not start a check
        finally:
            up.check, up.check_in_background = saved
        self.assertEqual(calls, [])


class UpdateRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox(up)
        self.src = os.path.join(self.tmp, "checkout")
        os.mkdir(self.src)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        for cmd in (["git", "init", "-q", "-b", "feature/x"], ["git", "remote", "add", "origin", "https://github.com/someone/Fork.git"]):
            subprocess.check_call(cmd, cwd=self.src)
        with open(os.path.join(self.src, "install.sh"), "w") as f:
            f.write("#!/bin/sh\n")
        subprocess.check_call(["git", "add", "."], cwd=self.src)
        subprocess.check_call(["git", "commit", "-q", "-m", "x"], cwd=self.src, env=env)
        with open(core.ADDON_SRC, "w") as f:
            f.write(self.src)
        self._spawn = up._spawn
        self.spawned = []
        up._spawn = self.spawned.append

    def tearDown(self):
        up._spawn = self._spawn
        cleanup(self.tmp)

    def test_source_comes_from_the_checkout(self):
        self.assertEqual(up.source(), ("someone/Fork", "feature/x", self.src))
        self.assertTrue(up.can_update())

    def test_no_checkout_means_no_self_update(self):
        os.remove(core.ADDON_SRC)
        self.assertFalse(up.can_update())
        started, message = up.start_update()
        self.assertFalse(started)
        self.assertEqual(self.spawned, [])

    def test_start_runs_the_script_detached_with_the_remembered_ports(self):
        with open(core.INSTALL_PORTS, "w") as f:
            f.write("8080 0")
        started, message = up.start_update()
        self.assertTrue(started)
        cmd = self.spawned[0]
        script = cmd[-1]
        self.assertIn("8080 --https-port=0", script)
        self.assertIn("'feature/x'", script)
        self.assertIn("merge --ff-only", script)
        self.assertEqual(up.update_state(), "running")
        self.assertFalse(up.start_update()[0])                  # no second one while running

    def test_script_rejects_unsafe_values(self):
        for branch in ("main; rm -rf /", "a b", "$(x)", ""):
            with self.assertRaises(ValueError):
                up.update_script("/home/pi/x", branch, 80, 443)
        with self.assertRaises(ValueError):
            up.update_script("/home/pi/it's", "main", 80, 443)
        with self.assertRaises(ValueError):
            up.update_script("relative/path", "main", 80, 443)

    def test_script_is_valid_shell(self):
        script = up.update_script(self.src, "main", 80, 443)
        p = subprocess.run(["sh", "-n", "-c", script], stderr=subprocess.PIPE)
        self.assertEqual(p.returncode, 0, p.stderr.decode())

    def test_finished_status_expires(self):
        with open(core.UPDATE_STATUS, "w") as f:
            f.write("ok")
        self.assertEqual(up.update_state(), "ok")
        old = time.time() - 3600
        os.utime(core.UPDATE_STATUS, (old, old))
        self.assertEqual(up.update_state(), "idle")
        with open(core.UPDATE_STATUS, "w") as f:
            f.write("running")
        os.utime(core.UPDATE_STATUS, (old, old))
        self.assertEqual(up.update_state(), "running")           # a running update never expires


class LogTests(unittest.TestCase):
    def test_lines_are_cleaned_for_the_page(self):
        self.assertEqual(up._clean_line("\x1b[32mok\x1b[0m done\n"), "ok done")
        self.assertEqual(up._clean_line("Receiving objects:  10%\rReceiving objects: 100%\r\n"), "Receiving objects: 100%")
        self.assertEqual(up._clean_line("a\x00b\x07c"), "a b c")
        self.assertEqual(len(up._clean_line("x" * 1000)), 300)
        self.assertEqual(up._clean_line("\r\r"), "")

    def test_tail_skips_blank_lines_and_keeps_the_end(self):
        tmp = sandbox(up)
        try:
            with open(core.UPDATE_LOG, "w") as f:
                f.write("\n".join(["line %d" % i if i % 3 else "" for i in range(60)]) + "\n")
            tail = up._log_tail()
            self.assertEqual(len(tail), 14)
            self.assertEqual(tail[-1], "line 59")
            self.assertNotIn("", tail)
            self.assertEqual(up._log_tail.__defaults__, (14,))
        finally:
            cleanup(tmp)


class RealScriptTests(unittest.TestCase):
    """Run the generated update script against a local 'origin' with a stub installer."""
    def setUp(self):
        self.tmp = sandbox(up)
        self.env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        self.origin = os.path.join(self.tmp, "origin")
        self.src = os.path.join(self.tmp, "checkout")
        self.git(["init", "-q", "-b", "main", self.origin], cwd=self.tmp)
        with open(os.path.join(self.origin, "install.sh"), "w") as f:
            f.write('#!/bin/sh\necho "installer ran: $@" > "%s/installer.out"\n' % self.tmp)
        self.commit(self.origin, "one")
        self.git(["clone", "-q", self.origin, self.src], cwd=self.tmp)

    def tearDown(self):
        cleanup(self.tmp)

    def git(self, args, cwd):
        subprocess.check_call(["git"] + args, cwd=cwd, env=self.env)

    def commit(self, repo, msg):
        with open(os.path.join(repo, "file"), "a") as f:
            f.write(msg + "\n")
        self.git(["add", "."], cwd=repo)
        self.git(["commit", "-q", "-m", msg], cwd=repo)

    def run_script(self):
        script = up.update_script(self.src, "main", 8080, 0)
        return subprocess.run(["sh", "-c", script], stderr=subprocess.PIPE, stdout=subprocess.PIPE)

    def test_pulls_then_installs_with_the_ports(self):
        self.commit(self.origin, "two")
        self.run_script()
        self.assertEqual(core.read_file(core.UPDATE_STATUS).strip(), "ok")
        with open(os.path.join(self.src, "file")) as f:
            self.assertIn("two", f.read())
        with open(os.path.join(self.tmp, "installer.out")) as f:
            self.assertEqual(f.read().strip(), "installer ran: 8080 --https-port=0")

    def test_local_changes_that_cannot_fast_forward_fail_without_installing(self):
        self.commit(self.src, "local only")
        self.commit(self.origin, "remote only")
        self.run_script()
        self.assertEqual(core.read_file(core.UPDATE_STATUS).strip(), "failed")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "installer.out")))
        with open(core.UPDATE_LOG) as f:
            self.assertIn("Updating", f.read())


class HttpUpdateTests(unittest.TestCase):
    def test_endpoints(self):
        tmp = sandbox(up)
        srv = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        orig = up.fetch
        up.fetch = fake_github(down=True)
        try:
            r = json.loads(urlopen(base + "/update", timeout=10).read().decode())
            for key in ("state", "can_update", "checking", "branch", "log"):
                self.assertIn(key, r)
            for path in ("/update/check", "/update/start"):          # a bare cross-site form post is refused
                with self.assertRaises(HTTPError) as cm:
                    urlopen(Request(base + path, data=b"", method="POST"), timeout=10)
                self.assertEqual(cm.exception.code, 403)
            req = Request(base + "/update/start", data=b"", method="POST", headers={"X-Requested-With": "checkin"})
            out = json.loads(urlopen(req, timeout=10).read().decode())
            self.assertIn("can't update itself", out["message"])    # no checkout recorded in the sandbox
        finally:
            up.fetch = orig
            srv.shutdown()
            srv.server_close()
            cleanup(tmp)


if __name__ == "__main__":
    unittest.main()


class UsbUpdateTests(unittest.TestCase):
    """An update from the folder called "update" on a USB stick."""
    def setUp(self):
        self.tmp = sandbox(up)
        self.media = os.path.join(self.tmp, "media")
        os.makedirs(self.media)
        self._roots, self._spawn = up.USB_ROOTS, up._spawn
        up.USB_ROOTS = [os.path.join(self.media, "*")]
        self.spawned = []
        up._spawn = self.spawned.append

    def tearDown(self):
        up.USB_ROOTS, up._spawn = self._roots, self._spawn
        cleanup(self.tmp)

    def stick(self, name, valid=True, age=0):
        folder = os.path.join(self.media, name, "update")
        os.makedirs(os.path.join(folder, "modules"))
        if valid:
            os.makedirs(os.path.join(folder, "base"))
            open(os.path.join(folder, "base", "base_web.py"), "w").close()
            with open(os.path.join(folder, "install.sh"), "w") as f:
                f.write('#!/bin/sh\necho "$NS_KEEP_SRC|$NS_VERSION|$@" > "%s/usb-installer.out"\n' % self.tmp)
            os.utime(os.path.join(folder, "install.sh"), (time.time() - age, time.time() - age))
        return folder

    def test_only_a_folder_that_looks_like_the_add_on_counts(self):
        self.assertEqual(up.usb_candidates(), [])
        self.stick("EMPTY", valid=False)
        self.assertEqual(up.usb_candidates(), [])                                          # no install.sh and no base/
        old, new = self.stick("OLD", age=86400), self.stick("NEW")
        os.makedirs(os.path.join(self.media, "LINK"))
        os.symlink(new, os.path.join(self.media, "LINK", "update"))
        got = up.usb_candidates()
        self.assertEqual([c["path"] for c in got], [new, old])                             # newest first, the link is not followed
        self.assertEqual(got[0]["drive"], "NEW")

    def test_the_script_is_built_from_safe_values_only(self):
        folder = self.stick("STICK")
        script = up.usb_script(folder, 8080, 0, "USB update 2026-10-07 10:00")
        for part in ("cp -r", "NS_KEEP_SRC=1", "NS_VERSION='USB update 2026-10-07 10:00'", "8080 --https-port=0", "usb_src"):
            self.assertIn(part, script)
        self.assertEqual(subprocess.run(["sh", "-n", "-c", script], stderr=subprocess.PIPE).returncode, 0)
        for bad in ("/media/x/it's/update", "relative/update", "/media/x/../etc/update", "/media/$(x)/update"):
            with self.assertRaises(ValueError):
                up.usb_script(bad, 80, 443, "v")
        with self.assertRaises(ValueError):
            up.usb_script(folder, 80, 443, "v; rm -rf /")

    def test_start_needs_a_stick_and_runs_one_update_at_a_time(self):
        started, message = up.start_usb_update()
        self.assertFalse(started)
        self.assertIn("No USB stick", message)
        self.assertEqual(self.spawned, [])
        self.stick("STICK")
        started, message = up.start_usb_update()
        self.assertTrue(started, message)
        self.assertEqual(len(self.spawned), 1)
        self.assertEqual(up.update_state(), "running")
        self.assertFalse(up.start_usb_update()[0])

    def test_the_script_copies_the_folder_and_runs_its_installer(self):
        folder = self.stick("STICK")
        with open(core.INSTALL_PORTS, "w") as f:
            f.write("8080 0")
        started, _message = up.start_usb_update()
        self.assertTrue(started)
        done = subprocess.run(["sh", "-c", self.spawned[0][-1]], stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        self.assertEqual(done.returncode, 0, done.stderr.decode())
        self.assertEqual(core.read_file(core.UPDATE_STATUS).strip(), "ok")
        self.assertTrue(os.path.exists(os.path.join(core.BASE_DIR, "usb_src", "base", "base_web.py")))     # a copy in the data folder: the stick can be pulled out
        ran = open(os.path.join(self.tmp, "usb-installer.out")).read().strip()
        self.assertRegex(ran, r"^1\|USB update \d{4}-\d\d-\d\d \d\d:\d\d\|8080 --https-port=0$")
        self.assertTrue(os.path.exists(folder))                                                          # the stick's folder is left alone

    def test_the_page_shows_the_stick_only_while_nothing_runs(self):
        import rebootupdate_web as rw
        self.assertFalse(rw.view({"state": "idle", "usb": [], "time": 1})["show_usb"])
        got = rw.view({"state": "idle", "usb": [{"path": "/media/pi/STICK/update", "drive": "STICK", "time": 1790000000}], "time": 1})
        self.assertTrue(got["show_usb"])
        self.assertIn("STICK", got["usb_text"])
        self.assertFalse(rw.view({"state": "running", "usb": [{"path": "/x/update", "drive": "x", "time": 1}], "time": 1})["show_usb"])
        self.assertIn("/update/usb", rw.PROTECTED)

    def test_the_installer_keeps_the_recorded_checkout_for_a_usb_update(self):
        text = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "install.sh")).read()
        for part in ('[ -n "$NS_VERSION" ]', '[ -z "$NS_KEEP_SRC" ]', 'rm -f "$DEST/version_commit"'):
            self.assertIn(part, text)
