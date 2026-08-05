# Poetry Transformer — Run & Deploy

This repository includes a small FastAPI server that runs the PoemTransformer engine, streams transformation events to connected web clients, and provides a minimal web UI that triggers the engine when the user presses Space.

Files of interest
- `server.py` — FastAPI server with endpoints:
  - `POST /trigger` — advance the transformation by one step
  - `POST /load_poem` — load poem text (JSON payload: {"poem": "text"})
  - `GET /state` — current poem state and stats
  - `WebSocket /ws` — real-time event stream (initial state + subsequent events)
  - Also serves the static UI at `/` from `static/index.html`.
- `static/index.html` — tiny web UI that connects to `/ws` and POSTs `/trigger` on Space.
- `pi_trigger.py` — simple Raspberry Pi client that POSTs `/trigger` when Space (or a button) is pressed.
- `run_local.sh` — single-command local runner (creates venv, installs dependencies, runs uvicorn).
- `requirements.txt` — Python dependencies.

Important note
- The `POST /trigger` handler currently includes a TODO comment where an API key check should be implemented. You can test locally without any API key; enable the key before public deployment.

Quick start — run locally (recommended)
1. Make the script executable and run the single command:

   chmod +x run_local.sh
   ./run_local.sh

   This will create a Python virtual environment (`.venv`), install dependencies, and start uvicorn with:
   `.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8000 --reload`.

2. Open the UI in your browser:

   http://localhost:8000/

   - The page will open a WebSocket to `ws://localhost:8000/ws` and show the current poem state.
   - Press Space (or click the "Trigger" button) to advance the poem. Each trigger is broadcast to all connected clients and appended to `output/translation_stream.jsonl`.

API examples (local)
- Trigger via curl:

  curl -X POST http://localhost:8000/trigger

- Load a poem:

  curl -X POST http://localhost:8000/load_poem -H "Content-Type: application/json" -d '{"poem":"Two roads diverged in a yellow wood"}'

- Get current state:

  curl http://localhost:8000/state

Raspberry Pi usage
Option A — Pi runs the full server (authoritative)
- Clone this repo on the Pi and run the same `./run_local.sh`.
- Browse to `http://<pi-ip>:8000/` from any device on the same network.

Option B — Pi as a trigger client (server is remote)
- If the central server is hosted remotely, configure the Pi to call that server by setting `SERVER_URL` environment variable:

  export SERVER_URL="https://yourserver.example"
  python3 pi_trigger.py

- `pi_trigger.py` will POST `/trigger` to the server when Space is pressed. If the Pi is offline, consider extending `pi_trigger.py` with a local queue and retry logic.

Offline/Intermittent connectivity patterns
- If the Pi is frequently offline and you still need immediate transforms, run the engine locally on the Pi (Option A) so it is authoritative while offline.
- Alternatively, have the Pi append triggers to a local JSONL and sync/replay when online.

Serving the static UI
- `server.py` now mounts the `static/` directory and will serve `static/index.html` at `/` — you do not need an external static server when running `uvicorn server:app`.

GPIO wiring and Raspberry Pi headless setup
- Purpose: The Pi acts as a headless trigger source using a physical button. The web UI sends the same POST /trigger when the user presses Space; the server is the single authority.

Hardware wiring (BCM numbering)
- Default button pin: GPIO17 (BCM 17). Adjust BUTTON_PIN in the systemd unit or export BUTTON_PIN in the environment if you use a different pin.
- Wiring with internal pull-up (recommended):
  - Connect one leg of the momentary push-button to GPIO17.
  - Connect the other leg to any GND pin on the Pi.
  - When pressed, the GPIO pin is pulled to ground and the script (with pull_up=True) detects the press.

Alternative wiring (external resistor / pull-down)
- If you prefer an external pull-down resistor, wire the button between 3.3V and the GPIO pin and set pull_up=False in the script.

Software and dependencies on the Pi
1) Clone and create venv

   cd /home/pi
   git clone https://github.com/tarynichibanhooray-coder/poetry-transformer.git
   cd poetry-transformer
   python3 -m venv .venv
   . .venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   pip install gpiozero

2) Confirm GPIO script and service are present

   ls -l pi_trigger_gpio.py systemd/pi-trigger-gpio.service

Systemd unit installation (copy from repo)

   sudo cp systemd/pi-trigger-gpio.service /etc/systemd/system/pi-trigger-gpio.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now pi-trigger-gpio
   sudo systemctl status pi-trigger-gpio
   sudo journalctl -u pi-trigger-gpio -f

Service environment variables (edit with systemctl override)
- To change the SERVER_URL, BUTTON_PIN, or PI_RETRY_INTERVAL use:

  sudo systemctl edit --full pi-trigger-gpio
  # edit Environment= lines or add new ones
  sudo systemctl daemon-reload
  sudo systemctl restart pi-trigger-gpio

GPIO testing notes
- Run the script manually while connected to a display or SSH with X11/TCP forwarded if you want to observe prints.
- For headless testing, examine the journal logs above.

Systemd & permissions
- The service runs as user `pi` in the example. Ensure the `pi` user has access to the repo directory and GPIO (gpiozero typically works as pi user).
- If you run as another user, ensure that user has access to GPIO (group gpio or run as root).

Deploying to a simple host (Render / Railway / similar)
- Push this repository to GitHub and connect your host (Render, Railway).
- Set the start/launch command to:

  .venv/bin/uvicorn server:app --host 0.0.0.0 --port $PORT

  or if the host provides its own Python install, use:

  uvicorn server:app --host 0.0.0.0 --port $PORT

- If you enable API key protection later, add the API key as an environment variable on the host.

Systemd unit example (Raspberry Pi)
- Create `/etc/systemd/system/poetry-transformer.service` with:

  [Unit]
  Description=Poetry Transformer FastAPI server
  After=network.target

  [Service]
  Type=simple
  User=pi
  WorkingDirectory=/home/pi/poetry-transformer
  ExecStart=/home/pi/poetry-transformer/.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8000
  Restart=on-failure

  [Install]
  WantedBy=multi-user.target

- Then enable and start:

  sudo systemctl daemon-reload
  sudo systemctl enable poetry-transformer
  sudo systemctl start poetry-transformer

Security notes
- The `/trigger` endpoint currently has a TODO comment for API key validation (`TODO: implement API key validation here (require API key in headers or form data)`).
- Before exposing the server publicly, implement and enable API key or other authentication, enable TLS (HTTPS), and restrict access where appropriate.

WebSocket vs SSE vs Polling — short rationale
- WebSocket (used here) provides low-latency bidirectional messaging. The server can push each event to all connected browsers immediately for a shared live view; browsers can also send messages on the same socket (if you add that later).
- SSE (Server-Sent Events) is simpler and unidirectional (server -> client). Use SSE if you only need pushes from server and want a simpler implementation.
- Polling is the simplest but least efficient approach (clients repeatedly GET `/state`). Use polling only for very small scale or if real-time low-latency is not required.

Troubleshooting
- If the UI shows "Disconnected" or fails to connect, check:
  - Is the server running on the expected host/port?
  - Browser security: if connecting from a different origin to `ws://`/`wss://`, ensure CORS/WSS settings are correct.
  - Check server logs printed by `uvicorn`.

GPIO test plan (end-to-end verification)
This test plan verifies the full flow: button press on Pi → POST /trigger → server advances poem → Web UI updates. Run these steps while your server and web client are up.

Prerequisites
- Server running on `http://<server-host>:8000` (run locally or on Pi). The web UI should be reachable at that address.
- Pi with `pi_trigger_gpio.py` installed and systemd service enabled (if using service mode).
- A browser open to `http://<server-host>:8000/` with DevTools console available.

Test steps
1) Verify server health
   curl http://<server-host>:8000/state
   Expected: JSON with "current_state" and "stats" fields.

2) Open web UI and confirm initial state
   - Open http://<server-host>:8000/ in a browser.
   - In the DevTools Console, ensure WebSocket connects (look for "Connected" in the page status).
   - The poem area should show the current state from server (initial state).

3) Trigger with web UI (Space)
   - Press Space or click the Trigger button in the browser.
   - Expected: The poem text updates immediately in the browser to a new state.
   - Check server log: uvicorn should show an incoming POST /trigger.
   - Check output file: tail -n 5 output/translation_stream.jsonl should show a new event.

4) Trigger with Pi button
   - Press the physical button wired to the Pi.
   - Expected: The server receives POST /trigger (check server logs or tail the JSONL), and the poem in the browser updates if connected.
   - Check Pi logs: sudo journalctl -u pi-trigger-gpio -f should show the attempt and either "Trigger sent successfully" or "Queued trigger for retry".

5) Simulate server offline and verify queuing
   - Stop the server temporarily: sudo systemctl stop poetry-transformer (or kill uvicorn).
   - Press the Pi button multiple times.
   - Expected: pi_queue.jsonl contains one line per press. On the Pi, cat pi_queue.jsonl should show JSON payloads.

6) Restore server and verify flusher
   - Start server: sudo systemctl start poetry-transformer
   - Wait RETRY_INTERVAL seconds and watch the Pi journal; queued triggers should be flushed and removed from pi_queue.jsonl.
   - Check server output JSONL to confirm events were processed.

7) Verify rate limit handling
   - Rapidly press the Pi button or call curl POST /trigger more than RATE_LIMIT_MAX_REQUESTS within RATE_LIMIT_WINDOW_SECONDS.
   - Expected: Server returns HTTP 429 on some requests; Pi flusher logs the 429 and keeps those items for retry.

8) Clean up
   - Remove queue files if desired: rm pi_queue.jsonl
   - Re-enable server and services as needed.

If any step fails, collect these logs and share them:
- Server logs: journalctl -u poetry-transformer (or uvicorn console output)
- Pi service logs: journalctl -u pi-trigger-gpio
- Contents of output/translation_stream.jsonl

If you want, I’ll now commit this updated README to main. Reply exactly: Commit README GPIO & test plan to main