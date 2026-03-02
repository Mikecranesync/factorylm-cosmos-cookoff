#!/bin/bash
# Pi Factory — Stage: Python Virtual Environment
# Runs inside the pi-gen chroot

set -e

python3 -m venv /opt/factorylm/venv

/opt/factorylm/venv/bin/pip install --upgrade pip

/opt/factorylm/venv/bin/pip install \
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
