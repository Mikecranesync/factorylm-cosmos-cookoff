#!/bin/bash
# Pi Factory — Stage: System Dependencies
# Runs inside the pi-gen chroot (the image being built)

set -e

apt-get update
apt-get install -y \
  python3-pip python3-venv python3-dev \
  git sqlite3 curl jq xxd \
  hostapd dnsmasq \
  network-manager net-tools wireless-tools iw \
  python3-serial
