#!/usr/bin/env bash
set -e

# update_and_run.sh — Pull latest main, ensure venv & deps, create .env if missing, export .env, and start server
# Usage: ./update_and_run.sh

echo "1/5 — Fetching latest from origin/main..."
git fetch origin
git checkout main
git pull --ff-only origin main

echo "2/5 — Setting up virtualenv and dependencies..."
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

# Create .env from example if missing
if [ ! -f .env ]; then
  echo "3/5 — .env not found. Creating .env from .env.example (edit .env to add your OPENAI_API_KEY)"
  if [ -f .env.example ]; then
    cp .env.example .env
    echo ".env created from .env.example — edit .env to set OPENAI_API_KEY, then re-run this script"
  else
    echo ".env.example missing. Please create .env and add OPENAI_API_KEY before running."
  fi
  exit 0
fi

# Export .env into environment for this run (safe for local dev)
set -a
# shellcheck disable=SC1091
source .env
set +a

echo "4/5 — Verifying OpenAI key is present..."
if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "ERROR: OPENAI_API_KEY is not set in .env. Edit .env and add it, then re-run."
  exit 1
fi

echo "5/5 — Starting uvicorn server (Ctrl-C to stop)..."
# Start uvicorn using the venv binary so we don't rely on shell builtins in exec
exec .venv/bin/uvicorn server:app --host 0.0.0.0 --port 8000 --reload
