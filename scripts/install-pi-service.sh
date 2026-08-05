#!/usr/bin/env bash
# scripts/install-pi-service.sh
# Installs and enables the pi-trigger-gpio systemd service (and optional server unit)
# Usage: sudo ./scripts/install-pi-service.sh [--install-server]

set -euo pipefail
INSTALL_SERVER=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-server) INSTALL_SERVER=1; shift ;;
    *) echo "Unknown arg: $1"; exit 2;;
  esac
done

SERVICE_SRC="systemd/pi-trigger-gpio.service"
SERVICE_DST="/etc/systemd/system/pi-trigger-gpio.service"

if [ ! -f "$SERVICE_SRC" ]; then
  echo "Service file $SERVICE_SRC not found in repo. Run from repo root." >&2
  exit 2
fi

sudo cp "$SERVICE_SRC" "$SERVICE_DST"
sudo systemctl daemon-reload
sudo systemctl enable --now pi-trigger-gpio
sudo systemctl status --no-pager pi-trigger-gpio || true

if [ "$INSTALL_SERVER" -eq 1 ]; then
  echo "Installing server unit"
  if [ -f systemd/poetry-transformer.service ]; then
    sudo cp systemd/poetry-transformer.service /etc/systemd/system/poetry-transformer.service
    sudo systemctl daemon-reload
    sudo systemctl enable --now poetry-transformer
    sudo systemctl status --no-pager poetry-transformer || true
  else
    echo "systemd/poetry-transformer.service not found in repo; skipping server install"
  fi
fi

echo "Install complete. Check logs with: sudo journalctl -u pi-trigger-gpio -f"
