"""DCNow! is the selected network after every reboot (core.reset_network_after_boot, keyed on the kernel's boot id)."""
import os
import unittest

from support import core, sandbox, cleanup


class BootResetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()
        self.kernel = os.path.join(self.tmp, "kernel_boot_id")
        self.saved = core.KERNEL_BOOT_ID
        core.KERNEL_BOOT_ID = self.kernel
        os.makedirs(core.BASE_DIR, exist_ok=True)

    def tearDown(self):
        core.KERNEL_BOOT_ID = self.saved
        cleanup(self.tmp)

    def boot(self, ident):
        with open(self.kernel, "w") as f:
            f.write(ident + "\n")

    def test_a_new_boot_selects_dcnow(self):
        self.boot("boot-1")
        core.reset_network_after_boot()
        open(core.FLAG, "w").close()                       # DCNET picked during this boot
        self.assertFalse(core.reset_network_after_boot())  # a service restart: nothing changes
        self.assertTrue(os.path.exists(core.FLAG))
        self.boot("boot-2")                                 # reboot
        self.assertTrue(core.reset_network_after_boot())
        self.assertFalse(os.path.exists(core.FLAG))
        self.assertFalse(core.reset_network_after_boot())   # the second service to start finds it done

    def test_the_first_run_after_an_install_keeps_the_selection(self):
        self.boot("boot-1")
        open(core.FLAG, "w").close()
        self.assertFalse(core.reset_network_after_boot())
        self.assertTrue(os.path.exists(core.FLAG))
        self.assertEqual(core.read_file(core.BOOT_ID), "boot-1")

    def test_no_boot_id_changes_nothing(self):
        open(core.FLAG, "w").close()
        self.assertFalse(core.reset_network_after_boot())
        self.assertTrue(os.path.exists(core.FLAG))


if __name__ == "__main__":
    unittest.main()
