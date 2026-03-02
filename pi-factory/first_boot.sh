#!/bin/bash
# Pi Factory — First Boot Script
# Runs once on first power-on to generate identity and enable services

set -e

echo "╔═══════════════════════════════════════╗"
echo "║   Pi Factory — First Boot             ║"
echo "╚═══════════════════════════════════════╝"

APP_DIR="/opt/factorylm"

# Generate unique gateway ID
GATEWAY_ID="flm-$(head -c 6 /dev/urandom | xxd -p)"

cat > "${APP_DIR}/config.json" << EOF
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
EOF

chown pi:pi "${APP_DIR}/config.json"

# Set hostname
hostnamectl set-hostname pi-factory 2>/dev/null || echo "pi-factory" > /etc/hostname
sed -i "s/127.0.1.1.*/127.0.1.1\tpi-factory/" /etc/hosts 2>/dev/null || true

# Enable services
systemctl enable pi-factory.service
systemctl enable pi-factory-watchdog.service
systemctl enable hostapd
systemctl enable dnsmasq

echo "Gateway ID: ${GATEWAY_ID}"
echo "Pi Factory first boot complete."
echo "Connect to WiFi: PiFactory-Connect"
echo "Open browser: http://192.168.4.1:8000/setup"
