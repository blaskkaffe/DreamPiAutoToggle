"""The PXE boot server's generated files and the kiosk session's address handling (the image and the server themselves are not run here)."""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from support import ROOT

PXE = os.path.join(ROOT, "pxe")
sys.path.insert(0, PXE)
import pxe_config  # noqa: E402

SESSION = os.path.join(PXE, "image", "usr", "local", "bin", "kiosk-session")


def session_url(cmdline):
    d = tempfile.mkdtemp()
    try:
        path = os.path.join(d, "cmdline")
        with open(path, "w") as f:
            f.write(cmdline)
        env = dict(os.environ, CMDLINE_FILE=path, KIOSK_DRY_RUN="1")
        return subprocess.run(["sh", SESSION], env=env, stdout=subprocess.PIPE, check=True).stdout.decode().strip()
    finally:
        shutil.rmtree(d)


class ConfigFiles(unittest.TestCase):
    def render(self, **kw):
        a = dict(ip="192.168.1.20", interface="eth0", network="192.168.1.0", board_url="http://192.168.1.20/", http_port=8069, dest="/opt/x")
        a.update(kw)
        return pxe_config.render(a["ip"], a["interface"], a["network"], a["board_url"], a["http_port"], a["dest"])

    def test_dnsmasq_is_proxy_dhcp_for_both_firmwares(self):
        conf, _ = self.render()
        self.assertIn("dhcp-range=192.168.1.0,proxy", conf)
        self.assertIn("port=0", conf)                                 # no DNS: it must not clash with the host's resolver
        self.assertIn("tftp-root=/opt/x/tftp", conf)
        self.assertIn("tag:!ipxe,x86PC,", conf)
        self.assertIn("undionly.kpxe", conf)
        self.assertIn("tag:!ipxe,X86-64_EFI,", conf)
        self.assertIn("ipxe.efi", conf)
        self.assertIn("tag:ipxe,X86-64_EFI,", conf)

    def test_boot_script_hands_the_board_address_to_the_kernel(self):
        _, boot = self.render()
        self.assertTrue(boot.startswith("#!ipxe"))
        self.assertIn("set server http://192.168.1.20:8069", boot)
        self.assertIn("checkin_url=${board}", boot)
        self.assertIn("fetch=${server}/filesystem.squashfs", boot)
        self.assertIn("${net0/mac:hexhyp}.ipxe", boot)

    def test_unusable_values_are_refused(self):
        with self.assertRaises(ValueError):
            self.render(board_url="http://x/ boot")
        with self.assertRaises(ValueError):
            self.render(interface="")

    def test_command_line_writes_both_files(self):
        d = tempfile.mkdtemp()
        try:
            subprocess.check_call([sys.executable, os.path.join(PXE, "pxe_config.py"), "--ip", "10.0.0.2", "--interface", "eth1",
                                   "--network", "10.0.0.0", "--board-url", "http://10.0.0.2/", "--dest", d])
            self.assertTrue(os.path.exists(os.path.join(d, "dnsmasq.conf")))
            self.assertTrue(os.path.exists(os.path.join(d, "tftp", "boot.ipxe")))
        finally:
            shutil.rmtree(d)


class KioskSession(unittest.TestCase):
    def test_address_from_the_kernel_command_line(self):
        self.assertEqual(session_url("boot=live ip=dhcp checkin_url=http://10.0.0.2 checkin_location="), "http://10.0.0.2/")

    def test_buildings_are_added(self):
        self.assertEqual(session_url("quiet checkin_url=http://10.0.0.2/ checkin_location=Omr%C3%A5de+A,B"),
                         "http://10.0.0.2/?location=Omr%C3%A5de+A,B")

    def test_default_when_nothing_is_given(self):
        self.assertEqual(session_url("quiet"), "http://checkin.local/")


class Files(unittest.TestCase):
    def test_scripts_parse(self):
        for path in (SESSION,):
            self.assertEqual(subprocess.run(["sh", "-n", path]).returncode, 0, path)
        bash = shutil.which("bash")
        for path in glob.glob(os.path.join(PXE, "*.sh")):
            self.assertEqual(subprocess.run([bash, "-n", path]).returncode, 0, path)

    def test_firefox_policy_is_json(self):
        with open(os.path.join(PXE, "image", "etc", "firefox", "policies", "policies.json")) as f:
            self.assertTrue(json.load(f)["policies"]["DisableAppUpdate"])


if __name__ == "__main__":
    unittest.main()
