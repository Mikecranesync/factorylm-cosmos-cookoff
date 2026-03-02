#!/bin/bash
# Pi Factory — Stage: Deploy Application
# Runs on the HOST (not chroot) — copies files into the image rootfs

set -e

# The repo root is two levels up from stage-factorylm
REPO_ROOT="$(cd "$(dirname "$0")/../../../../.." && pwd)"

# Create app directory structure in the image
install -d "${ROOTFS_DIR}/opt/factorylm/net/api"
install -d "${ROOTFS_DIR}/opt/factorylm/net/drivers"
install -d "${ROOTFS_DIR}/opt/factorylm/net/platform"
install -d "${ROOTFS_DIR}/opt/factorylm/net/portal"
install -d "${ROOTFS_DIR}/opt/factorylm/net/services"
install -d "${ROOTFS_DIR}/opt/factorylm/net/sim"
install -d "${ROOTFS_DIR}/opt/factorylm/net/diagnosis"
install -d "${ROOTFS_DIR}/opt/factorylm/config"
install -d "${ROOTFS_DIR}/opt/factorylm/data"
install -d "${ROOTFS_DIR}/var/log/factorylm"

# Copy application code
cp -r "${REPO_ROOT}/net/"* "${ROOTFS_DIR}/opt/factorylm/net/"

# Create __init__.py files
for d in net net/api net/drivers net/platform net/portal net/services net/sim net/diagnosis; do
    touch "${ROOTFS_DIR}/opt/factorylm/${d}/__init__.py"
done

# Copy config files
if [ -f "${REPO_ROOT}/config/factoryio.yaml" ]; then
    cp "${REPO_ROOT}/config/factoryio.yaml" "${ROOTFS_DIR}/opt/factorylm/config/"
fi

# Copy requirements.txt
cp "${REPO_ROOT}/requirements.txt" "${ROOTFS_DIR}/opt/factorylm/"

# Install first_boot script
install -m 755 "${REPO_ROOT}/pi-factory/first_boot.sh" \
    "${ROOTFS_DIR}/opt/factorylm/first_boot.sh"

# Install systemd services
install -m 644 "${REPO_ROOT}/pi-factory/systemd/pi-factory.service" \
    "${ROOTFS_DIR}/etc/systemd/system/pi-factory.service"
install -m 644 "${REPO_ROOT}/pi-factory/systemd/pi-factory-watchdog.service" \
    "${ROOTFS_DIR}/etc/systemd/system/pi-factory-watchdog.service"
install -m 644 "${REPO_ROOT}/pi-factory/systemd/pi-factory-firstboot.service" \
    "${ROOTFS_DIR}/etc/systemd/system/pi-factory-firstboot.service"

# Set ownership (pi user UID=1000 in pi-gen)
chown -R 1000:1000 "${ROOTFS_DIR}/opt/factorylm"
chown -R 1000:1000 "${ROOTFS_DIR}/var/log/factorylm"
