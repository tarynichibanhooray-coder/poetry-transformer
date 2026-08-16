#!/usr/bin/env bash
set -e

# Create venv if missing, install deps, run uvicorn
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
if [ -f requirements.txt ]; then
  pip install -r requirements.txt
else
  pip install fastapi uvicorn[standard] requests
fi

# Run server
exec .venv/bin/uvicorn server:app --host 0.0.0.0 --port 8000 --reload
