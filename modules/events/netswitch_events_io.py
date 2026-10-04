# DreamPi Netswitch add-on - DC99 events module: its jacks, see netswitch_bus.py. Python 2 and 3, only the base and files.
import netswitch_core as core

OUTPUTS = {"reminder_due": lambda: core.event_reminder() is not None}
