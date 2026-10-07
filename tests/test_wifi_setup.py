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
        st = w.wifi_state()
        self.assertEqual(st["state"], "hosting")
        self.assertEqual(st["networks"][0]["ssid"], "Home")
        w.set_state("idle")
        self.assertEqual(w.wifi_state()["state"], "idle")

    def test_stale_state_counts_as_idle(self):
        with open(w.WIFI_STATE, "w") as f:
            json.dump({"state": "hosting", "time": 1}, f)
        self.assertEqual(w.wifi_state()["state"], "idle")

    def test_start_stop_flags(self):
        self.assertFalse(w.start_requested())
        open(w.WIFI_START, "w").close()
        self.assertTrue(w.start_requested())
        w.clear_flags()
        self.assertFalse(w.start_requested())
        open(w.WIFI_STOP, "w").close()
        self.assertTrue(w.stop_requested())

    def test_ap_page_cannot_be_broken_out_of_by_an_ssid(self):
        evil = '</script><script>alert(1)</script>'
        page = w._ap_page([{"ssid": evil, "signal": -50, "secured": True}]).decode()
        self.assertNotIn(evil, page)
        self.assertEqual(page.count("</script>"), 1)
        self.assertIn("\\u003c/script\\u003e", page)         # still the same name once JSON-decoded


class DemoModeTests(unittest.TestCase):
    """Wi-Fi setup on dummy networks: no hostapd/wpa_supplicant, same states."""
    def setUp(self):
        self.tmp = sandbox(w)
        open(w.WIFI_DEMO, "w").close()
        self.saved = (w.SCAN_WAIT, w.DEMO_CONNECT_SECONDS, w.RESULT_PAUSE, w.run, w.output)
        w.SCAN_WAIT = w.DEMO_CONNECT_SECONDS = w.RESULT_PAUSE = 0

        def no_system(*a, **k):
            raise AssertionError("demo mode must not run system commands: %r" % (a,))
        w.run = w.output = no_system
        self.states = []
        self._set = w.set_state
        w.set_state = lambda state, ssid=None, networks=None: (self.states.append((state, ssid)), self._set(state, ssid, networks))

    def tearDown(self):
        w.SCAN_WAIT, w.DEMO_CONNECT_SECONDS, w.RESULT_PAUSE, w.run, w.output = self.saved
        w.set_state = self._set
        cleanup(self.tmp)

    def cycle(self, ssid, password):
        # the regular page's Connect button writes this file; the cycle picks it up while "hosting"
        with open(w.WIFI_CONNECT, "w") as f:
            json.dump({"ssid": ssid, "password": password}, f)
        w.setup_cycle(w.wifi_iface())
        return [s for s, _ in self.states]

    def test_dummy_networks_are_listed(self):
        nets = w.scan_networks("wlan0")
        self.assertEqual([n["ssid"] for n in nets][:2], ["DreamCast-Home", "Neighbour 5G"])
        self.assertTrue(any(not n["secured"] for n in nets))

    def test_demo_has_an_interface_without_wifi_hardware(self):
        self.assertEqual(w.wifi_iface(), "wlan0")

    def test_right_password_connects(self):
        self.assertEqual(self.cycle("DreamCast-Home", "demo"), ["scanning", "hosting", "connecting", "ok", "idle"])

    def test_open_network_connects_without_a_password(self):
        self.assertEqual(self.cycle("CoffeeShop Free", "")[-2:], ["ok", "idle"])

    def test_wrong_password_shows_failed_then_cancel_ends_it(self):
        base = w.set_state

        def set_state(state, ssid=None, networks=None):
            base(state, ssid, networks)
            if state == "failed":                   # the user cancels while the red state shows
                open(w.WIFI_STOP, "w").close()
        w.set_state = set_state
        self.assertEqual(self.cycle("Old Router", "nope"), ["scanning", "hosting", "connecting", "failed", "scanning", "idle"])   # failed -> rescans -> sees the stop request

    def test_try_connect_results(self):
        self.assertTrue(w.try_connect("wlan0", "DreamCast-Home", "demo"))
        self.assertFalse(w.try_connect("wlan0", "DreamCast-Home", "wrong"))
        self.assertTrue(w.try_connect("wlan0", "CoffeeShop Free", ""))
        self.assertTrue(w.try_connect("wlan0", "Some Hidden Net", "demo"))

    def test_no_wpa_supplicant_conf_is_written(self):
        w.try_connect("wlan0", "DreamCast-Home", "demo")
        self.assertFalse(os.path.exists(w.WPA_CONF) and "DreamCast-Home" in open(w.WPA_CONF).read())


if __name__ == "__main__":
    unittest.main()
