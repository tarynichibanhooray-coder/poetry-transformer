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

Deploying to a simple host (Render / Railway / similar)
- Push this repository to GitHub and connect your host (Render, Railway).
- Set the start/launch command to:

  .venv/bin/uvicorn server:app --host 0.0.0.0 --port $PORT

  or if the host provides its own Python install, use:

  uvicorn server:app --host 0.0.0.0 --port $PORT

- If you enable API key protection later, add the API key as an environment variable on the host.

Exposing a Pi to the internet (optional)
- If you run the server on a Pi but need public access, use a tunnel service such as Cloudflare Tunnel or ngrok. This avoids opening ports on your router.

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

If you want
- I can implement API key enforcement and show an example of how to call `/trigger` with the header.
- I can add a simple retry queue for `pi_trigger.py` so it buffers triggers while offline and retries when online.
- I can add rate-limiting or basic auth for `/trigger`.

What should I do next?