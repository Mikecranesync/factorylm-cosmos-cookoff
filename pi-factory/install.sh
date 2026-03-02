#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="factorylm-watchdog"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== FactoryLM Watchdog Installer ==="

# 1. Copy watchdog script
cp "$SCRIPT_DIR/watchdog.py" /home/pi/watchdog.py
chmod +x /home/pi/watchdog.py
echo "[1/3] Copied watchdog.py to /home/pi/"

# 2. Create systemd service
cat > /etc/systemd/system/${SERVICE_NAME}.service << 'EOF'
[Unit]
Description=FactoryLM Watchdog
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
ExecStart=/usr/bin/python3 /home/pi/watchdog.py
Restart=always
RestartSec=10
EnvironmentFile=/home/pi/.env

[Install]
WantedBy=multi-user.target
EOF
echo "[2/3] Created systemd service"

# 3. Enable and start
systemctl daemon-reload
systemctl enable ${SERVICE_NAME}
systemctl start ${SERVICE_NAME}
echo "[3/3] Service enabled and started"

echo ""
echo "Done. Check status with:"
echo "  sudo systemctl status ${SERVICE_NAME}"
echo "  journalctl -u ${SERVICE_NAME} -f"
