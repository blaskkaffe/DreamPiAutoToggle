"""Wi-Fi setup helpers that need no radio: scan parsing, wpa_supplicant.conf
rewriting, state file, the setup page (hostapd/dnsmasq/wpa_cli are faked)."""
import json
import os
import unittest

from support import core, sandbox, cleanup
import netswitch_wifi_setup as w

SCAN = ("bssid / frequency / signal level / flags / ssid\n"
        "aa:aa\t2412\t-70\t[WPA2-PSK-CCMP][ESS]\tHome\n"
        "bb:bb\t2437\t-50\t[WPA2-PSK-CCMP][ESS]\tHome\n"       # same SSID, stronger
        "cc:cc\t2462\t-60\t[ESS]\tCafe\n"
        "dd:dd\t2462\t-40\t[WPA2-PSK-CCMP][ESS]\t\n"            # hidden: skipped
        "garbage\n")


class WifiSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox(w)
        w.WPA_CONF = os.path.join(self.tmp, "wpa_supplicant.conf")
        self._run, self._out, self._wait = w.run, w.output, w.wait_or_stop
        w.run = lambda cmd, timeout=15: None
        w.wait_or_stop = lambda s: False

    def tearDown(self):
        w.run, w.output, w.wait_or_stop = self._run, self._out, self._wait
        cleanup(self.tmp)

    def wpa(self):
        with open(w.WPA_CONF) as f:
            return f.read()

    def test_scan_dedups_by_ssid_and_sorts_by_signal(self):
        w.output = lambda cmd, timeout=10: SCAN
        nets = w.scan_networks("wlan0")
        self.assertEqual([(n["ssid"], n["signal"], n["secured"]) for n in nets],
                         [("Home", -50, True), ("Cafe", -60, False)])

    def test_scan_failure_is_an_empty_list(self):
        w.output = lambda cmd, timeout=10: None
        self.assertEqual(w.scan_networks("wlan0"), [])

    def test_open_network_block(self):
        self.assertIn("key_mgmt=NONE", w._network_block("Cafe", ""))

    def test_passphrase_block_drops_plaintext_comment(self):
        w.output = lambda cmd, timeout=10: 'network={\n\tssid="Home"\n\t#psk="secret"\n\tpsk=abc123\n}\n'
        block = w._network_block("Home", "secret")
        self.assertNotIn("secret", block)
        self.assertIn("psk=abc123", block)

    def test_save_network_replaces_same_ssid_and_keeps_others(self):
        w.output = lambda cmd, timeout=10: None          # plain-text psk fallback
        w.save_network("Home", "one")
        w.save_network("Other", "two")
        w.save_network("Home", "three")
        text = self.wpa()
        self.assertEqual(text.count('ssid="Home"'), 1)
        self.assertEqual(text.count('ssid="Other"'), 1)
        self.assertIn('psk="three"', text)
        self.assertNotIn('psk="one"', text)
        self.assertTrue(text.startswith("ctrl_interface="))

    def test_quotes_in_ssid_are_escaped(self):
        w.output = lambda cmd, timeout=10: None
        w.save_network('My "Net"', "pw")
        self.assertIn('ssid="My \\"Net\\""', self.wpa())

    def test_state_file_round_trip_through_core(self):
        w.set_state("hosting", ssid="DreamPi WiFi Config", networks=[{"ssid": "Home", "signal": -50, "secured": True}])
        st = core.wifi_state()
        self.assertEqual(st["state"], "hosting")
        self.assertEqual(st["networks"][0]["ssid"], "Home")
        w.set_state("idle")
        self.assertEqual(core.wifi_state()["state"], "idle")

    def test_stale_state_counts_as_idle(self):
        with open(core.WIFI_STATE, "w") as f:
            json.dump({"state": "hosting", "time": 1}, f)
        self.assertEqual(core.wifi_state()["state"], "idle")

    def test_start_stop_flags(self):
        self.assertFalse(w.start_requested())
        open(core.WIFI_START, "w").close()
        self.assertTrue(w.start_requested())
        w.clear_flags()
        self.assertFalse(w.start_requested())
        open(core.WIFI_STOP, "w").close()
        self.assertTrue(w.stop_requested())

    def test_ap_page_cannot_be_broken_out_of_by_an_ssid(self):
        evil = '</script><script>alert(1)</script>'
        page = w._ap_page([{"ssid": evil, "signal": -50, "secured": True}]).decode()
        self.assertNotIn(evil, page)
        self.assertEqual(page.count("</script>"), 1)
        self.assertIn("\\u003c/script\\u003e", page)         # still the same name once JSON-decoded


if __name__ == "__main__":
    unittest.main()
