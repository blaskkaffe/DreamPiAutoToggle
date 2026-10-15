"""The network watch: what it logs when the computer's network changes (the host losing its address or link is what makes the screens lose contact)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "base"))
import base_netwatch as nw  # noqa: E402


class NetWatch(unittest.TestCase):
    def test_parsers(self):
        text = "2: eth0    inet 192.168.1.20/24 brd 192.168.1.255 scope global eth0\\       valid_lft forever\n3: wlan0    inet 10.0.0.5/24 scope global wlan0\n4: veth1@if3    inet 172.17.0.1/16 scope global veth1\n"
        self.assertEqual(nw.parse_addrs(text), {"eth0": ["192.168.1.20/24"], "wlan0": ["10.0.0.5/24"], "veth1": ["172.17.0.1/16"]})
        self.assertEqual(nw.parse_gateway("default via 192.168.1.1 dev eth0 proto dhcp metric 100\n"), "192.168.1.1")
        self.assertEqual(nw.parse_gateway(""), "")

    def test_changes_are_described(self):
        up = {"nets": {"eth0": {"state": "up", "carrier": "1", "addrs": ["192.168.1.20/24"]}}, "gateway": "192.168.1.1"}
        self.assertEqual(nw.changes(up, up), [])
        down = {"nets": {"eth0": {"state": "down", "carrier": "0", "addrs": []}}, "gateway": ""}
        got = "\n".join(nw.changes(up, down))
        for word in ("eth0 link up -> down", "address 192.168.1.20/24 -> none", "default gateway 192.168.1.1 -> none"):
            self.assertIn(word, got)
        other = {"nets": {"eth0": {"state": "up", "carrier": "1", "addrs": ["192.168.1.99/24"]}}, "gateway": "192.168.1.1"}
        self.assertIn("192.168.1.20/24 -> 192.168.1.99/24", "\n".join(nw.changes(up, other)))
        self.assertIn("appeared", "\n".join(nw.changes({"nets": {}, "gateway": ""}, up)))
        slow = {"nets": {"eth0": {"state": "up", "carrier": "1", "addrs": ["192.168.1.20/24"], "link": "10 Mb/s half"}}, "gateway": "192.168.1.1"}
        fast = {"nets": {"eth0": {"state": "up", "carrier": "1", "addrs": ["192.168.1.20/24"], "link": "1000 Mb/s full"}}, "gateway": "192.168.1.1"}
        self.assertIn("eth0 negotiated 10 Mb/s half -> 1000 Mb/s full", "\n".join(nw.changes(slow, fast)))

    def test_a_snapshot_never_fails(self):
        s = nw.snapshot()
        self.assertIn("nets", s)
        self.assertIn("gateway", s)
        self.assertIsNone(nw.gateway_answers(""))


if __name__ == "__main__":
    unittest.main()
