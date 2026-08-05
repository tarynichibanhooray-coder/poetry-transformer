#!/usr/bin/env bash
# scripts/enable-venv.sh
# Create a Python venv and install requirements + gpiozero
# Usage: ./scripts/enable-venv.sh [VENV_DIR]

set -euo pipefail
VENV_DIR=${1:-.venv}
PYTHON=${PYTHON:-python3}

if [ -d "$VENV_DIR" ]; then
  echo "Venv already exists at $VENV_DIR"
else
  echo "Creating venv at $VENV_DIR"
  $PYTHON -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
if [ -f requirements.txt ]; then
  pip install -r requirements.txt
fi
# gpiozero might not be in requirements; ensure installed for Pi
pip install gpiozero || true

echo "Venv ready. Activate with: source $VENV_DIR/bin/activate"
