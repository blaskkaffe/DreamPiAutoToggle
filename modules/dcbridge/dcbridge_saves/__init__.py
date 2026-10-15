"""dcbridge-saves: the Raspberry Pi side of the dcbridge virtual SD card.

* serves the SD card image to the RP2040 over /dev/dcbridge-disk,
* keeps a timestamped history of every openMenu serial-VMU save,
* lets you download, upload, relabel and restore saves (web page, JSON API, CLI).

Written for Python 3.5+ (DreamPi images ship old Raspbian), standard library
only. Needs the `mtools` and `dosfstools` packages.
"""
__version__ = "0.2.0"

SAVES_DIR = "/OPENMENU/SAVES"
LASTDISC = "/OPENMENU/LASTDISC.TXT"
VMU_SIZE = 131072           # openMenu SLOTn.VMU: raw 128 KB VMU image
NUM_SLOTS = 5
