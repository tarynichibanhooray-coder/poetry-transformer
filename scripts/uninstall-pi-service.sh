#!/usr/bin/env bash
# scripts/uninstall-pi-service.sh
# Disables and removes the pi-trigger-gpio systemd service
# Usage: sudo ./scripts/uninstall-pi-service.sh [--remove-server]

set -euo pipefail
REMOVE_SERVER=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --remove-server) REMOVE_SERVER=1; shift ;;
    *) echo "Unknown arg: $1"; exit 2;;
  esac
done

sudo systemctl stop pi-trigger-gpio || true
sudo systemctl disable pi-trigger-gpio || true
sudo rm -f /etc/systemd/system/pi-trigger-gpio.service || true
sudo systemctl daemon-reload
sudo systemctl reset-failed

if [ "$REMOVE_SERVER" -eq 1 ]; then
  sudo systemctl stop poetry-transformer || true
  sudo systemctl disable poetry-transformer || true
  sudo rm -f /etc/systemd/system/poetry-transformer.service || true
  sudo systemctl daemon-reload
  sudo systemctl reset-failed
fi

echo "Uninstall complete. Units removed and systemd reloaded."
