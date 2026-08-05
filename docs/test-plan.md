# Test Plan (end-to-end verification)

This document contains a step-by-step test plan you can run to verify the full flow: Pi button → server POST /trigger → server advances poem → Web UI updates.

Prerequisites
- Server running at http://<server-host>:8000 (uvicorn or systemd unit)
- Web UI reachable at http://<server-host>:8000/
- Pi with pi_trigger_gpio.py installed and systemd service enabled (if running as service)
- jq installed on the machine where you run the cURL checks (optional but helpful)

Quick collection prep
- Create a directory to gather artifacts:

  mkdir -p ~/poetry-transformer/test-results
  cd ~/poetry-transformer

Test steps and exact commands

1) Verify server health

  curl -s http://<server-host>:8000/state | jq .

Expected: JSON with keys "current_state" and "stats".
Save results:
  curl -s http://<server-host>:8000/state > test-results/state.json

2) Confirm web UI connects
- Open http://<server-host>:8000/ in a browser.
- In DevTools Console, ensure WebSocket connects and no errors.

3) Trigger with web UI (Space)
- Press Space.
- Check server-side event append:
  tail -n 5 output/translation_stream.jsonl

Expected: New JSON event with "reason": "trigger" and a new sequence_index.
Save tail:
  tail -n 20 output/translation_stream.jsonl > test-results/translation_stream_tail.jsonl

4) Trigger with Pi button (GPIO)
- Press the physical button wired to the Pi.
- Watch Pi logs:
  sudo journalctl -u pi-trigger-gpio -f

Expected: "Trigger sent successfully" or "Queued trigger for retry" entries.
Save recent logs:
  sudo journalctl -u pi-trigger-gpio -n 200 > test-results/pi_journal.log

5) Simulate server offline and verify queuing
- Stop server:
  sudo systemctl stop poetry-transformer
- Press Pi button 3–5 times.
- Verify queued file exists and has N lines:
  ls -l pi_queue.jsonl
  wc -l pi_queue.jsonl
  head -n 5 pi_queue.jsonl

Save sample:
  wc -l pi_queue.jsonl > test-results/queue_count.txt
  head -n 200 pi_queue.jsonl > test-results/queue_sample.jsonl

6) Restore server and verify flusher empties queue
- Start server:
  sudo systemctl start poetry-transformer
- Wait RETRY_INTERVAL seconds (default 10s) or watch Pi logs:
  sudo journalctl -u pi-trigger-gpio -f

Expected: queued items flushed (see "Flushed queued trigger" in Pi logs) and pi_queue.jsonl removed or reduced.
Save server logs and stream:
  sudo journalctl -u poetry-transformer -n 200 > test-results/server_journal.log
  tail -n 50 output/translation_stream.jsonl > test-results/translation_stream_after_restore.jsonl

7) Rate-limit verification
- Rapidly POST to exceed rate limit (defaults: 5 requests / 10s):

  for i in $(seq 1 8); do curl -s -o /dev/null -w "%{http_code}\n" -X POST http://<server-host>:8000/trigger; sleep 0.5; done > test-results/rate_test.txt

Expected: some 429 http codes when the limit is exceeded.

8) Collect artifacts

  mkdir -p test-results
  curl -s http://<server-host>:8000/state > test-results/state.json
  tail -n 50 output/translation_stream.jsonl > test-results/translation_stream.jsonl
  sudo journalctl -u poetry-transformer -n 500 > test-results/server_journal.log
  sudo journalctl -u pi-trigger-gpio -n 500 > test-results/pi_journal.log
  if [ -f pi_queue.jsonl ]; then wc -l pi_queue.jsonl > test-results/queue_count.txt; head -n 200 pi_queue.jsonl > test-results/queue_sample.jsonl; fi
  sudo systemctl status pi-trigger-gpio > test-results/pi_service_status.txt
  sudo systemctl status poetry-transformer > test-results/server_service_status.txt

What to provide back to me for diagnosis
- test-results/server_journal.log
- test-results/pi_journal.log
- test-results/translation_stream.jsonl
- test-results/queue_sample.jsonl (if present)
- Outputs of: sudo systemctl status pi-trigger-gpio && sudo systemctl status poetry-transformer

What I will do with the results
- I will analyze the logs and JSONL events and report exactly which steps passed/failed and why, and provide concrete fixes or code changes to resolve any issues.

If you want a single script that runs the artifact collection and packages a tarball, reply "Produce test-results script" and I will add it to the repo.