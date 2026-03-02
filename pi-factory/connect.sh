#!/bin/bash
# =============================================================================
#  PI FACTORY — CHARLIE-side Connect Script
#  Finds the Pi on the network and SSHes in.
#
#  Usage:
#    bash pi-factory/connect.sh          # Auto-discover and SSH
#    bash pi-factory/connect.sh --setup  # SSH + set static IP + install
#
#  Run from CHARLIE (192.168.1.12) after Phase 0 (re-image).
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

PI_USER="pi"
PI_PASS="factorylm"
PI_HOSTNAME="pi-factory"
PI_STATIC_IP="192.168.1.30"
IFACE="en0"

ok()   { echo -e "  ${GREEN}+${NC} $1"; }
warn() { echo -e "  ${YELLOW}!${NC} $1"; }
fail() { echo -e "  ${RED}x${NC} $1"; exit 1; }

echo ""
echo -e "${CYAN}${BOLD}  Pi Factory — Connect from CHARLIE${NC}"
echo ""

# ── Step 1: Try mDNS ─────────────────────────────────────────────────────────
echo -e "${BOLD}Step 1: Trying mDNS (${PI_HOSTNAME}.local)...${NC}"

PI_IP=""
if ping -c 1 -W 2 "${PI_HOSTNAME}.local" > /dev/null 2>&1; then
    PI_IP=$(ping -c 1 -W 2 "${PI_HOSTNAME}.local" 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    ok "mDNS resolved: ${PI_HOSTNAME}.local -> ${PI_IP}"
fi

# ── Step 2: Try static IP ────────────────────────────────────────────────────
if [[ -z "$PI_IP" ]]; then
    echo -e "${BOLD}Step 2: Trying static IP (${PI_STATIC_IP})...${NC}"
    if ping -c 1 -W 2 "${PI_STATIC_IP}" > /dev/null 2>&1; then
        PI_IP="${PI_STATIC_IP}"
        ok "Pi responding at ${PI_STATIC_IP}"
    fi
fi

# ── Step 3: Try IPv6 link-local ──────────────────────────────────────────────
if [[ -z "$PI_IP" ]]; then
    echo -e "${BOLD}Step 3: Scanning IPv6 link-local on ${IFACE}...${NC}"

    # Ping all-nodes multicast to populate neighbor table
    ping6 -c 3 -I "${IFACE}" ff02::1 > /dev/null 2>&1 || true
    sleep 1

    # Look for link-local neighbors that aren't us
    MY_MAC=$(ifconfig "${IFACE}" | grep ether | awk '{print $2}')
    NEIGHBORS=$(ndp -an 2>/dev/null | grep "${IFACE}" | grep -v "${MY_MAC}" | awk '{print $1}' | grep '^fe80' || true)

    if [[ -n "$NEIGHBORS" ]]; then
        for ADDR in $NEIGHBORS; do
            TARGET="${ADDR}%${IFACE}"
            echo "  Trying SSH to ${TARGET}..."
            if ssh -o ConnectTimeout=3 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
                "${PI_USER}@${TARGET}" "echo ok" 2>/dev/null; then
                PI_IP="${TARGET}"
                ok "Found Pi at ${PI_IP} (IPv6 link-local)"
                break
            fi
        done
    fi
fi

# ── Step 4: ARP scan fallback ────────────────────────────────────────────────
if [[ -z "$PI_IP" ]]; then
    echo -e "${BOLD}Step 4: ARP scan on local subnet...${NC}"
    # Scan 169.254.x.x link-local range (direct cable, no DHCP)
    for OCTET3 in $(seq 0 5); do
        for OCTET4 in $(seq 1 254); do
            IP="169.254.${OCTET3}.${OCTET4}"
            if ping -c 1 -W 1 "$IP" > /dev/null 2>&1; then
                if ssh -o ConnectTimeout=2 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
                    "${PI_USER}@${IP}" "echo ok" 2>/dev/null; then
                    PI_IP="$IP"
                    ok "Found Pi at ${PI_IP} (link-local)"
                    break 2
                fi
            fi
        done
    done
fi

# ── Result ────────────────────────────────────────────────────────────────────
if [[ -z "$PI_IP" ]]; then
    echo ""
    fail "Could not find Pi. Check:
    - Pi is powered on (solid red LED)
    - Ethernet cable connected to CHARLIE's en0
    - SD card was imaged with Raspberry Pi Imager (SSH enabled)
    - Wait ~2 minutes after power on"
fi

echo ""
echo -e "${GREEN}${BOLD}  Found Pi at: ${PI_IP}${NC}"
echo ""

# ── --setup mode: set static IP then run full install ─────────────────────────
if [[ "${1:-}" == "--setup" ]]; then
    echo -e "${BOLD}Running Phase 1 setup (static IP + OS update + install)...${NC}"
    echo ""

    # Build the remote setup commands
    REMOTE_CMDS=$(cat << 'SETUP_EOF'
set -e
echo "=== Setting static IP 192.168.1.30 ==="
sudo nmcli con add con-name "plc-subnet" type ethernet ifname eth0 \
  ipv4.method manual \
  ipv4.addresses 192.168.1.30/24 \
  ipv4.gateway 192.168.1.1 \
  ipv4.dns "8.8.8.8" 2>/dev/null || \
sudo nmcli con mod "plc-subnet" \
  ipv4.method manual \
  ipv4.addresses 192.168.1.30/24 \
  ipv4.gateway 192.168.1.1 \
  ipv4.dns "8.8.8.8"
sudo nmcli con up "plc-subnet"
echo "Static IP set. Pi will be at 192.168.1.30 after reconnect."
echo ""
echo "=== Updating OS ==="
sudo apt update -qq && sudo apt upgrade -y -qq
echo ""
echo "=== Installing git ==="
sudo apt install -y -qq git
echo ""
echo "=== Cloning Pi Factory ==="
git clone https://github.com/Mikecranesync/factorylm-cosmos-cookoff.git ~/factorylm 2>/dev/null || \
  (cd ~/factorylm && git pull)
echo ""
echo "=== Running setup.sh ==="
sudo bash ~/factorylm/pi-factory/setup.sh
echo ""
echo "=== Installing pylogix ==="
/opt/factorylm/venv/bin/pip install pylogix -q
echo ""
echo "=== Installing Tailscale ==="
curl -fsSL https://tailscale.com/install.sh | sh
echo "Run 'sudo tailscale up' with your auth key to join the tailnet."
SETUP_EOF
)

    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        "${PI_USER}@${PI_IP}" "$REMOTE_CMDS"

    echo ""
    echo -e "${GREEN}${BOLD}  Setup complete!${NC}"
    echo "  Pi is now at 192.168.1.30"
    echo "  Move Ethernet cables (Phase 2), then:"
    echo "    ssh pi@192.168.1.30"
    echo "    sudo tailscale up"
    echo ""
else
    # Just SSH in
    echo "Connecting via SSH..."
    echo "(password: ${PI_PASS})"
    echo ""
    exec ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        "${PI_USER}@${PI_IP}"
fi
