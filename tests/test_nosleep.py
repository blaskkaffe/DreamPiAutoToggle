"""install.sh keeps the host awake (a suspended host does not answer the screens until somebody uses it); the block is run here against a stub
systemctl and a temp folder, and uninstall.sh puts it back."""
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

from support import ROOT


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class NoSleep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bin = os.path.join(self.tmp, "bin")
        os.makedirs(self.bin)
        self.calls = os.path.join(self.tmp, "calls")
        stub = os.path.join(self.bin, "systemctl")
        with open(stub, "w") as f:      # "is-enabled" says enabled, everything else is written down
            f.write('#!/bin/sh\necho "$@" >> %s\n[ "$1" = is-enabled ] && echo enabled\nexit 0\n' % self.calls)
        os.chmod(stub, os.stat(stub).st_mode | stat.S_IEXEC)
        text = read("install.sh")
        block = text[text.index("# The host must never sleep"):text.index("# ------------------------------------------------------------------ modules")]
        self.block = block.replace("/etc/", self.tmp + "/etc/")
        self.dest = os.path.join(self.tmp, "dest")
        os.makedirs(self.dest)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_block(self, allow):
        env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"])
        return subprocess.run(["sh", "-e", "-c", 'DEST="%s"; ALLOW_SLEEP=%d\n%s' % (self.dest, allow, self.block)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True).stdout.decode()

    def test_the_host_is_kept_awake_and_it_is_undone(self):
        self.run_block(0)
        conf = open(os.path.join(self.tmp, "etc/systemd/logind.conf.d/90-checkin-no-sleep.conf")).read()
        for line in ("IdleAction=ignore", "HandleLidSwitch=ignore", "HandleSuspendKey=ignore"):
            self.assertIn(line, conf)
        calls = open(self.calls).read()
        for t in ("sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target"):
            self.assertIn("mask " + t, calls)
        self.assertEqual(sorted(open(os.path.join(self.dest, "sleep_masked")).read().split()), ["hibernate.target", "hybrid-sleep.target", "sleep.target", "suspend.target"])
        self.run_block(0)                                                   # a second install changes nothing it did not do before
        self.run_block(1)                                                   # --allow-sleep: back to how it was
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "etc/systemd/logind.conf.d/90-checkin-no-sleep.conf")))
        self.assertFalse(os.path.exists(os.path.join(self.dest, "sleep_masked")))
        self.assertIn("unmask", open(self.calls).read())

    def test_the_scripts_parse_and_uninstall_undoes_it(self):
        for name in ("install.sh", "uninstall.sh", "diagnose-network.sh"):
            subprocess.check_call(["sh", "-n", os.path.join(ROOT, name)])
        un = read("uninstall.sh")
        self.assertIn("90-checkin-no-sleep.conf", un)
        self.assertIn("unmask", un)
        self.assertTrue(re.search(r"--allow-sleep", read("install.sh")))


if __name__ == "__main__":
    unittest.main()
