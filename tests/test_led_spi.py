"""GPIO10 needs SPI: the LED service switches it on in config.txt when that pin is chosen and off again when it is left,
but only ever removes the line it added itself."""
import os
import unittest

from support import core, sandbox, cleanup, ledconfig
import netswitch_led as led
import netswitch_led_spi as spi


class SpiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        os.makedirs(core.BASE_DIR, exist_ok=True)
        self.config = os.path.join(self.tmp, "config.txt")
        self.saved = (spi.CONFIG_CANDIDATES, spi.SPI_DEVICE, spi._run)
        spi.CONFIG_CANDIDATES = [os.path.join(self.tmp, "missing.txt"), self.config]
        spi.SPI_DEVICE = os.path.join(self.tmp, "spidev0.0")          # does not exist: SPI is not up yet
        self.ran = []
        spi._run = lambda *cmd: self.ran.append(cmd) or True

    def tearDown(self):
        spi.CONFIG_CANDIDATES, spi.SPI_DEVICE, spi._run = self.saved
        led._spi_tried.clear()
        cleanup(self.tmp)

    def write(self, text):
        with open(self.config, "w") as f:
            f.write(text)

    def read(self):
        with open(self.config) as f:
            return f.read()

    def test_choosing_gpio10_turns_spi_on_and_leaving_it_turns_it_off(self):
        self.write("arm_64bit=1\ndtparam=audio=on")
        said = spi.ensure_spi(True)
        self.assertIn("switched on", said)
        self.assertIn("reboot", said)                                   # the device didn't appear: it applies after a reboot
        self.assertIn("dtparam=spi=on  # added by dreampi-netswitch\n", self.read())
        self.assertTrue(self.read().startswith("arm_64bit=1\ndtparam=audio=on\n"))
        self.assertEqual(core.read_file(spi.SPI_ADDED), self.config)
        self.assertIn(("dtparam", "spi=on"), self.ran)                  # and the running system was asked right away
        spi.ensure_spi(True)                                            # again: nothing is added twice
        self.assertEqual(self.read().count("dtparam=spi=on"), 1)
        self.assertIn("taken out", spi.ensure_spi(False))
        self.assertNotIn("spi=on", self.read())
        self.assertTrue(self.read().startswith("arm_64bit=1\ndtparam=audio=on"))
        self.assertFalse(os.path.exists(spi.SPI_ADDED))

    def test_an_spi_setting_the_user_made_is_left_alone(self):
        self.write("dtparam=spi=on\n")
        self.assertEqual(spi.ensure_spi(True), "")
        self.assertFalse(os.path.exists(spi.SPI_ADDED))
        self.assertEqual(spi.ensure_spi(False), "")
        self.assertEqual(self.read(), "dtparam=spi=on\n")

    def test_nothing_to_undo_when_the_addon_never_added_it(self):
        self.write("arm_64bit=1\n")
        self.assertEqual(spi.ensure_spi(False), "")
        self.assertEqual(self.read(), "arm_64bit=1\n")

    def test_no_config_txt(self):
        os.remove(self.config) if os.path.exists(self.config) else None
        self.assertIn("not found", spi.ensure_spi(True))

    def test_sync_follows_the_pin_setting(self):
        self.write("")
        with open(ledconfig.LED_GPIO, "w") as f:
            f.write("10")
        self.assertIn("switched on", spi.sync())
        with open(ledconfig.LED_GPIO, "w") as f:
            f.write("18")
        self.assertIn("taken out", spi.sync())

    def test_the_service_sets_spi_up_when_the_pin_changes_and_not_four_times_a_second(self):
        self.write("")
        old = led.drivers.open_output
        opened = []

        def fake_open(count, gpio):
            opened.append(gpio)
            if gpio == 10:
                raise OSError("no /dev/spidev0.0")        # not up yet
            return type("Out", (), {"show": lambda s, p: None, "close": lambda s: None})()
        led.drivers.open_output = fake_open
        try:
            out, count, gpio, switched = led.switch_output(None, 1, 18, 1, 10)
            self.assertFalse(switched)                    # stays on the old pin until SPI works
            self.assertIn("spi=on", self.read())
            led.switch_output(None, 1, 18, 1, 10)
            self.assertEqual(self.read().count("dtparam=spi=on"), 1)
            self.assertEqual(sum(1 for c in self.ran if c == ("dtparam", "spi=on")), 1)   # throttled
        finally:
            led.drivers.open_output = old


if __name__ == "__main__":
    unittest.main()
