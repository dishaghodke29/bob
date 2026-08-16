#!/bin/bash
# BOB — WireGuard VPN Setup Script
# Run once on the Arduino UNO Q as root.
# Sets up BOB as a VPN server so your phone can connect from anywhere.
#
# Usage: sudo bash /home/arduino/bob/setup_vpn.sh
#
# After running this script:
#   1. Scan the QR code on screen with your phone's WireGuard app
#   2. Enable the VPN on your phone
#   3. Open http://10.8.0.1:8000 in your phone's browser
#   4. Install as app: browser menu → "Add to Home Screen"

set -e

VPN_PORT=51820
VPN_SUBNET="10.8.0"
SERVER_IP="${VPN_SUBNET}.1"
CLIENT_IP="${VPN_SUBNET}.2"
WG_IFACE="wg0"
WG_DIR="/etc/wireguard"
KEY_DIR="/home/arduino/bob/vpn_keys"

echo ""
echo "======================================"
echo "  BOB WireGuard VPN Setup"
echo "======================================"
echo ""

# ── 1. Generate keys ──────────────────────────────────────────────────────────
mkdir -p "$KEY_DIR"
chmod 700 "$KEY_DIR"

echo "[1/5] Generating cryptographic keys..."
SERVER_PRIV=$(wg genkey)
SERVER_PUB=$(echo "$SERVER_PRIV" | wg pubkey)
CLIENT_PRIV=$(wg genkey)
CLIENT_PUB=$(echo "$CLIENT_PRIV" | wg pubkey)

# Save server keys
echo "$SERVER_PRIV" > "$KEY_DIR/server.priv"
echo "$SERVER_PUB"  > "$KEY_DIR/server.pub"
echo "$CLIENT_PRIV" > "$KEY_DIR/client.priv"
echo "$CLIENT_PUB"  > "$KEY_DIR/client.pub"
chmod 600 "$KEY_DIR"/*

# ── 2. Get public IP ──────────────────────────────────────────────────────────
echo "[2/5] Detecting public IP..."
PUBLIC_IP=$(curl -s --max-time 5 https://api.ipify.org || echo "YOUR_PUBLIC_IP")
echo "      Public IP: $PUBLIC_IP"
echo "      (Update this in /etc/wireguard/wg0.conf if it changes)"

# Save public IP
echo "$PUBLIC_IP" > "$KEY_DIR/public_ip.txt"

# ── 3. Server config ──────────────────────────────────────────────────────────
echo "[3/5] Creating server config..."

# Get the main network interface
MAIN_IF=$(ip route | grep '^default' | awk '{print $5}' | head -1)

cat > "${WG_DIR}/${WG_IFACE}.conf" << CONF
[Interface]
PrivateKey = ${SERVER_PRIV}
Address    = ${SERVER_IP}/24
ListenPort = ${VPN_PORT}
SaveConfig = false

# Enable IP forwarding + NAT so phone can reach BOB's services
PostUp   = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -o ${MAIN_IF} -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -o ${MAIN_IF} -j MASQUERADE

[Peer]
# Your phone
PublicKey  = ${CLIENT_PUB}
AllowedIPs = ${CLIENT_IP}/32
CONF

chmod 600 "${WG_DIR}/${WG_IFACE}.conf"

# ── 4. Client config (for phone) ─────────────────────────────────────────────
echo "[4/5] Creating phone config..."

CLIENT_CONF="${KEY_DIR}/bob_phone.conf"
cat > "$CLIENT_CONF" << CONF
[Interface]
PrivateKey = ${CLIENT_PRIV}
Address    = ${CLIENT_IP}/24
DNS        = 1.1.1.1

[Peer]
# BOB Robot (Arduino UNO Q)
PublicKey  = ${SERVER_PUB}
Endpoint   = ${PUBLIC_IP}:${VPN_PORT}
AllowedIPs = ${SERVER_IP}/32
PersistentKeepalive = 25
CONF

chmod 600 "$CLIENT_CONF"

# ── 5. Enable IP forwarding ───────────────────────────────────────────────────
echo "[5/5] Enabling IP forwarding and starting WireGuard..."

# Enable IP forwarding persistently
grep -qxF 'net.ipv4.ip_forward=1' /etc/sysctl.conf \
  || echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf
sysctl -p -q

# Open firewall port
iptables -I INPUT -p udp --dport $VPN_PORT -j ACCEPT 2>/dev/null || true

# Enable + start WireGuard
systemctl enable  "wg-quick@${WG_IFACE}"
systemctl start   "wg-quick@${WG_IFACE}" || wg-quick up "$WG_IFACE"

# ── Show QR code for phone setup ─────────────────────────────────────────────
echo ""
echo "======================================"
echo "  ✅ WireGuard VPN is running!"
echo "======================================"
echo ""
echo "  Scan this QR code with the WireGuard app on your phone:"
echo "  (Install 'WireGuard' from Play Store / App Store — free)"
echo ""

# Generate QR if qrencode is available
if command -v qrencode &>/dev/null; then
    qrencode -t ansiutf8 < "$CLIENT_CONF"
else
    apt-get install -y qrencode -qq 2>/dev/null && qrencode -t ansiutf8 < "$CLIENT_CONF"
fi

echo ""
echo "  Or manually import the config file:"
echo "  $CLIENT_CONF"
echo ""
echo "  After connecting on your phone, open:"
echo "  http://${SERVER_IP}:8000"
echo ""
echo "  To add as app: browser menu → 'Add to Home Screen'"
echo ""
echo "  ⚠️  Port forward UDP $VPN_PORT on your router to ${SERVER_IP}"
echo "      (so you can connect from outside your home WiFi)"
echo ""

# ── DuckDNS setup hint ────────────────────────────────────────────────────────
echo "  💡 If your home IP changes (dynamic IP):"
echo "     Get a free hostname at https://duckdns.org"
echo "     Then update the Endpoint in your phone's WireGuard config."
echo ""

wg show
