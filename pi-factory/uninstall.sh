#!/bin/bash
# =============================================================================
#  PI FACTORY — Uninstall Script
#  Cleanly removes Pi Factory from a Raspberry Pi
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}Run as root: sudo bash pi-factory/uninstall.sh${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}${BOLD}Pi Factory Uninstall${NC}"
echo ""
echo "This will remove:"
echo "  - /opt/factorylm (application + data)"
echo "  - pi-factory systemd services"
echo "  - WiFi AP configuration"
echo "  - Pi Factory branding"
echo ""
read -p "Continue? [y/N] " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 0
fi

echo "Stopping services..."
systemctl stop pi-factory 2>/dev/null || true
systemctl stop pi-factory-watchdog 2>/dev/null || true
systemctl stop hostapd 2>/dev/null || true

echo "Disabling services..."
systemctl disable pi-factory 2>/dev/null || true
systemctl disable pi-factory-watchdog 2>/dev/null || true

echo "Removing service files..."
rm -f /etc/systemd/system/pi-factory.service
rm -f /etc/systemd/system/pi-factory-watchdog.service
systemctl daemon-reload

echo "Removing application..."
rm -rf /opt/factorylm

echo "Removing WiFi AP config..."
rm -f /etc/dnsmasq.d/pi-factory.conf
rm -f /etc/hostapd/hostapd.conf
# Remove NetworkManager unmanage rule + systemd-networkd override (Bookworm)
rm -f /etc/NetworkManager/conf.d/pi-factory-unmanage-wlan0.conf
rm -f /etc/systemd/network/10-pf-wlan0.network
systemctl reload NetworkManager 2>/dev/null || true

echo "Removing branding..."
rm -f /etc/profile.d/pi-factory.sh
echo "" > /etc/motd

echo "Removing logs..."
rm -rf /var/log/factorylm

echo ""
echo -e "${GREEN}Pi Factory has been removed.${NC}"
echo "You may want to: sudo reboot"
