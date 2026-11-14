#!/usr/bin/env bash
# EXVS2 matchmaking server - Linux configure (step 2). Writes Configurations/server.json + kestrel.json.
# Usage: ./linux/configure.sh                     (asks questions)
#        ./linux/configure.sh --ip 203.0.113.10 [--http-port 28080] [--stun-port 3478] [--fill 15] [--yes]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
SERVER_DIR="${SERVER_DIR:-$ROOT/server-linux}"
CFG="$SERVER_DIR/Configurations"

IP=""; HTTP_PORT=28080; STUN_PORT=3478; FILL=15; YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --ip) IP="$2"; shift 2 ;;
    --http-port) HTTP_PORT="$2"; shift 2 ;;
    --stun-port) STUN_PORT="$2"; shift 2 ;;
    --fill) FILL="$2"; shift 2 ;;
    --yes|-y) YES=1; shift ;;
    -h|--help) sed -n 2,4p "$0"; exit 0 ;;
    *) echo "Unknown option $1" >&2; exit 1 ;;
  esac
done

[ -f "$CFG/server.json" ] || { echo "ERROR: $CFG/server.json not found. Run ./linux/build-server.sh first." >&2; exit 1; }
command -v python3 >/dev/null || { echo "ERROR: python3 is needed to edit the JSON files (sudo apt install python3)." >&2; exit 1; }

valid_ip() { [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; }

if [ -z "$IP" ]; then
  echo "Which address will the PLAYERS use to reach this server?"
  echo "  - VPS / port forwarding: your PUBLIC IP"
  echo "  - VPN (Tailscale, ZeroTier, Radmin, N2N...): this machine's VPN IP"
  echo "  - Only your home network: this machine's LAN IP"
  echo
  echo "IPv4 addresses on this machine:"
  ip -4 -o addr show 2>/dev/null | awk '$2!="lo"{split($4,a,"/"); printf "    %-15s (%s)\n", a[1], $2}' || true
  pub=""
  if [ "$YES" = 0 ]; then
    read -r -p "Look up this machine's public IP online (api.ipify.org)? [Y/n] " a
    if [[ ! "$a" =~ ^[nN] ]]; then pub="$(curl -fsS --max-time 5 https://api.ipify.org || true)"; fi
    [ -n "$pub" ] && echo "    Public IP: $pub"
  fi
  default="${pub:-$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<NF;i++) if($i=="src") print $(i+1)}')}"
  while :; do
    read -r -p "Server address (IPv4) [$default]: " IP; IP="${IP:-$default}"
    valid_ip "$IP" && break; echo "    That is not an IPv4 address like 203.0.113.10. Try again."
  done
  read -r -p "HTTP port for the card server + matchmaker [$HTTP_PORT]: " a; HTTP_PORT="${a:-$HTTP_PORT}"
fi
valid_ip "$IP" || { echo "ERROR: --ip must be an IPv4 address" >&2; exit 1; }
case "$IP" in 127.*) echo "WARNING: 127.x only works for games on this same machine." ;; esac

cp "$CFG/server.json" "$CFG/server.json.bak"
cp "$CFG/kestrel.json" "$CFG/kestrel.json.bak"
python3 - "$CFG" "$IP" "$HTTP_PORT" "$STUN_PORT" "$FILL" <<'PY'
import json, sys, os
cfg, ip, http_port, stun_port, fill = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), float(sys.argv[5])
def load(p):
    with open(p, encoding="utf-8-sig") as f: return json.load(f)
def save(p, d):
    with open(p, "w", encoding="utf-8") as f: json.dump(d, f, indent=2, ensure_ascii=False); f.write("\n")
sp = os.path.join(cfg, "server.json"); s = load(sp)
c = s.setdefault("CardServerConfig", {})
om = c.setdefault("OnlineMatching", {})
om.update({"Enabled": True, "MatchUrl": "", "StunHost": ip, "StunPort": stun_port, "BuiltinStun": True,
           "FillAfterSeconds": int(fill) if fill.is_integer() else fill, "AllowPartialRooms": True, "CpuStandInSeats": False})
ot = c.setdefault("OnlineTag", {})
for k, v in {"SendTagTeams": True, "TagStatus": 0, "MaxTeams": 20, "OneTimeInviteCode": True}.items(): ot.setdefault(k, v)
save(sp, s)
kp = os.path.join(cfg, "kestrel.json"); k = load(kp)
k.setdefault("Kestrel", {}).setdefault("Endpoints", {}).setdefault("BaseServer", {})["Url"] = f"http://0.0.0.0:{http_port}"
save(kp, k)
PY

cat <<MSG

Saved (old files kept as *.bak):
  Configurations/server.json : OnlineMatching Enabled=true, StunHost=$IP, StunPort=$STUN_PORT (+$((STUN_PORT+1))), BuiltinStun=true, FillAfterSeconds=$FILL
  Configurations/kestrel.json: listen on http://0.0.0.0:$HTTP_PORT

Open these ports (see Public-Server.txt):
  TCP $HTTP_PORT        card server + matchmaker + card website
  UDP $STUN_PORT, $((STUN_PORT+1))  STUN
  e.g. ufw:  sudo ufw allow $HTTP_PORT/tcp && sudo ufw allow $STUN_PORT:$((STUN_PORT+1))/udp
  and in your VPS provider's firewall / security group too.

Players use:  card server address $IP  (see Connect-Your-Game.txt)
Next: ./linux/start-server.sh
MSG
[ "$HTTP_PORT" = 28080 ] || echo "NOTE: the game connects to its card server on port 28080. Use another port only for a matchmaker that players reach through their own local card server (MatchUrl)."
