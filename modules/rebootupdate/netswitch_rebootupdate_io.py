# DreamPi Netswitch add-on - reboot and update module: its jacks, see netswitch_bus.py. Python 2 and 3, only the base and files.
import netswitch_core as core

OUTPUTS = {"addon_update": lambda: bool(core.update_info().get("addon")),
           "dreampi_update": lambda: bool(core.update_info().get("dreampi")),
           "update_running": lambda: core.update_status() == "running",
           "update_failed": lambda: core.update_status() == "failed",
           "rebooting": lambda: core.reboot_pending()}
