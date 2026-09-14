# Poetry Transformer

Poetry Transformer displays one poem in a browser and advances its translation
one action at a time when you press Space. The page uses ordinary HTTP: it
loads the current poem from `GET /state`, then each `POST /trigger` waits for
one action and returns the updated poem. After a poem completes its full
outward-and-return journey, the following trigger selects another active poem.

## Run locally

1. Open a terminal and enter the project:

   ```sh
   cd /Users/taryn/RealDesktop/coding/poetry-transformer
   ```

2. Create or edit `.env` in that directory:

   ```text
   OPENAI_API_KEY="sk-your-key-here"
   ```

   You may also set `OPENAI_MODEL`. Do not commit `.env`.

3. Start the app:

   ```sh
   ./run_local.sh
   ```

   The script creates `.venv` when needed, installs the requirements, and
   starts the FastAPI server.

4. Open:

   - Live poem: http://localhost:8000/
   - Add a poem: http://localhost:8000/add.html
   - Poem library: http://localhost:8000/poems

5. Press Space on the live page to advance exactly one translation action.
   Press Ctrl-C in the terminal to stop the server.

## Add a poem

Open `/add.html`, then:

1. Enter an optional title.
2. Choose the language of the original poem.
3. Enter the original poem.
4. Optionally enter your own final target-language translation. When supplied,
   this is the rendering the outward journey ends on.
5. Use `/` between lines and `//` for a blank line between stanzas. Real line
   breaks also work.
6. Select **Load Poem**.

Loading saves the poem and immediately makes it the displayed poem.

## Manage the poem library

Open `/poems` to see every saved poem.

- **In rotation** controls whether the automatic sequence can select the poem.
  Switching a poem off preserves the poem but skips it during rotation.
- Open a poem at `/poems/{id}` to edit its title, original language, original
  text, target language, or chosen final translation. Select **Save poem** to
  update that same poem record in place. Clear the final-translation field and
  save to remove the chosen target.
- The same edit page has Stage 1 words, Stage 2 phrases, and Stage 3 variations
  sections. Every new model result is recorded there automatically. Model
  results can be edited or deleted, and readings can also be added by hand.
- **Show this poem now** immediately replaces the poem on the live page. This
  does not change whether the poem is in the active rotation.
- **Delete this poem** permanently removes that poem record. The currently
  displayed poem cannot be deleted; first use **Show this poem now** on a
  different poem, then return to the old poem and delete it.

## Edit a poem

1. Open `/poems`.
2. Select the poem title or **Open**.
3. Change the title, languages, original poem, or chosen final translation.
4. Select **Save poem**.
5. In any stage section, select **Add**, enter its source, authored reading,
   and optional note, then **Save**. Every saved model or hand-authored record
   has **Edit** and **Delete** controls.

The same poem id is retained. If that poem is currently displayed, saving also
restarts the server's live transformation state from the edited source and
languages. A live page already open in another tab does not receive push
updates; reload that page to display the edited starting state. An edit is
rejected if it would duplicate another poem's exact source text and language
pair.

## What is saved

The SQLite database stores:

- authored source/start text
- optional user-authored target/final translation
- title
- source and target languages
- active rotation flag and necessary record metadata
- every Stage 1 word result, including source word, alternatives, journey,
  stage order, and notes
- every Stage 2 phrase result, including its source scrap, journey, stage
  order, and notes
- every Stage 3 full-poem variation, including its source poem, journey,
  stage order, and notes
- readings explicitly added by a person
- translation request history and enabled translation caches

Presentation events are also appended to `output/translation_stream.jsonl`.
The previous unwanted data was cleaned once: 37 old stage rows, 38 word-cache
rows, 10 phrase-cache rows, 728 history rows, and the old JSONL stream were
deleted while poems 8, 9, and 10 were retained. New API output is recorded from
that clean point forward.

## HTTP behavior

- `GET /state` returns the current presentation snapshot for initial page load.
- `POST /trigger` waits for and returns exactly one completed action. Concurrent
  requests are serialized by the server.
- `POST /load_poem` saves and displays an authored poem.
- `GET /languages` lists supported source and target languages.
- `GET /api/poems` and `GET /api/poems/{id}` return saved poem records.
- `POST /api/poems/{id}/iterations` adds a hand-authored stage record.
- `PATCH /api/iterations/{id}` edits a saved model or hand-authored record.
- `DELETE /api/iterations/{id}` deletes a saved model or hand-authored record.
- `PATCH /api/poems/{id}` edits authored poem fields and/or the active flag in
  place. When the poem is live, the response also includes its reset
  presentation event.
- `POST /api/poems/{id}/live` displays that saved poem immediately.
- `DELETE /api/poems/{id}` deletes a non-displayed poem.

## Deploy on Render

Create a Python web service with:

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn server:app --host 0.0.0.0 --port $PORT`
- Environment variable: `OPENAI_API_KEY`

You may also set `OPENAI_MODEL`. Do not set `SERVER_URL` on the web service;
the browser uses same-origin HTTP requests. `SERVER_URL` is only for an
external Raspberry Pi trigger client and should point that client at the
deployed service.

Render web-service filesystems are ephemeral. This project currently uses a
local SQLite database, so poem records will not survive deploy replacement,
restart, or spin-down unless persistent database storage is added.

## Raspberry Pi trigger

`pi_trigger.py` and `pi_trigger_gpio.py` send ordinary `POST /trigger`
requests. Set `SERVER_URL` in the external Pi process to the app URL. The web
service itself does not need that variable.
