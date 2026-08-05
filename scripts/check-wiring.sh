#!/usr/bin/env bash
# scripts/check-wiring.sh
# Quick wiring check for GPIO button using gpiozero
# Usage: ./scripts/check-wiring.sh [BUTTON_PIN]

set -euo pipefail
BUTTON_PIN=${1:-${BUTTON_PIN:-17}}
PYTHON=$(command -v python3 || true)
if [ -z "$PYTHON" ]; then
  echo "python3 not found"
  exit 2
fi

$PYTHON - <<PY
import os
try:
    from gpiozero import Button
except Exception as e:
    print('gpiozero import failed:', e)
    raise SystemExit(3)

pin = int(os.environ.get('BUTTON_PIN', '$BUTTON_PIN'))
btn = Button(pin, pull_up=True)
print(f'BUTTON_PIN={pin}, is_pressed={btn.is_pressed}')
# Wait briefly to allow human to press button if they want
print('You can press the button now (waiting 3s to sample)...')
import time
start = time.time()
pressed = btn.is_pressed
while time.time() - start < 3:
    if btn.is_pressed:
        pressed = True
        break
    time.sleep(0.05)
print('Final sample: is_pressed=', pressed)
PY
