One file per screen that should show only some buildings. Name it after the screen's MAC address with dashes
and lower case letters, for example 00-1a-2b-3c-4d-5e.ipxe, and copy it to <pxe folder>/www/screens/ (install-pxe.sh
copies this folder's *.ipxe files there). Content, buildings written as on the board's buttons, spaces as +, several
separated by a comma (no space after it):

#!ipxe
set location Omr%C3%A5de+A,Omr%C3%A5de+B

(Letters beyond a-z are percent-encoded: Område is Omr%C3%A5de.) A screen without a file shows everybody.
