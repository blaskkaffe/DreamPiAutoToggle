#!/bin/bash
# Network test in throwaway namespaces (needs root, iproute2, iptables,
# dnsmasq, udhcpc or busybox, curl, nc, python3):
#
#   [dc]  dc0 ---- dcnet0 [pi] pi-wan ---- inet0 [inet]  203.0.113.10 "game server"
#
# Checks: DHCP from dnsmasq with our generated config, DNS redirect (stands in
# for DreamPi's dreamcast.online entries), outbound NAT, an inbound port
# forward, idempotent re-runs and clean removal.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
NET="$HERE/../../modules/dcbridge/system/dcbridge-net"
T=$(mktemp -d)
PASS=0; FAIL=0
ok()   { echo "  ok   $*"; PASS=$((PASS+1)); }
bad()  { echo "  FAIL $*"; FAIL=$((FAIL+1)); }
cleanup() {
    for p in "$T"/*.pid; do [ -f "$p" ] && kill "$(cat "$p")" 2>/dev/null; done
    for n in dcb_dc dcb_pi dcb_inet; do ip netns pids $n 2>/dev/null | xargs -r kill 2>/dev/null; done
    for n in dcb_dc dcb_pi dcb_inet; do ip netns del $n 2>/dev/null; done
    rm -rf "$T"
}
trap cleanup EXIT

for n in dcb_dc dcb_pi dcb_inet; do ip netns add $n; ip -n $n link set lo up; done
ip link add pi-wan netns dcb_pi type veth peer name inet0 netns dcb_inet
ip link add dcnet0 netns dcb_pi type veth peer name dc0 netns dcb_dc
ip -n dcb_inet addr add 198.51.100.1/24 dev inet0; ip -n dcb_inet link set inet0 up
ip -n dcb_inet addr add 203.0.113.10/32 dev lo
ip -n dcb_pi addr add 198.51.100.2/24 dev pi-wan; ip -n dcb_pi link set pi-wan up
ip -n dcb_pi route add default via 198.51.100.1
ip -n dcb_dc link set dc0 up

cat > "$T/conf" <<EOF
DCNET_IF=dcnet0
DCNET_ADDR=192.168.170.1
FORWARD_PORTS="tcp:2048:dcnet"
EOF
export DCBRIDGE_CONF="$T/conf" DNSMASQ_CONF="$T/dnsmasq.d/dcbridge.conf" DCBRIDGE_RUN="$T/run"
PI="ip netns exec dcb_pi"

$PI "$NET" dnsmasq-conf 2>/dev/null
$PI "$NET" dcnet-up 2>/dev/null
$PI "$NET" firewall-up 2>/dev/null            # second run must not duplicate rules
n1=$($PI iptables-save | grep -c -- '-A DCB-')
$PI "$NET" firewall-up 2>/dev/null
n2=$($PI iptables-save | grep -c -- '-A DCB-')
[ "$n1" = "$n2" ] && ok "firewall-up is idempotent ($n1 rules)" || bad "rules grew $n1 -> $n2"
[ "$($PI iptables -S POSTROUTING -t nat | grep -c DCB-POST)" = 1 ] && ok "single hook in POSTROUTING" || bad "hooks"

sed -i "s#dhcp-leasefile=.*#dhcp-leasefile=$T/leases#" "$DNSMASQ_CONF"
# Another (old) Dreamcast MAC still holds .2, so ours gets a different address:
# the port forward must follow it via the dhcp-script hook.
echo "$(( $(date +%s) + 3600 )) 02:00:00:00:00:99 192.168.170.2 olddc *" > "$T/leases"
dnsmasq --test -C "$DNSMASQ_CONF" >/dev/null 2>&1 && ok "generated dnsmasq config parses" || bad "dnsmasq --test"
$PI dnsmasq -C "$DNSMASQ_CONF" --pid-file="$T/dnsmasq.pid" --no-resolv --no-hosts \
    --address=/sega.example/203.0.113.10 --log-facility="$T/dnsmasq.log"

# The Dreamcast side: get an address by DHCP
cat > "$T/udhcpc.sh" <<'EOF'
#!/bin/sh
[ "$1" = bound ] || exit 0
ip addr add "$ip/${mask:-24}" dev "$interface"
ip route add default via "$router"
echo "$ip $router $dns" > "$LEASEOUT"
EOF
chmod +x "$T/udhcpc.sh"
UDHCPC=$(command -v udhcpc || echo "busybox udhcpc")
LEASEOUT="$T/lease" ip netns exec dcb_dc $UDHCPC -i dc0 -n -q -t 5 -s "$T/udhcpc.sh" >/dev/null 2>&1
read -r dcip router dns < "$T/lease" 2>/dev/null || true
case "${dcip:-}" in 192.168.170.[3-9]) dc_ok=1 ;; *) dc_ok=0 ;; esac
[ $dc_ok = 1 ] && [ "${router:-}" = 192.168.170.1 ] && [ "${dns:-}" = 192.168.170.1 ] \
    && ok "DHCP: Dreamcast got $dcip, gateway $router, DNS $dns" || bad "DHCP lease '${dcip:-} ${router:-} ${dns:-}'"
sleep 0.5
[ "$(cat "$T/run/dcnet-ip" 2>/dev/null)" = "${dcip:-x}" ] && ok "lease hook recorded the Dreamcast address" || bad "lease hook"


ans=$(ip netns exec dcb_dc python3 - <<'EOF'
import socket, struct
q = struct.pack(">HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0) + b"\x04sega\x07example\x00" + struct.pack(">HH", 1, 1)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.settimeout(3)
s.sendto(q, ("192.168.170.1", 53)); r = s.recv(512)
print(socket.inet_ntoa(r[-4:]))
EOF
)
[ "$ans" = 203.0.113.10 ] && ok "DNS via the Pi resolves redirected names" || bad "DNS answer '$ans'"

# Outbound NAT: the game server must see the Pi's WAN address
ip netns exec dcb_inet python3 -c "
import http.server
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        b = self.client_address[0].encode(); self.send_response(200); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a): pass
http.server.HTTPServer(('203.0.113.10', 8000), H).serve_forever()" >/dev/null 2>&1 &
echo $! > "$T/http.pid"; sleep 0.5
seen=$(ip netns exec dcb_dc curl -s -m 3 http://203.0.113.10:8000/)
[ "$seen" = 198.51.100.2 ] && ok "outbound NAT (server sees $seen)" || bad "server saw '$seen'"

# Inbound forward tcp:2048 -> Dreamcast
ip netns exec dcb_dc sh -c "echo hello-from-dc | nc -l -p 2048 -q 1 2>/dev/null || echo hello-from-dc | nc -l 2048" >/dev/null 2>&1 &
echo $! > "$T/nc.pid"; sleep 0.5
got=$(ip netns exec dcb_inet nc -w 2 198.51.100.2 2048 </dev/null 2>/dev/null)
[ "$got" = hello-from-dc ] && ok "inbound port forward reaches the Dreamcast" || bad "forward got '$got'"

# Removal
$PI "$NET" firewall-down 2>/dev/null
[ "$($PI iptables-save | grep -c DCB-)" = 0 ] && ok "firewall-down removes every rule and chain" || bad "leftovers"
seen=$(ip netns exec dcb_dc curl -s -m 2 http://203.0.113.10:8000/)
[ -z "$seen" ] && ok "no NAT after firewall-down" || bad "still NATed"

echo "$PASS passed, $FAIL failed"
[ "$FAIL" = 0 ]
