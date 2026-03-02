#!/bin/bash
echo "Pi Factory — First Boot"
# Generate unique gateway ID
GATEWAY_ID="flm-$(head -c 6 /dev/urandom | xxd -p)"
echo "{\"gateway_id\": \"$GATEWAY_ID\"}" > /opt/factorylm/config.json
# Enable services
systemctl enable factorylm-connect
systemctl start factorylm-connect
echo "Gateway ID: $GATEWAY_ID"
echo "Connect to WiFi: PiFactory-Setup"
echo "Open browser to http://192.168.4.1:8000/setup"
