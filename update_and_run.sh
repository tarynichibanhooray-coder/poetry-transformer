#!/usr/bin/env bash
set -euo pipefail

# Pull the latest main, then hand off to run_local.sh.
#
# This deliberately contains no setup or launch logic of its own, so there is
# only one way the server ever starts.
#
# Note: this checks out main, so don't run it from a feature branch.

cd "$(dirname "$0")"

echo "Fetching latest from origin/main..."
git fetch origin
git checkout main
git pull --ff-only origin main

exec ./run_local.sh
