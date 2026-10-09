"""The offline bundle scripts and the restart-on-crash settings (the scripts themselves need apt and a network, so they are only parsed here)."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from support import ROOT


def read(*parts):
    with open(os.path.join(ROOT, *parts)) as f:
        return f.read()


class OfflineBundle(unittest.TestCase):
    def test_scripts_parse(self):
        bash = shutil.which("bash")
        for name in ("prepare-offline.sh", "install-offline.sh"):
            path = os.path.join(ROOT, "offline", name)
            self.assertEqual(subprocess.run([bash, "-n", path]).returncode, 0, path)
            self.assertTrue(os.access(path, os.X_OK), name)

    def test_the_package_list_has_what_was_asked_for(self):
        names = [re.sub(r"#.*", "", l).strip() for l in read("offline", "packages.txt").splitlines()]
        names = [n for n in names if n]
        for want in ("firefox-esr", "chromium", "mpv", "python3", "openssl", "dnsmasq-base", "ipxe"):
            self.assertIn(want, names)

    def test_the_pxe_installer_skips_apt_when_the_packages_are_there(self):
        text = read("pxe", "install-pxe.sh")
        self.assertRegex(text, r'if \[ ! -x /usr/sbin/dnsmasq \].*\n\s+apt-get update')


class RestartOnCrash(unittest.TestCase):
    def test_the_host_kiosk_browser_is_started_again(self):
        text = read("kiosk", "kiosk-browser.sh")
        self.assertIn("while true; do", text)
        self.assertNotIn("exec ", text)                         # exec would end the loop with the browser
        self.assertEqual(subprocess.run(["bash", "-n", os.path.join(ROOT, "kiosk", "kiosk-browser.sh")]).returncode, 0)

    def test_the_image_kiosk_restarts_firefox_and_chromium(self):
        text = read("pxe", "image", "usr", "local", "bin", "kiosk-session")
        loop = text[text.index("while true; do"):]
        self.assertIn("firefox-esr", loop)
        self.assertIn("chromium", loop)
        self.assertIn("sleep 2", loop)
        self.assertIn("Restart=always", read("pxe", "image", "etc", "systemd", "system", "kiosk.service"))        # X and the session

    def test_the_browser_is_chosen_on_the_command_line(self):
        session = os.path.join(ROOT, "pxe", "image", "usr", "local", "bin", "kiosk-session")
        d = tempfile.mkdtemp()
        try:
            def browser(cmdline):
                path = os.path.join(d, "cmdline")
                with open(path, "w") as f:
                    f.write(cmdline)
                env = dict(os.environ, CMDLINE_FILE=path, CONFIG_FILE=os.path.join(d, "none"), KIOSK_DRY_RUN="browser")
                return subprocess.run(["sh", session], env=env, stdout=subprocess.PIPE, check=True).stdout.decode().strip()
            self.assertEqual(browser("quiet"), "firefox")
            self.assertEqual(browser("quiet checkin_browser=chromium"), "chromium")
            self.assertEqual(browser("quiet checkin_browser=lynx"), "firefox")
        finally:
            shutil.rmtree(d)

    def test_the_computer_restarts_after_a_panic_or_a_hang(self):
        for text in (read("install.sh"), read("pxe", "image", "etc", "sysctl.d", "90-checkin-reboot.conf") +
                     read("pxe", "image", "etc", "systemd", "system.conf.d", "90-checkin-watchdog.conf")):
            self.assertIn("kernel.panic", text)
            self.assertIn("RuntimeWatchdogSec", text)
        self.assertIn("90-checkin-reboot.conf", read("uninstall.sh"))
        self.assertIn("softdog", read("pxe", "image", "etc", "modules-load.d", "softdog.conf"))
        with open(os.path.join(ROOT, "pxe", "kiosk-image.json")) as f:
            m = json.load(f)
        for key in ("args", "install_args", "shell_args"):
            self.assertIn("panic=10", m[key])
        self.assertIn("panic=10", read("pxe", "image", "usr", "local", "bin", "checkin-install"))

    def test_the_image_has_both_browsers_and_mpv(self):
        text = read("pxe", "build-image.sh")
        for pkg in ("firefox-esr", "chromium", "mpv"):
            self.assertIn(pkg, text)


if __name__ == "__main__":
    unittest.main()
