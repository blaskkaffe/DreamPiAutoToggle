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
import netswitch_update as up

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
        return "#dreampi.py_version=202701010000\n"
    return fetch


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox(up)
        self._fetch = up.fetch
        with open(core.ADDON_COMMIT, "w") as f:
            f.write(LOCAL)
        with open(probes.ADDON_VERSION, "w") as f:
            f.write("2026-09-30 12:00 (aaaaaaa)")
        up._info.update({"time": 0, "checking": False, "addon": None, "dreampi": None, "error": None})

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

    def test_dreampi_versions(self):
        dp = os.path.join(self.tmp, "dreampi")
        os.mkdir(dp)
        probes.DREAMPI_DIR = dp
        with open(os.path.join(dp, "dreampi.py"), "w") as f:
            f.write("#!/usr/bin/env python\n#dreampi.py_version=202601010000\n")
        with open(os.path.join(dp, "netlink.py"), "w") as f:
            f.write("#netlink_version=202801010000\n")          # newer than the fake remote
        up.fetch = lambda url: "#%s_version=202701010000\n" % os.path.basename(url)[:-3] if "netlink" not in url else "#netlink_version=202701010000\n"
        r = up.check_dreampi()
        by = dict((f["name"], f) for f in r["files"])
        self.assertTrue(by["dreampi.py"]["newer"])
        self.assertEqual(by["dreampi.py"]["current"], "2026-01-01 00:00")
        self.assertFalse(by["netlink.py"]["newer"])
        self.assertEqual(by["dcnow.py"]["current"], "not found")
        self.assertFalse(by["dcnow.py"]["newer"])
        self.assertTrue(r["newer"])


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
        self.assertIn("Updating", open(core.UPDATE_LOG).read())


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
            req = Request(base + "/update/start", data=b"", method="POST", headers={"X-Requested-With": "netswitch"})
            out = json.loads(urlopen(req, timeout=10).read().decode())
            self.assertIn("can't update itself", out["message"])    # no checkout recorded in the sandbox
        finally:
            up.fetch = orig
            srv.shutdown()
            srv.server_close()
            cleanup(tmp)


if __name__ == "__main__":
    unittest.main()
