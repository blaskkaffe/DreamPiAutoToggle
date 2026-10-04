# DreamPi Netswitch add-on - online players module: its jacks, see netswitch_bus.py. Python 2 and 3, only the base and files.
import netswitch_core as core

OUTPUTS = {"game_played": lambda: bool(core.players_watch()["games"]),
           "friend_online": lambda: bool(core.players_watch()["friends"])}
