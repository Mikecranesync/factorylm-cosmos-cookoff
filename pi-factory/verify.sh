#!/bin/bash
# =============================================================================
#  PI FACTORY — Verification Script
#  Run on the Pi after setup to confirm everything works.
#
#  Usage: bash ~/factorylm/pi-factory/verify.sh
# =============================================================================

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

pass() { echo -e "  ${GREEN}PASS${NC}  $1"; ((PASS++)); }
fail() { echo -e "  ${RED}FAIL${NC}  $1"; ((FAIL++)); }
warn() { echo -e "  ${YELLOW}WARN${NC}  $1"; ((WARN++)); }

echo ""
echo -e "${CYAN}${BOLD}  Pi Factory — Verification${NC}"
echo ""

# ── 1. Systemd service ───────────────────────────────────────────────────────
echo -e "${BOLD}1. Systemd Service${NC}"
if systemctl is-active --quiet pi-factory; then
    pass "pi-factory.service is running"
else
    fail "pi-factory.service is NOT running"
    echo "       Fix: sudo systemctl start pi-factory && pf-logs"
fi

if systemctl is-enabled --quiet pi-factory; then
    pass "pi-factory.service is enabled (starts on boot)"
else
    warn "pi-factory.service is not enabled"
fi

# ── 2. API responds ──────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}2. API Health${NC}"
if curl -sf http://localhost:8000/api/status > /dev/null 2>&1; then
    pass "API responds at :8000/api/status"
else
    fail "API not responding at :8000/api/status"
fi

# ── 3. Gateway identity ──────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}3. Gateway Identity${NC}"
if [[ -f /opt/factorylm/config.json ]]; then
    GW_ID=$(jq -r '.gateway_id // empty' /opt/factorylm/config.json 2>/dev/null)
    if [[ -n "$GW_ID" ]]; then
        pass "Gateway ID: ${GW_ID}"
    else
        fail "config.json exists but no gateway_id"
    fi
else
    fail "/opt/factorylm/config.json missing"
fi

# ── 4. PLC scan ──────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}4. PLC Discovery${NC}"
PLC_RESULT=$(curl -sf http://localhost:8000/api/plc/scan 2>/dev/null || echo "")
if [[ -n "$PLC_RESULT" ]]; then
    PLC_COUNT=$(echo "$PLC_RESULT" | jq 'if type == "array" then length else 0 end' 2>/dev/null || echo "0")
    if [[ "$PLC_COUNT" -gt 0 ]]; then
        pass "PLC scan found ${PLC_COUNT} device(s)"
    else
        warn "PLC scan returned 0 devices (is Ethernet connected to PLC subnet?)"
    fi
else
    warn "PLC scan endpoint not available (API may still be starting)"
fi

# ── 5. WiFi AP ───────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}5. WiFi Access Point${NC}"
if systemctl is-active --quiet hostapd; then
    pass "hostapd is running (WiFi AP active)"
else
    warn "hostapd is not running"
    echo "       Fix: sudo systemctl start hostapd"
fi

if systemctl is-active --quiet dnsmasq; then
    pass "dnsmasq is running (DHCP for WiFi clients)"
else
    warn "dnsmasq is not running"
fi

# Check wlan0 has the right IP
WLAN_IP=$(ip -4 addr show wlan0 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -1)
if [[ "$WLAN_IP" == "192.168.4.1" ]]; then
    pass "wlan0 has correct IP: 192.168.4.1"
else
    warn "wlan0 IP is '${WLAN_IP:-none}' (expected 192.168.4.1)"
fi

# ── 6. Static IP ─────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}6. Network${NC}"
ETH_IP=$(ip -4 addr show eth0 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -1)
if [[ "$ETH_IP" == "192.168.1.30" ]]; then
    pass "eth0 has static IP: 192.168.1.30"
else
    warn "eth0 IP is '${ETH_IP:-none}' (expected 192.168.1.30)"
fi

# ── 7. Tailscale ─────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}7. Tailscale${NC}"
if command -v tailscale > /dev/null 2>&1; then
    TS_STATUS=$(tailscale status --json 2>/dev/null | jq -r '.BackendState // empty' 2>/dev/null)
    if [[ "$TS_STATUS" == "Running" ]]; then
        TS_IP=$(tailscale ip -4 2>/dev/null || echo "unknown")
        pass "Tailscale running (IP: ${TS_IP})"
    elif [[ "$TS_STATUS" == "NeedsLogin" ]]; then
        warn "Tailscale installed but needs login: sudo tailscale up"
    else
        warn "Tailscale installed but state: ${TS_STATUS:-unknown}"
    fi
else
    warn "Tailscale not installed"
fi

# ── 8. Python venv + pylogix ─────────────────────────────────────────────────
echo ""
echo -e "${BOLD}8. Python Environment${NC}"
if [[ -f /opt/factorylm/venv/bin/python ]]; then
    pass "Python venv exists"
else
    fail "Python venv missing at /opt/factorylm/venv/"
fi

if /opt/factorylm/venv/bin/python -c "import pylogix" 2>/dev/null; then
    pass "pylogix installed"
else
    warn "pylogix not installed (install: /opt/factorylm/venv/bin/pip install pylogix)"
fi

if /opt/factorylm/venv/bin/python -c "import pymodbus" 2>/dev/null; then
    pass "pymodbus installed"
else
    fail "pymodbus not installed"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  ${GREEN}PASS: ${PASS}${NC}  ${RED}FAIL: ${FAIL}${NC}  ${YELLOW}WARN: ${WARN}${NC}"

if [[ $FAIL -eq 0 ]]; then
    echo ""
    echo -e "  ${GREEN}${BOLD}Pi Factory is operational.${NC}"
    echo ""
    IP=$(hostname -I | awk '{print $1}')
    echo "  Dashboard:    http://${IP}:8000"
    echo "  Setup Wizard: http://192.168.4.1:8000/setup"
    echo "  WiFi AP:      PiFactory-Connect (password: factorylm)"
else
    echo ""
    echo -e "  ${RED}${BOLD}Fix the FAILs above before proceeding.${NC}"
fi
echo ""
