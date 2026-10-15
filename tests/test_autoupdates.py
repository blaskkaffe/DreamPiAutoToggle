"""Settings > System: back up and remove DreamPi's /boot/noautoupdates.txt (so DreamPi updates its scripts and writes netlink_config.ini again) and
restore it. The file is in /boot, which the web service may not write to: the removal and the restore run through the updater's _spawn()."""
import json
import os
import subprocess
import unittest

from support import core, sandbox, cleanup
import netswitch_rebootupdate as reb
import netswitch_update as up


class Auto(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        self.flag = os.path.join(self.tmp, "boot-noautoupdates.txt")
        self.was = (reb.NOAUTO, up._spawn)
        reb.NOAUTO = self.flag
        self.spawned = []
        up._spawn = lambda cmd: (self.spawned.append(cmd), subprocess.call(cmd))      # what systemd-run would do, at once

    def tearDown(self):
        reb.NOAUTO, up._spawn = self.was
        cleanup(self.tmp)

    def test_allow_backs_up_then_removes_and_restore_puts_it_back(self):
        with open(self.flag, "w") as f:
            f.write("keep me\n")
        self.assertEqual(reb.auto_state(), {"off": True, "backup": False})
        done, message = reb.auto_allow()
        self.assertTrue(done, message)
        self.assertFalse(os.path.exists(self.flag))
        self.assertEqual(open(reb.NOAUTO_BACKUP).read(), "keep me\n")
        self.assertEqual(self.spawned[0][:2], ["rm", "-f"])                                # the removal is not done by the sandboxed service itself
        self.assertEqual(reb.auto_state(), {"off": False, "backup": True})
        self.assertIn("restart DreamPi", message)
        done, message = reb.auto_restore()
        self.assertTrue(done, message)
        self.assertEqual(open(self.flag).read(), "keep me\n")
        self.assertEqual(reb.auto_state(), {"off": True, "backup": False})                # the backup is only offered while the file is missing

    def test_an_empty_file_is_backed_up_too(self):
        open(self.flag, "w").close()                                                        # the file is normally empty
        self.assertTrue(reb.auto_allow()[0])
        self.assertTrue(os.path.exists(reb.NOAUTO_BACKUP))
        self.assertTrue(reb.auto_restore()[0])
        self.assertEqual(os.path.getsize(self.flag), 0)

    def test_nothing_is_removed_when_the_backup_cannot_be_made(self):
        open(self.flag, "w").close()
        reb.NOAUTO_BACKUP = os.path.join(self.tmp, "no", "such", "folder", "backup")
        try:
            done, message = reb.auto_allow()
        finally:
            reb.NOAUTO_BACKUP = os.path.join(core.BASE_DIR, "noautoupdates.backup")
        self.assertFalse(done)
        self.assertTrue(os.path.exists(self.flag))
        self.assertEqual(self.spawned, [])
        self.assertIn("nothing was removed", message)

    def test_the_cases_that_do_nothing(self):
        self.assertFalse(reb.auto_allow()[0])                                               # there is no file: updates are on already
        self.assertFalse(reb.auto_restore()[0])                                             # no backup
        with open(reb.NOAUTO_BACKUP, "w") as f:
            f.write("x")
        open(self.flag, "w").close()
        self.assertFalse(reb.auto_restore()[0])                                             # the file is there already
        self.assertEqual(self.spawned, [])

    def test_a_removal_that_does_not_happen_is_reported_and_the_backup_kept(self):
        open(self.flag, "w").close()
        up._spawn = lambda cmd: None                                                        # systemd-run failed
        import time
        real = time.sleep
        reb.time.sleep = lambda s: None
        reb.time.time, orig = (lambda t=[0]: t.__setitem__(0, t[0] + 3) or t[0]), reb.time.time
        try:
            done, message = reb.auto_allow()
        finally:
            reb.time.time = orig
            reb.time.sleep = real
        self.assertFalse(done)
        self.assertTrue(os.path.exists(reb.NOAUTO_BACKUP))
        self.assertIn("backup is kept", message)

    def test_the_page_gets_the_state_and_both_paths_need_the_pin(self):
        open(self.flag, "w").close()
        out = up.status()
        out.update(reb.view(out))
        self.assertEqual(out["auto"], {"off": True, "backup": False})
        self.assertIn("/autoupdates/allow", reb.PROTECTED)
        self.assertIn("/autoupdates/restore", reb.PROTECTED)
        self.assertIn("/autoupdates/allow", reb.POST)
        layout = json.load(open(os.path.join(os.path.dirname(reb.__file__), "layout.json")))
        shows = [i.get("show") for i in layout["settings"][0]["items"]]
        self.assertIn("@update.auto.off", shows)
        self.assertIn("@update.auto.backup", shows)


if __name__ == "__main__":
    unittest.main()
