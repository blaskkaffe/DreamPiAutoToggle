#!/bin/sh
# Check-in add-on - network check. Changes nothing; prints what the computer's network looks like, to find out why screens lose contact with the host.
# Run it on the host and on a screen WHILE it is not working, and send both outputs:
#   sudo /opt/checkin-board/diagnose-network.sh [host-address-for-the-screen-to-test]
# On a screen give the host's address:  ./diagnose-network.sh 192.168.1.20
HOST="$1"
sec() { printf '\n===== %s =====\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }
sec "time, kernel"; date; uname -r; uptime
sec "sleep / suspend (a sleeping host does not answer ping until somebody uses it)"
have systemctl && for t in sleep suspend hibernate; do echo "$t.target: $(systemctl is-enabled $t.target 2>/dev/null)"; done
have journalctl && journalctl -b --no-pager 2>/dev/null | grep -iE "PM: suspend|Suspending system|System is suspend|Lid closed|Reached target.*sleep|idle.*suspend|powering off|PM: resume" | tail -15
ls /etc/systemd/logind.conf.d/ 2>/dev/null
sec "interfaces (state, addresses)"; if have ip; then ip -br addr; elif have ifconfig; then ifconfig -a; fi
sec "routes"; have ip && ip route
sec "link details (errors, drops)"; have ip && ip -s link | head -60
sec "neighbours (ARP: who this computer has seen on the LAN)"; have ip && ip neigh | head -40
sec "link speed / duplex"; have ethtool && for d in /sys/class/net/*; do n=$(basename "$d"); [ -e "$d/device" ] && ethtool "$n" 2>/dev/null | grep -E "Speed|Duplex|Link detected"; done
sec "is another computer using this computer's address? (needs arping: apt install iputils-arping)"
if have arping && have ip; then
  for n in $(ip -4 -o addr show scope global | awk '{print $2}' | sort -u); do a=$(ip -4 -o addr show dev "$n" scope global | awk '{print $4; exit}' | cut -d/ -f1)
    [ -n "$a" ] && { echo "$n $a:"; arping -D -c 2 -w 3 -I "$n" "$a" 2>&1 | tail -2; echo "(a reply from another MAC address means two computers have this address)"; }; done
else echo "(arping is not installed)"; fi
sec "names"; hostname; have avahi-daemon && (systemctl is-active avahi-daemon 2>/dev/null); have getent && getent hosts "$(hostname).local" 2>/dev/null
sec "services"
for s in checkin-board checkin-board-pxe checkin-board-pxe-http avahi-daemon NetworkManager systemd-networkd dhcpcd; do
  st=$(systemctl is-active "$s" 2>/dev/null); case "$st" in ""|inactive|unknown) ;; *) echo "$s: $st" ;; esac; done
sec "listening ports (80/443 the board, 67/69/4011/8069 network boot)"; have ss && ss -lntu | grep -E ":(80|443|67|69|4011|8069|5353)\b"
sec "firewall"; have ufw && ufw status 2>/dev/null | head -20; have nft && nft list ruleset 2>/dev/null | head -40
sec "what the network did while the board was running (the service logs a line at every change)"; have journalctl && journalctl -u checkin-board --no-pager 2>/dev/null | grep -E "network:|restarting the service|failed" | tail -40
sec "kernel messages about the network card or link"; have journalctl && journalctl -k --no-pager 2>/dev/null | grep -iE "link is|link down|NETDEV WATCHDOG|reset|firmware|hang|timeout|r8169|e1000|iwl|brcm|rtl|ath" | tail -30
sec "reaching things"
GW=$(ip -4 route show default 2>/dev/null | awk '{print $3; exit}')
[ -z "$GW" ] || { echo "router $GW:"; ping -c 3 -W 2 "$GW" 2>&1 | tail -3; }
if [ -n "$HOST" ]; then
  echo "the host $HOST:"; ping -c 3 -W 2 "$HOST" 2>&1 | tail -3
  have curl && curl -sS -m 5 -o /dev/null -w "board /ping over http: %{http_code} in %{time_total}s\n" "http://$HOST/ping" 2>&1
fi
sec "done"
