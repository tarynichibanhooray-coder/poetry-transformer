#!/usr/bin/env bash
# scripts/run-server-dev.sh
# Activate venv and run uvicorn in reload mode for development
# Usage: ./scripts/run-server-dev.sh [PORT]

set -euo pipefail
PORT=${1:-8000}
VENV_DIR=${VENV_DIR:-.venv}

if [ -d "$VENV_DIR" ]; then
  echo "Activating venv: $VENV_DIR"
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

echo "Starting uvicorn server:app --reload on 0.0.0.0:$PORT"
exec uvicorn server:app --host 0.0.0.0 --port "$PORT" --reload
