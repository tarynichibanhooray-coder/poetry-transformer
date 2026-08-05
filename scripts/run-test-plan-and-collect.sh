#!/usr/bin/env bash
# scripts/run-test-plan-and-collect.sh
# Wrapper to run a minimal test sequence and then collect artifacts into a tarball
# Usage: ./scripts/run-test-plan-and-collect.sh <server-host[:port]>

set -euo pipefail
SERVER_HOST=${1:-localhost:8000}
REPO_ROOT=$(pwd)

echo "Running basic healthcheck against http://$SERVER_HOST/state"
./scripts/healthcheck.sh "http://$SERVER_HOST"

echo "Triggering a test trigger via curl"
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST "http://$SERVER_HOST/trigger" || true

echo "Waiting 1s for server to process"
sleep 1

echo "Collecting test results"
./scripts/collect-test-results.sh "$SERVER_HOST"

echo "Test results packaged at $REPO_ROOT/test-results.tar.gz"
ls -lh "$REPO_ROOT/test-results.tar.gz"
