#!/usr/bin/env bash
# scripts/healthcheck.sh
# Simple HTTP healthcheck for the Poetry Transformer server
# Usage: ./scripts/healthcheck.sh [SERVER_URL]

set -euo pipefail
SERVER_URL=${1:-${SERVER_URL:-http://localhost:8000}}

echo "Checking server state at $SERVER_URL/state"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$SERVER_URL/state" || true)
if [ "$HTTP_CODE" = "200" ]; then
  echo "OK: /state returned 200"
  curl -s "$SERVER_URL/state" | jq . || true
  exit 0
else
  echo "FAIL: /state returned HTTP $HTTP_CODE"
  exit 1
fi
