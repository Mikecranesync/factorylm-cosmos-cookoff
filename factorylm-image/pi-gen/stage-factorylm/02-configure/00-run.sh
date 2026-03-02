#!/bin/bash -e
# Pi Factory — pi-gen network configuration stage
# Aligns with setup.sh WiFi AP and network config

# Install hostapd and dnsmasq configs
install -m 644 files/hostapd.conf "${ROOTFS_DIR}/etc/hostapd/hostapd.conf"
install -m 644 files/dnsmasq.conf "${ROOTFS_DIR}/etc/dnsmasq.d/pi-factory.conf"

# Configure static IP for wlan0 (matches setup.sh)
cat >> "${ROOTFS_DIR}/etc/dhcpcd.conf" << 'DHCPEOF'

# Pi Factory — WiFi AP static IP
interface wlan0
    static ip_address=192.168.4.1/24
    nohook wpa_supplicant
DHCPEOF

# Unmask and enable hostapd + dnsmasq
on_chroot << 'CHREOF'
systemctl unmask hostapd
systemctl enable hostapd
systemctl enable dnsmasq
CHREOF
