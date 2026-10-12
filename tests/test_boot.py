"""DCNow! is the selected network after every reboot (sw.reset_network_after_boot, keyed on the kernel's boot id)."""
import os
import unittest

from support import core, sandbox, cleanup
import netswitch_switcher_state as sw  # noqa: E402


class BootResetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        self.kernel = os.path.join(self.tmp, "kernel_boot_id")
        self.saved = sw.KERNEL_BOOT_ID
        sw.KERNEL_BOOT_ID = self.kernel
        os.makedirs(core.BASE_DIR, exist_ok=True)

    def tearDown(self):
        sw.KERNEL_BOOT_ID = self.saved
        cleanup(self.tmp)

    def boot(self, ident):
        with open(self.kernel, "w") as f:
            f.write(ident + "\n")

    def test_a_new_boot_selects_dcnow(self):
        self.boot("boot-1")
        sw.reset_network_after_boot()
        open(sw.FLAG, "w").close()                       # DCNET picked during this boot
        self.assertFalse(sw.reset_network_after_boot())  # a service restart: nothing changes
        self.assertTrue(os.path.exists(sw.FLAG))
        self.boot("boot-2")                                 # reboot
        self.assertTrue(sw.reset_network_after_boot())
        self.assertFalse(os.path.exists(sw.FLAG))
        self.assertFalse(sw.reset_network_after_boot())   # the second service to start finds it done

    def test_the_first_run_after_an_install_keeps_the_selection(self):
        self.boot("boot-1")
        open(sw.FLAG, "w").close()
        self.assertFalse(sw.reset_network_after_boot())
        self.assertTrue(os.path.exists(sw.FLAG))
        self.assertEqual(core.read_file(sw.BOOT_ID), "boot-1")

    def test_no_boot_id_changes_nothing(self):
        open(sw.FLAG, "w").close()
        self.assertFalse(sw.reset_network_after_boot())
        self.assertTrue(os.path.exists(sw.FLAG))


if __name__ == "__main__":
    unittest.main()
