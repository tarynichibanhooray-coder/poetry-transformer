# Poetry Transformer — Run & Deploy

This repository includes a small FastAPI server that runs the PoemTransformer engine, streams transformation events to connected web clients, and provides a minimal web UI that triggers the engine.

Files of interest
- `server.py` — FastAPI server with endpoints:
  - `POST /trigger` — advance the transformation by one step
  - `POST /load_poem` — load and save a poem (JSON payload: `{"poem": "text", "title": "optional", "source_language_code": "es"}`)
  - `GET /state` — current poem state, stats, and active language pair
  - `GET /languages` — source and target languages the app accepts
  - `GET /poems` — previously saved poems, newest first
  - `WebSocket /ws` — real-time event stream (initial state + subsequent events)
  - Also serves the static UI at `/` from `static/index.html`.
- `static/index.html` — tiny web UI that connects to `/ws` and POSTs `/trigger` on Space.
- `static/add.html` — form for adding a poem, with `/`-separated lines and an original-language picker.
- `pi_trigger.py` — simple Raspberry Pi client that POSTs `/trigger` when Space (or a button) is pressed.
- `run_local.sh` — single-command local runner (creates venv, installs dependencies, runs uvicorn).
- `requirements.txt` — Python dependencies. (Updated to include `openai`.)

Important note
- The `POST /trigger` handler currently includes a TODO comment where an API key check should be implemented. You can test locally without any API key; enable the key before public deployment.

Quick start — run locally (recommended)
1. Run the single command:

   ./run_local.sh

   This creates a Python virtual environment (`.venv`), installs dependencies from `requirements.txt`, and starts uvicorn. Override the bind address with `HOST` and `PORT`, e.g. `PORT=8080 ./run_local.sh`.

   To pull the latest `main` first and then start, use `./update_and_run.sh`, which delegates to `run_local.sh` rather than duplicating the launch logic. Note that it checks out `main`, so don't run it from a feature branch.

2. Open the UI in your browser:

   http://localhost:8000/

   - The page will open a WebSocket to `ws://localhost:8000/ws` and show the current poem state.
   - Press Space (or click the "Trigger" button) to advance the poem. Each trigger is broadcast to all connected clients and appended to `output/translation_stream.jsonl`.

Adding poems
- Open http://localhost:8000/add.html (linked from the live view).
- Paste the poem using `/` to separate lines and `//` for a blank line between stanzas. Poems pasted with real line breaks work too.
- Pick the poem's original language. This is stored per poem, feeds the OpenAI prompt, and keys the translation cache, so poems in different languages never share cached words.
- The list of selectable languages comes from `SUPPORTED_SOURCE_LANGUAGES` in `config.py`, served to the page via `GET /languages`. Add a `{"name": ..., "code": ...}` entry there to offer another language.
- Poems are saved to the `poems` table. Re-saving the same text and language pair updates the existing row instead of creating a duplicate.

Environment variables and .env (new)
- Create a `.env` file at the repository root (do NOT commit it). Use the provided `.env.example` as a starting point.

Example `.env`:

```
OPENAI_API_KEY="sk-REPLACE_WITH_YOUR_KEY"
OPENAI_MODEL="gpt-4o"
SERVER_URL="http://localhost:8000"  # optional for pi_trigger
```

- `config.py` loads `.env` automatically, so the key is picked up however you start the app — `run_local.sh`, a bare `uvicorn` command, `main.py`, or a test. No launcher script injects it.
- Real environment variables take precedence over `.env`, so systemd or CI can override it without editing the file.
- If `OPENAI_API_KEY` is missing, the app fails at startup with a clear message instead of starting and then returning an opaque 401 on the first translation.
- `.env` is included in `.gitignore` to avoid accidentally committing secrets.

API examples (local)
- Trigger via curl:

  curl -X POST http://localhost:8000/trigger

- Load a poem:

  curl -X POST http://localhost:8000/load_poem -H "Content-Type: application/json" -d '{"poem":"Two roads diverged in a yellow wood"}'

- Get current state:

  curl http://localhost:8000/state

Raspberry Pi usage
- Refer to the original README for Pi deployment and systemd instructions.

If you'd like I can also open a PR with these changes instead of committing directly to main. Reply: "Create WAL PR" to create a PR or "Done" if you want nothing further.
