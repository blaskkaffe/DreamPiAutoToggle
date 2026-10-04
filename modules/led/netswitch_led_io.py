# DreamPi Netswitch add-on - Status LED module: its jacks, see netswitch_bus.py. Python 2 and 3, only the base.
# "Alert A / B / C" are level inputs: the LED message of the same name is on while the input is on (ledconfig reads them from the
# bus), so nothing has to run here. What an alert looks like is up to the user: put the message in a colour row of Settings > Status LED.
INPUTS = {"alert_a": None, "alert_b": None, "alert_c": None}
