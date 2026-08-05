#!/usr/bin/env bash
# scripts/run-pi-trigger-manual.sh
# Activate venv and run pi_trigger.py in foreground for manual testing
# Usage: ./scripts/run-pi-trigger-manual.sh

set -euo pipefail
VENV_DIR=${VENV_DIR:-.venv}
if [ -d "$VENV_DIR" ]; then
  # shellcheck disable=SC1090
  source "$VENV_DIR/bin/activate"
else
  echo "Venv not found at $VENV_DIR. Creating and installing requirements..."
  python3 -m venv "$VENV_DIR"
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  pip install --upgrade pip
  if [ -f requirements.txt ]; then
    pip install -r requirements.txt
  fi
fi

echo "Running pi_trigger.py (press Space if using keyboard client or press button for GPIO client)"
echo "Queue file (if used) will be created in the working directory as pi_queue.jsonl"
python3 pi_trigger.py
