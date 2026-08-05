#!/usr/bin/env bash
# scripts/collect-test-results.sh
# Implements the test-plan artifact collection and packages results into test-results.tar.gz
# Run from the repo root where output/ and system services are accessible.

set -euo pipefail
REPO_ROOT=$(pwd)
RESULT_DIR="$REPO_ROOT/test-results"
SERVER_HOST=${1:-${SERVER_HOST:-localhost:8000}}
mkdir -p "$RESULT_DIR"

echo "Collecting /state"
curl -s "http://$SERVER_HOST/state" > "$RESULT_DIR/state.json" || true

echo "Collecting translation stream tail"
if [ -f output/translation_stream.jsonl ]; then
  tail -n 50 output/translation_stream.jsonl > "$RESULT_DIR/translation_stream.jsonl" || true
fi

echo "Collecting journal logs (may require sudo)"
if command -v systemctl >/dev/null 2>&1; then
  sudo journalctl -u poetry-transformer -n 500 > "$RESULT_DIR/server_journal.log" || true
  sudo journalctl -u pi-trigger-gpio -n 500 > "$RESULT_DIR/pi_journal.log" || true
  sudo systemctl status pi-trigger-gpio > "$RESULT_DIR/pi_service_status.txt" || true
  sudo systemctl status poetry-transformer > "$RESULT_DIR/server_service_status.txt" || true
fi

echo "Collecting pi_queue.jsonl if present"
if [ -f pi_queue.jsonl ]; then
  wc -l pi_queue.jsonl > "$RESULT_DIR/queue_count.txt" || true
  head -n 200 pi_queue.jsonl > "$RESULT_DIR/queue_sample.jsonl" || true
fi

echo "Collecting other logs and files"
ls -l > "$RESULT_DIR/ls.txt" || true

TAR_FILE="$REPO_ROOT/test-results.tar.gz"
rm -f "$TAR_FILE"
tar -czf "$TAR_FILE" -C "$RESULT_DIR" .

echo "Packaged results -> $TAR_FILE"
