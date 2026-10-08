"""The PXE boot server's generated files and the kiosk session's address handling (the image and the server themselves are not run here)."""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from support import ROOT

PXE = os.path.join(ROOT, "pxe")
sys.path.insert(0, PXE)
import pxe_boot  # noqa: E402
import pxe_config  # noqa: E402
import pxe_server  # noqa: E402

SESSION = os.path.join(PXE, "image", "usr", "local", "bin", "kiosk-session")


def session_url(cmdline, **extra):
    d = tempfile.mkdtemp()
    try:
        path = os.path.join(d, "cmdline")
        with open(path, "w") as f:
            f.write(cmdline)
        env = dict(os.environ, CMDLINE_FILE=path, KIOSK_DRY_RUN="1", CONFIG_FILE=os.path.join(d, "none"))
        env.update(extra)
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

    def test_first_script_reports_serial_and_mac_to_the_boot_server(self):
        _, boot = self.render()
        self.assertTrue(boot.startswith("#!ipxe"))
        self.assertIn("set server http://192.168.1.20:8069", boot)
        self.assertIn("${server}/boot?serial=${serial:uristring}&mac=${net0/mac:hexhyp}", boot)

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
    def test_address_and_screen_id_from_the_kernel_command_line(self):
        self.assertEqual(session_url("boot=live ip=dhcp checkin_url=http://10.0.0.2 checkin_screen=abc123 checkin_location="),
                         "http://10.0.0.2/?screen=abc123")

    def test_buildings_are_added(self):
        self.assertEqual(session_url("quiet checkin_url=http://10.0.0.2/ checkin_screen=abc checkin_location=Omr%C3%A5de+A,B"),
                         "http://10.0.0.2/?screen=abc&location=Omr%C3%A5de+A,B")

    def test_default_when_nothing_is_given(self):
        self.assertRegex(session_url("quiet"), r"^http://checkin\.local/\?screen=\S+$")

    def test_a_local_install_reads_its_config_file(self):
        d = tempfile.mkdtemp()
        try:
            conf = os.path.join(d, "conf")
            with open(conf, "w") as f:
                f.write("CHECKIN_URL='http://10.0.0.9/'\nCHECKIN_SCREEN='ser1'\nCHECKIN_LOCATION='A'\n")
            self.assertEqual(session_url("quiet", CONFIG_FILE=conf), "http://10.0.0.9/?screen=ser1&location=A")
            self.assertEqual(session_url("checkin_url=http://other/", CONFIG_FILE=conf), "http://other/?screen=ser1&location=A")      # the command line wins
        finally:
            shutil.rmtree(d)


class Files(unittest.TestCase):
    def test_scripts_parse(self):
        for path in (SESSION,):
            self.assertEqual(subprocess.run(["sh", "-n", path]).returncode, 0, path)
        bash = shutil.which("bash")
        wizard = os.path.join(PXE, "image", "usr", "local", "bin", "checkin-install")
        self.assertEqual(subprocess.run([bash, "-n", wizard]).returncode, 0, wizard)
        for path in glob.glob(os.path.join(PXE, "*.sh")):
            self.assertEqual(subprocess.run([bash, "-n", path]).returncode, 0, path)

    def test_the_loading_screen_is_the_chicken_logo(self):
        share = os.path.join(PXE, "image", "usr", "local", "share", "checkin-kiosk")
        with open(os.path.join(share, "logo.png"), "rb") as f:
            self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")
        with open(os.path.join(share, "loading.html")) as f:
            html = f.read()
        self.assertIn('src="logo.png"', html)
        self.assertIn("location.hash", html)                                           # the board's address comes after the #
        with open(SESSION) as f:
            self.assertIn("loading.html#$SHOW", f.read())

    def test_firefox_policy_is_json(self):
        with open(os.path.join(PXE, "image", "etc", "firefox", "policies", "policies.json")) as f:
            self.assertTrue(json.load(f)["policies"]["DisableAppUpdate"])


IMAGES = {"kiosk": {"id": "kiosk", "name": "Check-in screen", "kernel": "vmlinuz", "initrd": "initrd.img", "order": 1,
                    "args": "boot=live fetch={base}/fs.squashfs checkin_url={board} checkin_screen={screen} checkin_location={location}",
                    "install_args": "boot=live fetch={base}/fs.squashfs checkin_install", "shell_args": "boot=live checkin_shell"},
          "tools": {"id": "tools", "name": "Memory test", "kernel": "mt", "initrd": "mt.img", "order": 50, "args": "console=tty0",
                    "install_args": "", "shell_args": ""}}


class BootLogic(unittest.TestCase):
    def test_machine_ids(self):
        self.assertEqual(pxe_boot.machine_id("ABC 123", "aa:bb:cc:dd:ee:ff"), "abc_123")
        for junk in ("", "To Be Filled By O.E.M.", "Default string", "00000000", "FFFFFFFF"):
            self.assertEqual(pxe_boot.machine_id(junk, "AA:BB:CC:DD:EE:FF"), "mac-aabbccddeeff", junk)      # no usable serial: the MAC address names it
        self.assertEqual(pxe_boot.machine_id("", "nonsense"), "")

    def test_a_computer_set_to_an_image_skips_the_menu_but_i_installs(self):
        text = pxe_boot.boot_script("ser1", "SER1", "aa-bb-cc-dd-ee-ff", {}, IMAGES, {"image": "kiosk", "location": "Område A"}, "http://s:8069", "http://b/")
        head = text.split(":menu")[0]
        self.assertIn("prompt --key 0x69 --timeout 3000", head)                     # I while booting
        self.assertIn("goto install-kiosk", head)
        self.assertIn("goto boot-kiosk", head)
        self.assertIn("checkin_screen=ser1 checkin_location=Omr%C3%A5de+A", text)
        self.assertIn("kernel http://s:8069/images/kiosk/vmlinuz", text)

    def test_an_image_that_cannot_be_installed_has_no_i_prompt(self):
        text = pxe_boot.boot_script("ser1", "SER1", "", {}, IMAGES, {"image": "tools"}, "http://s:8069", "http://b/")
        self.assertNotIn("0x69", text.split(":menu")[0])

    def test_an_unset_computer_gets_the_menu_with_install_shell_and_the_others(self):
        text = pxe_boot.boot_script("ser2", "SER2", "", {}, IMAGES, None, "http://s:8069", "http://b/")
        self.assertNotIn("0x69", text.split(":menu")[0])
        for want in ("item --key 1 boot-kiosk Check-in screen", "item --key 2 boot-tools Memory test", "item --key i install-kiosk",
                     "item --key s shell-kiosk", "item ipxeshell iPXE shell", "item local Boot from the local disk",
                     "choose --default boot-kiosk --timeout 20000"):
            self.assertIn(want, text)
        self.assertNotIn("install-tools", text)                                       # only an image that allows it can be installed
        self.assertIn("checkin_install", text.split(":install-kiosk")[1].split(":shell-kiosk")[0])

    def test_an_installed_computer_boots_its_disk(self):
        text = pxe_boot.boot_script("ser3", "SER3", "", {"installed": True}, IMAGES, None, "http://s:8069", "http://b/")
        self.assertIn("Press N for the network boot menu || exit", text)

    def test_images_are_read_from_folders(self):
        www = tempfile.mkdtemp()
        try:
            for name, manifest in (("kiosk", {"name": "K", "kernel": "vmlinuz", "initrd": "i", "order": 2}), ("bad", {"name": "no kernel"}),
                                   ("evil", {"name": "x", "kernel": "../../etc/passwd", "initrd": "i"})):
                os.makedirs(os.path.join(www, "images", name))
                with open(os.path.join(www, "images", name, "image.json"), "w") as f:
                    json.dump(manifest, f)
            self.assertEqual(list(pxe_boot.load_images(www)), ["kiosk"])
        finally:
            shutil.rmtree(www)

    def test_registry_and_assignments(self):
        d = tempfile.mkdtemp()
        try:
            st = pxe_boot.Store(d)
            self.assertEqual(st.register("ser1", "SER1", "AA:BB:CC:DD:EE:FF", "10.0.0.5")["boots"], 1)
            self.assertEqual(st.register("ser1", "SER1", "AA:BB:CC:DD:EE:FF", "10.0.0.5")["boots"], 2)
            self.assertEqual(st.registry()["ser1"]["mac"], "aa-bb-cc-dd-ee-ff")
            self.assertTrue(st.set_installed("ser1"))
            self.assertFalse(st.set_installed("nobody"))
            st.assign("ser1", "kiosk", "A")
            self.assertEqual(st.assignments(), {"ser1": {"image": "kiosk", "location": "A", "board_url": "", "args": ""}})
            self.assertTrue(st.unassign("ser1"))
        finally:
            shutil.rmtree(d)


class BootServer(unittest.TestCase):
    """The real server on a random port: a computer reports itself and gets its script."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp()
        folder = os.path.join(cls.root, "www", "images", "kiosk")
        os.makedirs(folder)
        shutil.copy(os.path.join(PXE, "kiosk-image.json"), os.path.join(folder, "image.json"))
        with open(os.path.join(folder, "vmlinuz"), "w") as f:
            f.write("kernel")
        cls.srv = pxe_server.make_server("127.0.0.1", 0, cls.root, "http://127.0.0.1/")
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.store = pxe_boot.Store(os.path.join(cls.root, "data"))

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.root)

    def get(self, path):
        return urlopen("http://127.0.0.1:%d%s" % (self.port, path), timeout=10).read().decode()

    def test_an_unknown_computer_is_listed_but_does_not_boot_until_allowed(self):
        self.srv.store._grants.clear()                                                 # (every test here comes from the same address)
        text = self.get("/boot?serial=SN-77&mac=aa-bb-cc-dd-ee-01&product=Box&ip=10.0.0.7")
        self.assertIn("not approved yet", text)                                        # no boot script, only its numbers and what to do
        self.assertIn("Serial number: SN-77", text)
        self.assertIn("MAC address:   aa-bb-cc-dd-ee-01", text)
        self.assertNotIn("kernel", text)
        rec = self.store.registry()["sn-77"]                                           # but it is in the "has connected" list
        self.assertEqual((rec["serial"], rec["mac"], rec["ip"]), ("SN-77", "aa-bb-cc-dd-ee-01", "10.0.0.7"))
        self.assertEqual(self.store.status("sn-77", "aa-bb-cc-dd-ee-01"), "pending")
        with self.assertRaises(HTTPError) as e:                                        # and the image files are not served to it
            self.get("/images/kiosk/vmlinuz")
        self.assertEqual(e.exception.code, 403)

    def test_allow_assign_install_flow(self):
        self.get("/boot?serial=SN-78&mac=aa-bb-cc-dd-ee-03")
        self.assertTrue(self.store.allow("SN-78"))
        text = self.get("/boot?serial=SN-78&mac=aa-bb-cc-dd-ee-03")
        self.assertIn("menu Check-in screen sn-78", text)                              # allowed, not set to anything: the menu
        self.assertIn("approved (sn-78", text)                                         # and it says it is connected
        self.assertEqual(self.get("/images/kiosk/vmlinuz"), "kernel")                  # its address may fetch the files now
        self.store.assign("sn-78", "kiosk", "A", "http://other/", "foo=bar")
        head = self.get("/boot?serial=SN-78&mac=aa-bb-cc-dd-ee-03")
        self.assertIn("goto boot-kiosk", head.split(":menu")[0])
        self.assertIn("checkin_url=http://other/", head)                               # per-computer settings
        self.assertIn("foo=bar", head)
        self.assertEqual(self.get("/installed?id=sn-78").strip(), "ok")
        self.assertTrue(self.store.registry()["sn-78"]["installed"])
        with self.assertRaises(HTTPError) as e:
            self.get("/installed?id=nobody")
        self.assertEqual(e.exception.code, 404)

    def test_a_mac_on_the_whitelist_is_enough_and_a_block_wins(self):
        self.store.allow("AA:BB:CC:DD:EE:04")                                         # before the computer has ever connected
        self.assertIn("kernel", self.get("/boot?serial=SN-79&mac=aa-bb-cc-dd-ee-04"))
        self.store.block("sn-79")
        text = self.get("/boot?serial=SN-79&mac=aa-bb-cc-dd-ee-04")
        self.assertIn("has been blocked", text)
        self.assertNotIn("kernel", text)

    def test_open_mode_lets_everybody_boot(self):
        self.store.set_mode("open")
        try:
            self.assertIn("kernel", self.get("/boot?serial=SN-80&mac=aa-bb-cc-dd-ee-05"))
        finally:
            self.store.set_mode("whitelist")

    def test_a_computer_without_a_serial_is_named_by_its_mac(self):
        self.get("/boot?serial=To+Be+Filled+By+O.E.M.&mac=AA-BB-CC-DD-EE-02")
        self.assertIn("mac-aabbccddee02", self.store.registry())

    def test_image_folders_are_not_listed(self):
        self.store.set_mode("open")
        try:
            self.get("/boot?serial=x1&mac=aa-bb-cc-dd-ee-06")
            with self.assertRaises(HTTPError):
                self.get("/images/kiosk/")
        finally:
            self.store.set_mode("whitelist")


class AdminTool(unittest.TestCase):
    def test_assign_list_unassign(self):
        root = tempfile.mkdtemp()
        try:
            folder = os.path.join(root, "www", "images", "kiosk")
            os.makedirs(folder)
            shutil.copy(os.path.join(PXE, "kiosk-image.json"), os.path.join(folder, "image.json"))
            env = dict(os.environ, CHECKIN_PXE_DIR=root)
            os.makedirs(os.path.join(root, "data"))
            tool = os.path.join(PXE, "pxectl.py")

            def run(*a):
                p = subprocess.run([sys.executable, tool] + list(a), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                return p.returncode, p.stdout.decode()
            self.assertEqual(run("assign", "SER9", "kiosk", "--location", "Område A")[0], 0)
            self.assertEqual(pxe_boot.Store(os.path.join(root, "data")).assignments()["ser9"]["location"], "Område A")
            self.assertIn("kiosk  location=Område A", run("list")[1])
            self.assertEqual(run("assign", "ser9", "kiosk", "--args", "bad;rm -rf")[0], 1)                   # kernel arguments are checked
            self.assertEqual(run("allow", "SER9", "AA:BB:CC:DD:EE:07")[0], 0)
            self.assertIn("allowed", run("list")[1])
            self.assertIn("ser9", run("list")[1])
            self.assertEqual(run("pending")[1].count("PENDING"), 0)
            self.assertEqual(run("block", "ser9")[0], 0)
            self.assertIn("blocked", run("list")[1])
            self.assertEqual(run("clear", "ser9")[0], 0)
            self.assertEqual(run("allow", "not a key!")[0], 1)
            self.assertEqual(run("mode", "open")[0], 0)
            self.assertEqual(run("assign", "ser9", "nope")[0], 1)                          # an image that does not exist
            self.assertEqual(run("unassign", "ser9")[0], 0)
        finally:
            shutil.rmtree(root)


if __name__ == "__main__":
    unittest.main()
