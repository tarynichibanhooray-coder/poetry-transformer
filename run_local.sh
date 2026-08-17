#!/usr/bin/env bash
set -euo pipefail

# Single entry point for running the server. Creates the virtualenv, installs
# dependencies, and starts uvicorn.
#
# Configuration is NOT injected here: the app loads .env itself via config.py,
# so it behaves the same however it is started. Override the bind address with
# HOST and PORT if needed.

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Creating virtualenv..."
  python3 -m venv .venv
fi

echo "Installing dependencies..."
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements.txt --quiet

if [ ! -f .env ]; then
  cp .env.example .env
  echo "No .env found, so one was created from .env.example."
  echo "Add your OPENAI_API_KEY to .env, then run this script again."
  exit 1
fi

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

echo "Starting server on http://localhost:${PORT}/ (Ctrl-C to stop)"
exec .venv/bin/uvicorn server:app --host "$HOST" --port "$PORT" --reload
