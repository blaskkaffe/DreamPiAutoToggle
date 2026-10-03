"""The measurements behind the LED messages Wi-Fi signal and slow connection (parsers only; nothing runs ping)."""
import unittest
from unittest import mock

from support import probes

PING = """3 packets transmitted, 3 received, 0% packet loss, time 402ms
rtt min/avg/max/mdev = 11.250/12.500/14.000/1.200 ms
"""
LOSSY = """3 packets transmitted, 1 received, 66.6667% packet loss, time 2003ms
rtt min/avg/max/mdev = 250.000/250.000/250.000/0.000 ms
"""
WIRELESS = """Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22
wlan0: 0000   60.  -52.  -256        0      0      0      0      0        0
"""


class PingTests(unittest.TestCase):
    def test_average_and_loss_are_read(self):
        self.assertEqual(probes.parse_ping(PING), (12.5, 0.0))
        self.assertEqual(probes.parse_ping(LOSSY), (250.0, 66.6667))

    def test_unreadable_text_gives_nothing(self):
        self.assertEqual(probes.parse_ping("ping: unknown host"), (None, None))

    def test_slow_means_high_latency_or_much_loss(self):
        self.assertFalse(probes.is_slow(40.0, 0.0))
        self.assertTrue(probes.is_slow(probes.LATENCY_HIGH_MS, 0.0))
        self.assertTrue(probes.is_slow(20.0, probes.LOSS_HIGH_PERCENT))
        self.assertFalse(probes.is_slow(None, None))


class WifiLevelTests(unittest.TestCase):
    def test_the_signal_level_is_read_in_dbm(self):
        with mock.patch("builtins.open", mock.mock_open(read_data=WIRELESS)):
            self.assertEqual(probes.wifi_level(), -52)

    def test_without_wifi_there_is_none(self):
        with mock.patch("builtins.open", side_effect=IOError):
            self.assertIsNone(probes.wifi_level())


if __name__ == "__main__":
    unittest.main()
