"""The network box's Serial PPP and KOSnet rows (modules/switcher/netswitch_switcher_state.py): shown only while the RP2040 Dreamcast cable's serial
or network side is in use on this Pi, read from DreamPi's netlink_config.ini, /sys/class/net, /proc and the cable's lease file."""
import os
import unittest

from support import core, web, sandbox, cleanup
import netswitch_switcher_state as st


class Paths(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        t = self.tmp
        self.was = dict((n, getattr(st, n)) for n in ("NETLINK_CONFIGS", "NOAUTO", "SYS_NET", "PROC", "RUN_DIR", "ARP", "KOSNET_LEASES"))
        st.NETLINK_CONFIGS = (os.path.join(t, "boot.ini"), os.path.join(t, "dreampi.ini"))
        st.NOAUTO = os.path.join(t, "noauto")
        st.SYS_NET, st.PROC, st.RUN_DIR = os.path.join(t, "net"), os.path.join(t, "proc"), os.path.join(t, "run")
        st.ARP, st.KOSNET_LEASES = os.path.join(t, "arp"), os.path.join(t, "leases")
        for d in (st.SYS_NET, st.PROC, st.RUN_DIR):
            os.makedirs(d)
        self.port = os.path.join(t, "dccable")

    def tearDown(self):
        for n, v in self.was.items():
            setattr(st, n, v)
        cleanup(self.tmp)

    def write(self, path, text):
        with open(path, "w") as f:
            f.write(text)

    def ini(self, body, which=1):
        self.write(st.NETLINK_CONFIGS[which], body)

    def pppd(self, pid, device, iface=None):
        os.makedirs(os.path.join(st.PROC, str(pid)))
        self.write(os.path.join(st.PROC, str(pid), "cmdline"), "\0".join(["pppd", device, "115200", "nodetach"]) + "\0")
        os.makedirs(os.path.join(st.SYS_NET, iface or "ppp0"), exist_ok=True)
        if iface:
            self.write(os.path.join(st.RUN_DIR, iface + ".pid"), "%d\n%s\n" % (pid, iface))

    # ---- the serial config as netlink.py reads it
    def test_defaults_and_the_serial_port_section(self):
        self.assertEqual(st.serial_config(), ("/dev/ttyUSB0", 115200, False, False))                # no config file
        self.ini("[Serial Port]\n; port = /dev/nothing\nport = %s\nbaud = 57600\n[DCNet]\nenabled = yes\nport = 7654\n" % self.port)
        self.assertEqual(st.serial_config(), (self.port, 57600, False, True))                       # the port line of another section is not it
        self.ini("[Serial Port]\ndisabled = yes\n")
        self.assertTrue(st.serial_config()[2])
        self.ini("[server:199401]\nport = 4821\n")
        self.assertEqual(st.serial_config()[0], "/dev/ttyUSB0")

    def test_boot_config_wins_and_noautoupdates_means_defaults(self):
        self.ini("[Serial Port]\nport = /dev/one\n", 0)
        self.ini("[Serial Port]\nport = /dev/two\n", 1)
        self.assertEqual(st.serial_config()[0], "/dev/one")
        self.write(st.NOAUTO, "")                                                                  # netlink.py reads no config then
        self.assertEqual(st.serial_config(), ("/dev/ttyUSB0", 115200, False, False))

    # ---- the Serial PPP row
    def test_row_is_hidden_without_an_adapter_and_when_disabled(self):
        self.assertFalse(st.serial_ppp_view()["show"])
        self.ini("[Serial Port]\ndisabled = yes\nport = %s\n" % self.port)
        self.write(self.port, "")
        self.assertFalse(st.serial_ppp_view()["show"])

    def test_row_ready_missing_and_connected(self):
        self.ini("[Serial Port]\nport = %s\nbaud = 115200\n" % self.port)
        v = st.serial_ppp_view()
        self.assertEqual((v["show"], v["state"], v["text"]), (True, "warn", "Cable not found"))   # named in the config but not plugged in
        self.write(self.port, "")
        v = st.serial_ppp_view()
        self.assertEqual((v["state"], v["text"], v["sub"]), ("ok", "Ready", "%s • 115200 baud" % self.port))
        self.pppd(2170, self.port, "ppp1")
        v = st.serial_ppp_view()
        self.assertEqual((v["state"], v["text"], v["sub"]), ("ok", "Connected", "ppp1 • %s" % self.port))

    def test_a_modem_call_is_not_a_serial_call_and_symlinks_are_followed(self):
        self.write(self.port, "")
        link = os.path.join(self.tmp, "by-name")
        os.symlink(self.port, link)
        self.ini("[Serial Port]\nport = %s\n" % link)
        self.pppd(900, os.path.join(self.tmp, "ttyACM2"), "ppp0")                                    # DreamPi's modem call
        self.assertEqual(st.serial_ppp_view()["text"], "Ready")
        self.pppd(901, self.port)                                                                    # same device as the symlink, interface not in a pid file
        self.assertEqual(st.serial_ppp_view()["sub"].split(" ")[0], "ppp")

    def test_nothing_is_scanned_without_a_ppp_interface(self):
        self.write(self.port, "")
        self.ini("[Serial Port]\nport = %s\n" % self.port)
        os.makedirs(os.path.join(st.PROC, "5"))                                                      # no cmdline file here: reading it would be skipped, not crash
        self.assertEqual(st.serial_call(self.port), None)

    # ---- the KOSnet row
    def test_kosnet_row_follows_the_cable_interface_and_the_lease(self):
        self.assertFalse(st.kosnet_view()["show"])
        iface = os.path.join(st.SYS_NET, st.KOSNET_IFACE)
        os.makedirs(iface)
        self.write(os.path.join(iface, "operstate"), "up\n")
        v = st.kosnet_view()
        self.assertEqual((v["show"], v["state"], v["text"]), (True, "ok", "Ready"))
        self.write(st.KOSNET_LEASES, "1792100000 aa:bb:cc:dd:ee:ff 192.168.50.12 dreamcast *\n")
        self.write(st.ARP, "IP address       HW type     Flags       HW address            Mask     Device\n"
                           "192.168.50.12    0x1         0x0         00:00:00:00:00:00     *        %s\n" % st.KOSNET_IFACE)
        self.assertEqual(st.kosnet_view()["text"], "Ready")                                          # an incomplete ARP entry: the Dreamcast is gone
        self.write(st.ARP, "IP address       HW type     Flags       HW address            Mask     Device\n"
                           "192.168.50.12    0x1         0x2         aa:bb:cc:dd:ee:ff     *        %s\n" % st.KOSNET_IFACE)
        v = st.kosnet_view()
        self.assertEqual((v["text"], v["sub"]), ("Connected", "Dreamcast 192.168.50.12"))
        self.write(os.path.join(iface, "operstate"), "down\n")
        self.assertEqual(st.kosnet_view()["text"], "Link down")

    def test_both_rows_are_in_the_api_between_modem_and_internet(self):
        d, warnings = {}, []
        import netswitch_switcher as sw
        sw.api(d, warnings)
        self.assertEqual(sorted(d["serialppp"]), ["show", "state", "sub", "text"])
        self.assertEqual(sorted(d["kosnet"]), ["show", "state", "sub", "text"])
        import json
        rows = [r["label"] for r in json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modules", "switcher", "layout.json")))["dashboard"][0]["items"][0]["rows"]]
        self.assertEqual(rows[1:5], ["Modem", "Serial PPP", "KOSnet", "Internet"])


if __name__ == "__main__":
    unittest.main()
