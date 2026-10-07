"""The web service runs as root: host/origin checks, the optional PIN, the update's origin pinning."""
import http.client
import json
import os
import subprocess
import threading
import time
import unittest

from support import sandbox, cleanup, core, web
import netswitch_rebootupdate as ru
import base_security as sec
import netswitch_update as up


class HostAndOriginTests(unittest.TestCase):
    def test_hosts(self):
        for ok in (None, "192.168.1.5", "192.168.1.5:80", "[::1]:8080", "localhost", "dreampi", "dreampi.local:80",
                   "router.lan", "dreampi.home.arpa", "10.0.0.2:443"):
            self.assertTrue(sec.host_allowed(ok), ok)
        for bad in ("evil.example.com", "evil.com:80", "a.b.c.d.example.org", "dreampi.local.evil.com", ":80"):
            self.assertFalse(sec.host_allowed(bad), bad)

    def test_hosts_from_the_allowed_file(self):
        tmp = sandbox()
        try:
            with open(core.ALLOWED_HOSTS, "w") as f:
                f.write("# mine\npi.example.org\n")
            self.assertTrue(sec.host_allowed("pi.example.org:443"))
            self.assertFalse(sec.host_allowed("other.example.org"))
        finally:
            cleanup(tmp)

    def test_post_rules(self):
        h = {"Host": "dreampi.local"}
        self.assertTrue(sec.post_allowed(dict(h, **{"X-Requested-With": "x"}), True))
        self.assertTrue(sec.post_allowed(dict(h, **{"X-Requested-With": "x", "Origin": "http://dreampi.local"}), True))
        self.assertFalse(sec.post_allowed(dict(h, **{"X-Requested-With": "x", "Origin": "http://evil.com"}), True))
        self.assertFalse(sec.post_allowed(dict(h, **{"Origin": "null"}), False))
        self.assertTrue(sec.post_allowed(dict(h, **{"Origin": "http://dreampi.local"}), False))     # form post, JavaScript off
        self.assertFalse(sec.post_allowed(dict(h, **{"Origin": "http://dreampi.local"}), True))     # but not for strict actions
        self.assertFalse(sec.post_allowed(h, False))                                               # neither header nor origin
        self.assertTrue(sec.post_allowed(dict(h, **{"Referer": "http://dreampi.local/x"}), False))
        self.assertFalse(sec.post_allowed(dict(h, **{"Referer": "http://evil.com/x"}), False))


class PinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        sec.reset_for_tests()

    def tearDown(self):
        cleanup(self.tmp)

    def test_no_pin_means_everything_passes(self):
        self.assertFalse(sec.pin_required())
        self.assertTrue(sec.check_pin("")[0])

    def test_set_check_and_clear(self):
        sec.set_pin("4821")
        self.assertTrue(sec.pin_required())
        text = open(core.ADMIN_PIN).read()
        self.assertNotIn("4821", text)                     # only a salted hash is stored
        self.assertEqual(oct(os.stat(core.ADMIN_PIN).st_mode & 0o777), "0o600")
        self.assertTrue(sec.check_pin("4821")[0])
        self.assertFalse(sec.check_pin("4822")[0])
        self.assertFalse(sec.check_pin("")[0])
        sec.clear_pin()
        self.assertFalse(sec.pin_required())

    def test_bad_pins_are_refused(self):
        for bad in ("", "123", "x" * 65):
            with self.assertRaises(ValueError):
                sec.set_pin(bad)

    def test_lockout_after_five_wrong_tries(self):
        sec.set_pin("4821")
        for _ in range(sec.FAIL_LIMIT):
            self.assertFalse(sec.check_pin("0000")[0])
        ok, message = sec.check_pin("4821")                # even the right PIN waits
        self.assertFalse(ok)
        self.assertIn("Too many", message)
        sec.reset_for_tests()
        self.assertTrue(sec.check_pin("4821")[0])

    def test_a_damaged_file_does_not_open_the_actions(self):
        with open(core.ADMIN_PIN, "w") as f:
            f.write("garbage")
        self.assertTrue(sec.pin_required())
        self.assertFalse(sec.check_pin("garbage")[0])


class HttpSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = sandbox(up)
        core.save_module_enabled("wifi", True)      # off by default: /wificonnect only exists (and is protected) while it is on
        cls.srv = web.Server(("127.0.0.1", 0), web.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.spawned = []
        cls._spawn = ru._spawn_reboot
        ru._spawn_reboot = lambda: cls.spawned.append(1)

    @classmethod
    def tearDownClass(cls):
        ru._spawn_reboot = cls._spawn
        cls.srv.shutdown()
        cls.srv.server_close()
        cleanup(cls.tmp)

    def setUp(self):
        sec.clear_pin()
        sec.reset_for_tests()
        del self.spawned[:]

    def req(self, method, path, headers=None, body=b""):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(method, path, body=body or None, headers=headers or {})
        r = c.getresponse()
        out = (r.status, r.read(), r)
        c.close()
        return out

    def test_foreign_host_name_is_refused(self):                      # DNS rebinding
        for method in ("GET", "POST"):
            status, _body, _r = self.req(method, "/api" if method == "GET" else "/dcnet",
                                         {"Host": "evil.example.com", "X-Requested-With": "x"})
            self.assertEqual(status, 421)

    def test_cross_site_posts_are_refused(self):
        evil = {"Host": "127.0.0.1:%d" % self.port, "Origin": "http://evil.example.com"}
        for path in ("/dcnet", "/numbers", "/wificonnect", "/ledconfig", "/ledrows", "/reboot", "/update/start"):
            for extra in ({}, {"X-Requested-With": "x"}, {"Content-Type": "text/plain"}):
                status, _b, _r = self.req("POST", path, dict(evil, **extra), b"{}")
                self.assertEqual(status, 403, (path, extra))
        self.assertEqual(self.spawned, [])
        self.assertFalse(os.path.exists(core.FLAG))

    def test_post_without_header_or_origin_is_refused(self):
        self.assertEqual(self.req("POST", "/dcnet")[0], 403)
        self.assertFalse(os.path.exists(core.FLAG))

    def test_openmenu_selects_the_network_like_the_page(self):
        """openMenu's two buttons send POST /dcnow and /dcnet over the PPP link: X-Requested-With: openMenu, no Origin, often no Host."""
        h = {"X-Requested-With": "openMenu"}
        open(core.DEBUG_DTMF, "w").close()                       # the debug log is on
        core.save_module_enabled("debuglog", True)
        self.assertEqual(self.req("POST", "/dcnet", h)[0], 204)
        self.assertTrue(os.path.exists(core.FLAG))
        self.assertEqual(self.req("POST", "/dcnow", h)[0], 204)
        self.assertFalse(os.path.exists(core.FLAG))
        log = open(core.DTMF_LOG).read()
        self.assertIn("openMenu: DCNET selected", log)
        self.assertIn("openMenu: DCNow! selected", log)

    def test_same_site_form_post_still_works_without_javascript(self):
        status, _b, r = self.req("POST", "/dcnet", {"Origin": "http://127.0.0.1:%d" % self.port,
                                                    "Host": "127.0.0.1:%d" % self.port})
        self.assertEqual(status, 303)
        self.assertTrue(os.path.exists(core.FLAG))
        os.remove(core.FLAG)

    def test_reboot_form_post_is_never_enough(self):
        status, _b, _r = self.req("POST", "/reboot", {"Origin": "http://127.0.0.1:%d" % self.port,
                                                      "Host": "127.0.0.1:%d" % self.port})
        self.assertEqual(status, 403)
        self.assertEqual(self.spawned, [])

    def test_pin_guards_reboot_and_update(self):
        sec.set_pin("4821")
        h = {"X-Requested-With": "x"}
        for path in ("/reboot", "/update/start", "/wificonnect"):
            sec.reset_for_tests()
            self.assertEqual(self.req("POST", path, h, b"{}")[0], 401, path)
            self.assertEqual(self.req("POST", path, dict(h, **{"X-Netswitch-Pin": "1111"}), b"{}")[0], 401, path)
        self.assertEqual(self.spawned, [])
        sec.reset_for_tests()
        status, body, _r = self.req("POST", "/reboot", dict(h, **{"X-Netswitch-Pin": "4821"}))
        self.assertEqual((status, json.loads(body.decode())["started"]), (200, True))
        self.assertEqual(self.spawned, [1])
        # the check for updates and everyday switches need no PIN
        self.assertEqual(self.req("POST", "/update/check", h)[0], 200)
        self.assertEqual(self.req("POST", "/dcnet", h)[0], 204)
        os.path.exists(core.FLAG) and os.remove(core.FLAG)

    def test_api_says_whether_a_pin_is_needed(self):
        self.assertFalse(json.loads(self.req("GET", "/api")[1].decode())["pin"])
        sec.set_pin("4821")
        self.assertTrue(json.loads(self.req("GET", "/api")[1].decode())["pin"])

    def test_lockout_answers_429(self):
        sec.set_pin("4821")
        h = {"X-Requested-With": "x", "X-Netswitch-Pin": "0000"}
        codes = [self.req("POST", "/reboot", h)[0] for _ in range(sec.FAIL_LIMIT + 1)]
        self.assertEqual(codes[:sec.FAIL_LIMIT], [401] * sec.FAIL_LIMIT)
        self.assertEqual(codes[-1], 429)

    def test_locked_settings_need_the_pin_but_the_dashboard_does_not(self):
        h = {"X-Requested-With": "x"}
        self.assertEqual(self.req("POST", "/settings-pin", h, b'{"value": true}')[0], 409)         # no PIN yet: nothing to lock with
        sec.set_pin("4821")
        self.assertEqual(self.req("POST", "/settings-pin", h, b'{"value": true}')[0], 200)
        api = json.loads(self.req("GET", "/api")[1].decode())
        self.assertEqual(api["settings_pin"], {"on": True, "pin": True})
        for path in ("/colour", "/screen", "/screen/stretch", "/modules", "/buttonconfig", "/numbers", "/clock/beat", "/highlight", "/settings-pin"):
            sec.reset_for_tests()
            self.assertEqual(self.req("POST", path, h, b"{}")[0], 401, path)
        self.assertFalse(os.path.exists(core.SCREEN))
        for path, want in (("/dcnet", 204), ("/dcnow", 204), ("/hangup", 204), ("/players/star", None), ("/events/dismiss", None)):
            got = self.req("POST", path, h, b"{}")[0]
            self.assertNotEqual(got, 401, path)
            if want:
                self.assertEqual(got, want, path)
        self.assertEqual(self.req("POST", "/openmenu/games", {"X-Requested-With": "openMenu"}, b"#openmenu-games 1 abc 0\n")[0], 200)
        ok = dict(h, **{"X-Netswitch-Pin": "4821"})
        sec.reset_for_tests()
        self.assertEqual(self.req("POST", "/screen/stretch", ok, b'{"value": true}')[0], 200)
        self.assertTrue(core.screen_settings()["stretch"])
        self.assertEqual(self.req("POST", "/pin/check", ok, b"{}")[0], 200)
        self.assertEqual(self.req("POST", "/pin/check", dict(h, **{"X-Netswitch-Pin": "0000"}), b"{}")[0], 401)
        self.assertEqual(self.req("POST", "/settings-pin", ok, b'{"value": false}')[0], 200)        # unlocked again: settings are open
        self.assertEqual(self.req("POST", "/screen/stretch", h, b'{"value": false}')[0], 200)
        os.path.exists(core.FLAG) and os.remove(core.FLAG)

    def test_the_pin_can_be_set_changed_and_removed_from_the_page(self):
        h = {"X-Requested-With": "x"}
        self.assertEqual(self.req("POST", "/pin", h, b'{"pin": "ab"}')[0], 400)                    # too short
        self.assertEqual(self.req("POST", "/pin", h, b'{"pin": "4821"}')[0], 200)
        self.assertTrue(sec.pin_required())
        self.assertEqual(self.req("POST", "/pin", h, b'{"pin": "9999"}')[0], 401)                  # changing it needs the old one
        old = dict(h, **{"X-Netswitch-Pin": "4821"})
        self.assertEqual(self.req("POST", "/pin", old, b'{"pin": "9999"}')[0], 200)
        sec.reset_for_tests()
        self.assertTrue(sec.check_pin("9999")[0])
        core.save_settings_pin(True)
        self.assertEqual(self.req("POST", "/pin", dict(h, **{"X-Netswitch-Pin": "9999"}), b'{"pin": ""}')[0], 200)
        self.assertFalse(sec.pin_required())
        self.assertFalse(core.settings_pin_on())                                                    # no PIN: the lock goes with it
        self.assertFalse(sec.settings_locked())

    def test_page_cannot_be_framed(self):
        _s, _b, r = self.req("GET", "/")
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        self.assertIn("frame-ancestors 'none'", r.getheader("Content-Security-Policy"))
        self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")

    def test_negative_content_length_does_not_hang(self):
        status, _b, _r = self.req("POST", "/numbers", {"X-Requested-With": "x", "Content-Length": "-5"})
        self.assertEqual(status, 400)

    def test_wifi_connect_cuts_long_values(self):
        core.save_module_enabled("wifi", True)
        body = json.dumps({"ssid": "s" * 100, "password": "p" * 200}).encode()
        self.assertEqual(self.req("POST", "/wificonnect", {"X-Requested-With": "x"}, body)[0], 204)
        got = json.load(open(core.WIFI_CONNECT))
        self.assertEqual((len(got["ssid"]), len(got["password"])), (32, 63))
        core.save_module_enabled("wifi", False)


class WifiApTests(unittest.TestCase):
    def test_the_open_setup_access_point_closes_itself(self):
        import netswitch_wifi_setup as wifi
        self.assertEqual(wifi.AP_TIMEOUT, 600)
        self.assertFalse(wifi.ap_expired(time.time() + 5))
        self.assertTrue(wifi.ap_expired(time.time() - 1))


class UpdateOriginTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox(up)
        self.src = os.path.join(self.tmp, "checkout")
        os.mkdir(self.src)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=self.src)
        subprocess.check_call(["git", "remote", "add", "origin", "https://github.com/blaskkaffe/DreamPiAutoToggle.git"], cwd=self.src)
        open(os.path.join(self.src, "install.sh"), "w").write("#!/bin/sh\n")
        subprocess.check_call(["git", "add", "."], cwd=self.src)
        subprocess.check_call(["git", "commit", "-q", "-m", "x"], cwd=self.src, env=env)
        open(core.ADDON_SRC, "w").write(self.src)
        self._spawn, self.spawned = up._spawn, []
        up._spawn = self.spawned.append

    def tearDown(self):
        up._spawn = self._spawn
        cleanup(self.tmp)

    def set_origin(self, url):
        subprocess.check_call(["git", "remote", "set-url", "origin", url], cwd=self.src)

    def test_github_origin_is_fine_and_is_the_fetch_address(self):
        self.assertIsNone(up.origin_problem())
        self.assertTrue(up.start_update()[0])
        script = self.spawned[0][-1]
        self.assertIn("U='https://github.com/blaskkaffe/DreamPiAutoToggle.git'", script)
        self.assertIn("GIT_ALLOW_PROTOCOL=https:ssh", script)
        self.assertIn("fetch \"$U\"", script)

    def test_other_origins_are_refused(self):
        for url in ("https://evil.example.com/x/y.git", "/tmp/local", "ext::sh -c id", "https://github.com.evil.com/x/y",
                    "file:///etc", "https://github.com/x/y z"):
            self.set_origin(url)
            started, message = up.start_update()
            self.assertFalse(started, url)
            self.assertIn("Update refused", message)
        self.assertEqual(self.spawned, [])

    def test_origin_must_match_what_was_installed(self):
        open(core.UPDATE_ORIGIN, "w").write("https://github.com/blaskkaffe/DreamPiAutoToggle.git\n")
        self.assertIsNone(up.origin_problem())
        self.set_origin("https://github.com/someone-else/Fork.git")
        self.assertIn("changed", up.origin_problem())
        self.assertFalse(up.start_update()[0])

    def test_ssh_github_origin_is_fine(self):
        self.set_origin("git@github.com:blaskkaffe/DreamPiAutoToggle.git")
        self.assertIsNone(up.origin_problem())

    def test_branch_cannot_look_like_an_option(self):
        for branch in ("-x", "--upload-pack=sh", "a/../b", "a/"):
            with self.assertRaises(ValueError):
                up.update_script("/home/pi/x", branch, 80, 443)

    def test_script_with_url_is_valid_shell(self):
        script = up.update_script(self.src, "main", 80, 443, "https://github.com/a/b.git")
        self.assertEqual(subprocess.run(["sh", "-n", "-c", script]).returncode, 0)
        with self.assertRaises(ValueError):
            up.update_script(self.src, "main", 80, 443, "https://evil.com/a/b")

    def test_status_file_is_not_written_through_a_link(self):
        target = os.path.join(self.tmp, "victim")
        os.symlink(target, core.UPDATE_STATUS)
        up._write_status("running")
        self.assertFalse(os.path.exists(target))
        self.assertEqual(open(core.UPDATE_STATUS).read(), "running")


if __name__ == "__main__":
    unittest.main()
