#!/bin/bash
# =============================================================================
#  PI FACTORY — Master Setup Script
#  Transforms a fresh Raspberry Pi OS into the Pi Factory appliance.
#
#  Usage:
#    curl -sSL https://raw.githubusercontent.com/Mikecranesync/factorylm-cosmos-cookoff/main/pi-factory/setup.sh | sudo bash
#
#  Or manually:
#    sudo bash pi-factory/setup.sh
#
#  What this does:
#    1. Installs system dependencies
#    2. Creates /opt/factorylm directory structure
#    3. Sets up Python venv with all packages
#    4. Copies application code
#    5. Configures WiFi captive portal (hostapd + dnsmasq)
#    6. Installs systemd services (auto-start on boot)
#    7. Generates unique gateway ID
#    8. Sets Pi Factory branding (hostname, MOTD, splash)
#    9. Enables and starts everything
#
#  Compatible: Raspberry Pi 3B+, Pi 4, Pi 5, Pi Zero 2W
#  OS: Raspberry Pi OS Bookworm (64-bit recommended)
# =============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Config
APP_DIR="/opt/factorylm"
VENV_DIR="${APP_DIR}/venv"
DATA_DIR="${APP_DIR}/data"
LOG_DIR="/var/log/factorylm"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PI_USER="${SUDO_USER:-pi}"
HOSTNAME_NEW="pi-factory"
WIFI_SSID="PiFactory-Connect"
WIFI_IP="192.168.4.1"

# =============================================================================
# Banner
# =============================================================================
print_banner() {
    echo ""
    echo -e "${CYAN}${BOLD}"
    echo "  ╔═══════════════════════════════════════════════╗"
    echo "  ║                                               ║"
    echo "  ║          ┏━━━┓ ┏━━━┓                          ║"
    echo "  ║          ┃ ╔═╝ ┃ ╔═╝                          ║"
    echo "  ║          ┃ ╚═╗ ┃ ╚═╗                          ║"
    echo "  ║          ┗━━━╝ ┗━━━╝                          ║"
    echo "  ║                                               ║"
    echo "  ║        P I   F A C T O R Y                    ║"
    echo "  ║        by Pi Factory                           ║"
    echo "  ║                                               ║"
    echo "  ║   Industrial PLC Monitor + AI Diagnosis       ║"
    echo "  ║   Type a command. Move a machine.             ║"
    echo "  ║                                               ║"
    echo "  ╚═══════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo ""
}

# =============================================================================
# Helpers
# =============================================================================
step() {
    echo ""
    echo -e "${BLUE}${BOLD}━━━ Step $1: $2 ━━━${NC}"
}

ok() {
    echo -e "  ${GREEN}✓${NC} $1"
}

warn() {
    echo -e "  ${YELLOW}⚠${NC} $1"
}

fail() {
    echo -e "  ${RED}✗${NC} $1"
    exit 1
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        fail "This script must be run as root (sudo bash pi-factory/setup.sh)"
    fi
}

check_pi() {
    if [[ ! -f /proc/device-tree/model ]] && [[ ! -f /sys/firmware/devicetree/base/model ]]; then
        warn "Not running on a Raspberry Pi — continuing in dev mode"
        export PI_FACTORY_DEV=1
    else
        MODEL=$(cat /proc/device-tree/model 2>/dev/null || cat /sys/firmware/devicetree/base/model 2>/dev/null)
        ok "Detected: ${MODEL}"
    fi
}

# =============================================================================
# Step 1: System Dependencies
# =============================================================================
install_system_deps() {
    step "1/9" "Installing system dependencies"

    apt-get update -qq

    PACKAGES=(
        python3-pip
        python3-venv
        python3-dev
        git
        sqlite3
        # WiFi AP + captive portal
        hostapd
        dnsmasq
        # Networking tools
        network-manager
        net-tools
        wireless-tools
        iw
        # Modbus serial (for VFD RS485)
        python3-serial
        # Misc
        xxd
        curl
        jq
    )

    apt-get install -y -qq "${PACKAGES[@]}" 2>/dev/null
    ok "System packages installed"
}

# =============================================================================
# Step 2: Directory Structure
# =============================================================================
create_directories() {
    step "2/9" "Creating Pi Factory directory structure"

    mkdir -p "${APP_DIR}"
    mkdir -p "${APP_DIR}/net/api"
    mkdir -p "${APP_DIR}/net/drivers"
    mkdir -p "${APP_DIR}/net/platform"
    mkdir -p "${APP_DIR}/net/portal"
    mkdir -p "${APP_DIR}/net/services"
    mkdir -p "${APP_DIR}/net/sim"
    mkdir -p "${APP_DIR}/net/diagnosis"
    mkdir -p "${APP_DIR}/config"
    mkdir -p "${DATA_DIR}"
    mkdir -p "${LOG_DIR}"

    chown -R "${PI_USER}:${PI_USER}" "${APP_DIR}"
    chown -R "${PI_USER}:${PI_USER}" "${LOG_DIR}"
    ok "Created ${APP_DIR}"
    ok "Created ${DATA_DIR}"
    ok "Created ${LOG_DIR}"
}

# =============================================================================
# Step 3: Python Virtual Environment
# =============================================================================
setup_python_venv() {
    step "3/9" "Setting up Python virtual environment"

    python3 -m venv "${VENV_DIR}"

    # Upgrade pip
    "${VENV_DIR}/bin/pip" install --upgrade pip -q

    # Install all required packages
    "${VENV_DIR}/bin/pip" install -q \
        "pymodbus>=3.6,<4.0" \
        "pycomm3>=1.2,<2.0" \
        "opcua>=0.98,<1.0" \
        "fastapi>=0.100" \
        "uvicorn[standard]" \
        "aiosqlite" \
        "qrcode[pil]" \
        "python-multipart" \
        "httpx" \
        "pyyaml" \
        "Pillow" \
        "pyserial"

    ok "Python venv created at ${VENV_DIR}"
    ok "All Python packages installed"
}

# =============================================================================
# Step 4: Copy Application Code
# =============================================================================
copy_app_code() {
    step "4/9" "Deploying Pi Factory application"

    # Copy net/ application package
    if [[ -d "${REPO_DIR}/net" ]]; then
        cp -r "${REPO_DIR}/net/"* "${APP_DIR}/net/"
        ok "Copied net/ application code"
    else
        fail "Cannot find net/ directory in ${REPO_DIR}"
    fi

    # Copy config files
    if [[ -f "${REPO_DIR}/config/factoryio.yaml" ]]; then
        cp "${REPO_DIR}/config/factoryio.yaml" "${APP_DIR}/config/"
        ok "Copied config/factoryio.yaml"
    fi

    # Copy requirements.txt
    if [[ -f "${REPO_DIR}/requirements.txt" ]]; then
        cp "${REPO_DIR}/requirements.txt" "${APP_DIR}/"
        ok "Copied requirements.txt"
    fi

    # Create __init__.py files for packages
    touch "${APP_DIR}/net/__init__.py"
    touch "${APP_DIR}/net/api/__init__.py"
    touch "${APP_DIR}/net/drivers/__init__.py"
    touch "${APP_DIR}/net/platform/__init__.py"
    touch "${APP_DIR}/net/portal/__init__.py"
    touch "${APP_DIR}/net/services/__init__.py"
    touch "${APP_DIR}/net/sim/__init__.py"
    touch "${APP_DIR}/net/diagnosis/__init__.py"

    # Set permissions
    chown -R "${PI_USER}:${PI_USER}" "${APP_DIR}"
    ok "Application deployed to ${APP_DIR}"
}

# =============================================================================
# Step 5: WiFi Captive Portal
# =============================================================================
setup_captive_portal() {
    step "5/9" "Configuring WiFi captive portal"

    if [[ "${PI_FACTORY_DEV:-0}" == "1" ]]; then
        warn "Dev mode — skipping WiFi AP setup"
        return
    fi

    # Stop services during config
    systemctl stop hostapd 2>/dev/null || true
    systemctl stop dnsmasq 2>/dev/null || true

    # hostapd config — WiFi access point
    cat > /etc/hostapd/hostapd.conf << HOSTAPD
interface=wlan0
driver=nl80211
ssid=${WIFI_SSID}
hw_mode=g
channel=6
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
# WPA2 for security
wpa=2
wpa_passphrase=factorylm
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
HOSTAPD

    # Point hostapd to config
    sed -i 's|#DAEMON_CONF=""|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd 2>/dev/null || true

    # dnsmasq config — DHCP + DNS redirect
    cat > /etc/dnsmasq.d/pi-factory.conf << DNSMASQ
interface=wlan0
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
address=/#/${WIFI_IP}
DNSMASQ

    # Static IP for wlan0 via NetworkManager (Bookworm)
    # Remove any existing Pi Factory wlan0 connection
    nmcli con delete "pf-wlan0" 2>/dev/null || true

    # Create static wlan0 connection (used by hostapd, not managed by NM)
    # We use ip command + systemd-networkd override instead
    cat > /etc/systemd/network/10-pf-wlan0.network << NETD
[Match]
Name=wlan0

[Network]
Address=${WIFI_IP}/24
DHCPServer=no
NETD

    # Tell NetworkManager to leave wlan0 alone (hostapd manages it)
    cat > /etc/NetworkManager/conf.d/pi-factory-unmanage-wlan0.conf << NM_CONF
[keyfile]
unmanaged-devices=interface-name:wlan0
NM_CONF

    # Reload NetworkManager to pick up the unmanage rule
    systemctl reload NetworkManager 2>/dev/null || true

    # Set wlan0 IP directly (takes effect now, before reboot)
    ip addr flush dev wlan0 2>/dev/null || true
    ip addr add ${WIFI_IP}/24 dev wlan0 2>/dev/null || true
    ip link set wlan0 up 2>/dev/null || true

    # Unmask and enable
    systemctl unmask hostapd
    systemctl enable hostapd
    systemctl enable dnsmasq

    ok "WiFi AP configured: SSID=${WIFI_SSID}"
    ok "Captive portal on ${WIFI_IP}:8000"
}

# =============================================================================
# Step 6: Systemd Services
# =============================================================================
install_services() {
    step "6/9" "Installing systemd services"

    # Main application service
    cat > /etc/systemd/system/pi-factory.service << SERVICE
[Unit]
Description=Pi Factory — Pi Factory Gateway
Documentation=https://github.com/Mikecranesync/factorylm-cosmos-cookoff
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${PI_USER}
WorkingDirectory=${APP_DIR}
Environment="PATH=${VENV_DIR}/bin:/usr/local/bin:/usr/bin:/bin"
Environment="FACTORYLM_NET_MODE=real"
Environment="FACTORYLM_NET_DB=${DATA_DIR}/net.db"
ExecStart=${VENV_DIR}/bin/uvicorn net.api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=pi-factory

[Install]
WantedBy=multi-user.target
SERVICE

    # Watchdog service — restarts if API is unresponsive
    cat > /etc/systemd/system/pi-factory-watchdog.service << WATCHDOG
[Unit]
Description=Pi Factory Watchdog
After=pi-factory.service
Requires=pi-factory.service

[Service]
Type=simple
User=${PI_USER}
ExecStart=/bin/bash -c 'while true; do sleep 30; curl -sf http://localhost:8000/api/status > /dev/null || (echo "Pi Factory unresponsive, restarting..." | systemd-cat -t pi-factory-watchdog && systemctl restart pi-factory); done'
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
WATCHDOG

    # Reload and enable
    systemctl daemon-reload
    systemctl enable pi-factory.service
    systemctl enable pi-factory-watchdog.service

    ok "pi-factory.service installed and enabled"
    ok "pi-factory-watchdog.service installed and enabled"
}

# =============================================================================
# Step 7: Generate Gateway Identity
# =============================================================================
generate_gateway_id() {
    step "7/9" "Generating unique gateway identity"

    GATEWAY_ID="flm-$(head -c 6 /dev/urandom | xxd -p)"

    cat > "${APP_DIR}/config.json" << CONFIG
{
    "gateway_id": "${GATEWAY_ID}",
    "name": "Pi Factory",
    "version": "1.0.0",
    "mode": "real",
    "api_port": 8000,
    "plc_poll_hz": 5,
    "history_write_hz": 1,
    "created_at": "$(date -Iseconds)"
}
CONFIG

    chown "${PI_USER}:${PI_USER}" "${APP_DIR}/config.json"
    ok "Gateway ID: ${GATEWAY_ID}"
}

# =============================================================================
# Step 8: Pi Factory Branding
# =============================================================================
setup_branding() {
    step "8/9" "Applying Pi Factory branding"

    # Set hostname
    hostnamectl set-hostname "${HOSTNAME_NEW}" 2>/dev/null || echo "${HOSTNAME_NEW}" > /etc/hostname

    # Update /etc/hosts
    sed -i "s/127.0.1.1.*/127.0.1.1\t${HOSTNAME_NEW}/" /etc/hosts 2>/dev/null || true

    # MOTD — the first thing you see on SSH login
    cat > /etc/motd << 'MOTD'

  ╔═══════════════════════════════════════════════════╗
  ║                                                   ║
  ║            ⚙  P I   F A C T O R Y  ⚙             ║
  ║            ━━━━━━━━━━━━━━━━━━━━━━━━               ║
  ║                                                   ║
  ║   Industrial PLC Monitor + AI Diagnosis           ║
  ║   Powered by Pi Factory                            ║
  ║                                                   ║
  ║   Dashboard:  http://pi-factory.local:8000        ║
  ║   WiFi AP:    PiFactory-Connect                   ║
  ║   Status:     sudo systemctl status pi-factory    ║
  ║   Logs:       sudo journalctl -u pi-factory -f    ║
  ║                                                   ║
  ╚═══════════════════════════════════════════════════╝

MOTD

    # Profile helper — pi-factory command
    cat > /etc/profile.d/pi-factory.sh << 'PROFILE'
# Pi Factory CLI helpers
alias pf-status='systemctl status pi-factory'
alias pf-logs='journalctl -u pi-factory -f --no-pager'
alias pf-restart='sudo systemctl restart pi-factory'
alias pf-stop='sudo systemctl stop pi-factory'
alias pf-start='sudo systemctl start pi-factory'

pf-info() {
    echo ""
    echo "  Pi Factory Status"
    echo "  ━━━━━━━━━━━━━━━━"
    local STATUS=$(systemctl is-active pi-factory 2>/dev/null || echo "unknown")
    local GW_ID=$(jq -r '.gateway_id // "unknown"' /opt/factorylm/config.json 2>/dev/null || echo "unknown")
    local IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    echo "  Service:    ${STATUS}"
    echo "  Gateway:    ${GW_ID}"
    echo "  IP:         ${IP}"
    echo "  Dashboard:  http://${IP}:8000"
    echo "  WiFi AP:    PiFactory-Connect"
    echo ""
}

# Show info on login
pf-info
PROFILE

    chmod +x /etc/profile.d/pi-factory.sh
    ok "Hostname set to ${HOSTNAME_NEW}"
    ok "MOTD and CLI helpers installed"
}

# =============================================================================
# Step 9: Launch Everything
# =============================================================================
launch() {
    step "9/9" "Starting Pi Factory"

    # Start services
    systemctl start pi-factory.service || warn "Could not start pi-factory (may need reboot)"

    if [[ "${PI_FACTORY_DEV:-0}" != "1" ]]; then
        systemctl start hostapd || warn "Could not start hostapd"
        systemctl start dnsmasq || warn "Could not start dnsmasq"
    fi

    # Wait for API to come up
    echo -n "  Waiting for API..."
    for i in {1..15}; do
        if curl -sf http://localhost:8000/api/status > /dev/null 2>&1; then
            echo -e " ${GREEN}UP${NC}"
            break
        fi
        echo -n "."
        sleep 2
    done

    # Final status
    echo ""
    echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "  ${GREEN}${BOLD}Pi Factory is LIVE${NC}"
    echo ""

    local IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    local GW_ID=$(jq -r '.gateway_id' "${APP_DIR}/config.json" 2>/dev/null || echo "unknown")

    echo -e "  Gateway ID:   ${CYAN}${GW_ID}${NC}"
    echo -e "  Dashboard:    ${CYAN}http://${IP:-pi-factory.local}:8000${NC}"
    echo -e "  Setup Wizard: ${CYAN}http://${IP:-pi-factory.local}:8000/setup${NC}"

    if [[ "${PI_FACTORY_DEV:-0}" != "1" ]]; then
        echo -e "  WiFi AP:      ${CYAN}${WIFI_SSID}${NC} (password: factorylm)"
    fi

    echo ""
    echo -e "  ${BOLD}Next steps:${NC}"
    echo "    1. Connect phone to WiFi: ${WIFI_SSID}"
    echo "    2. Open browser → wizard auto-launches"
    echo "    3. Plug Ethernet into PLC subnet"
    echo "    4. Wizard auto-discovers your PLC"
    echo ""
    echo -e "  ${BOLD}Commands:${NC}"
    echo "    pf-status   — check service status"
    echo "    pf-logs     — tail live logs"
    echo "    pf-restart  — restart the service"
    echo "    pf-info     — show gateway info"
    echo ""
    echo -e "${GREEN}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

# =============================================================================
# Main
# =============================================================================
main() {
    print_banner
    check_root
    check_pi

    echo -e "${BOLD}Starting Pi Factory setup...${NC}"
    echo -e "  Source:  ${REPO_DIR}"
    echo -e "  Target:  ${APP_DIR}"
    echo -e "  User:    ${PI_USER}"
    echo ""

    install_system_deps
    create_directories
    setup_python_venv
    copy_app_code
    setup_captive_portal
    install_services
    generate_gateway_id
    setup_branding
    launch

    echo "Setup complete. Reboot recommended: sudo reboot"
}

main "$@"
