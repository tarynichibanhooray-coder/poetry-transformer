from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import asyncio
import json
import os
from pathlib import Path
from typing import Dict, List, Optional

import config

from poem_transformer_engine import (
    PoemTransformerEngine,
    TransformationPhase,
    join_words_with_separators,
    split_words_and_separators,
)


config.validate_required_settings()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

OUTPUT_JSONL_PATH = BASE_DIR / "output" / "translation_stream.jsonl"
OUTPUT_JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
# Ensure file exists
if not OUTPUT_JSONL_PATH.exists():
    OUTPUT_JSONL_PATH.write_text("")


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        try:
            self.active_connections.remove(websocket)
        except ValueError:
            pass

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        to_remove = []
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except Exception:
                to_remove.append(connection)
        for c in to_remove:
            self.disconnect(c)


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = ConnectionManager()
engine = PoemTransformerEngine()
sequence_index = 1

# Synonym cycling config
SYNONYM_CYCLE_INTERVAL = float(os.environ.get("SYNONYM_CYCLE_INTERVAL", "1.0"))
LOG_INTERMEDIATE_SYNONYMS = os.environ.get("LOG_INTERMEDIATE_SYNONYMS", "false").lower() in ("1", "true", "yes")

# Lock to serialize synonym cycles so they don't overlap
_cycle_lock = asyncio.Lock()


class LoadPoemRequest(BaseModel):
    """Payload for loading a poem, including the language it was written in."""
    poem: str
    title: Optional[str] = None
    source_language_code: Optional[str] = None
    target_language_code: Optional[str] = None
    stanza_delimiter: Optional[str] = None


def _resolve_language(code: Optional[str], supported: List[dict], label: str) -> Optional[dict]:
    """Look up a language by ISO code, rejecting codes the app doesn't support.

    Unknown codes are refused rather than passed through, since a typo would
    silently create its own partition of the translation cache.
    """
    if not code:
        return None

    for language in supported:
        if language["code"] == code:
            return language

    supported_codes = ", ".join(language["code"] for language in supported)
    raise HTTPException(
        status_code=400,
        detail=f"Unsupported {label} language code '{code}'. Expected one of: {supported_codes}"
    )


def _current_language_pair() -> Dict[str, str]:
    return {
        "source_language": engine.source_language,
        "source_language_code": engine.source_language_code,
        "target_language": engine.target_language,
        "target_language_code": engine.target_language_code,
    }


def _append_event_to_jsonl(event: dict) -> None:
    try:
        with OUTPUT_JSONL_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"✗ Failed to write event to JSONL: {e}")


async def _broadcast_event(event: dict) -> None:
    await manager.broadcast(json.dumps(event, ensure_ascii=False))


async def _run_synonym_cycle_for_word(word_index: int, seq_idx_start: int, prev_state: str):
    """Run the synonym cycle for a single word index.

    Broadcasts intermediate states at SYNONYM_CYCLE_INTERVAL and appends only the final settled event.
    """
    global sequence_index

    # Validate index
    if word_index < 0 or word_index >= len(engine.original_poem_words):
        # Nothing to do — out of range
        return

    original_word = engine.original_poem_words[word_index]

    # Fetch translation and synonyms (may populate cache)
    translation_data = engine.get_or_fetch_word_translation_with_synonyms(original_word)
    synonyms_list = translation_data.get('synonyms') or []
    primary = translation_data.get('target_word') or translation_data.get('primary_translation') or (synonyms_list[0] if synonyms_list else original_word)

    # Deduplicate while preserving order
    seen = set()
    dedup_synonyms = []
    for s in synonyms_list:
        if s not in seen:
            dedup_synonyms.append(s)
            seen.add(s)
    if primary not in seen:
        # ensure primary is shown as final choice if it's not already in the list
        # We will still show synonyms first, then primary as final
        final_on_primary = True
    else:
        final_on_primary = False

    # If no synonyms, just set primary and finish
    if not dedup_synonyms:
        engine.replace_word_in_transformation_state(word_index, primary)
        engine.word_synonym_cycle_index[word_index] = 0
        engine.trigger_count += 1

        # Possibly transition phase if we've exhausted phase 1
        if engine.trigger_count >= len(engine.original_poem_words):
            engine.transition_to_phase_2_pairs()

        event = {
            "sequence_index": seq_idx_start,
            "timestamp": None,
            "unit_level": "poem",
            "unit_path": None,
            "previous_state": prev_state,
            "new_state": engine.get_current_transformation_state(),
            "reason": "trigger",
            "confidence": 0.8,
            "alternatives": [],
            "triggered_by_context": False,
            "context_snapshot": {}
        }
        _append_event_to_jsonl(event)
        await _broadcast_event(event)
        sequence_index += 1
        return

    # Broadcast each synonym in place (intermediate). Do not persist intermediates unless configured.
    for syn in dedup_synonyms:
        temp_words, temp_separators = split_words_and_separators(
            engine.get_current_transformation_state()
        )
        temp_words[word_index] = syn
        temp_state = join_words_with_separators(temp_words, temp_separators)

        inter_event = {
            "sequence_index": None,
            "timestamp": None,
            "unit_level": "poem",
            "unit_path": None,
            "previous_state": prev_state,
            "new_state": temp_state,
            "reason": "synonym_cycle",
            "confidence": 0.0,
            "alternatives": dedup_synonyms,
            "intermediate": True,
            "triggered_by_context": False,
            "context_snapshot": {"word_index": word_index}
        }

        # Broadcast intermediate
        await _broadcast_event(inter_event)

        # Optionally log intermediate to JSONL
        if LOG_INTERMEDIATE_SYNONYMS:
            # Use a sequence index for logged intermediates as well
            inter_event_logged = inter_event.copy()
            inter_event_logged['sequence_index'] = sequence_index
            _append_event_to_jsonl(inter_event_logged)
            sequence_index += 1

        # Wait before showing next synonym
        await asyncio.sleep(SYNONYM_CYCLE_INTERVAL)

    # After cycling synonyms, set final word. If primary not in synonyms, make sure final shows primary
    final_choice = primary

    engine.replace_word_in_transformation_state(word_index, final_choice)

    # Update cycle index for word (set to index of final in synonyms if present)
    try:
        idx = dedup_synonyms.index(final_choice)
        engine.word_synonym_cycle_index[word_index] = (idx + 1) % max(1, len(dedup_synonyms))
    except ValueError:
        # Not found in dedup list
        engine.word_synonym_cycle_index[word_index] = 0

    # Advance trigger count and possibly transition phase
    engine.trigger_count += 1
    if engine.trigger_count >= len(engine.original_poem_words):
        engine.transition_to_phase_2_pairs()

    # Final event — persist and broadcast
    event = {
        "sequence_index": seq_idx_start,
        "timestamp": None,
        "unit_level": "poem",
        "unit_path": None,
        "previous_state": prev_state,
        "new_state": engine.get_current_transformation_state(),
        "reason": "trigger",
        "confidence": 0.8,
        "alternatives": dedup_synonyms,
        "triggered_by_context": False,
        "context_snapshot": {"word_index": word_index}
    }

    _append_event_to_jsonl(event)
    await _broadcast_event(event)
    sequence_index += 1


@app.post("/trigger")
async def trigger(request: Request):
    """Advance transformation by one trigger and broadcast the visible change.

    For Phase 1 word-by-word, a single trigger starts a synonym cycle for the next word. Intermediates are
    broadcast to connected clients at SYNONYM_CYCLE_INTERVAL, and the final choice is appended to the JSONL.

    For later phases, the original process_next_sensor_trigger() behavior is preserved.
    """
    global sequence_index

    # capture previous state snapshot
    prev_state = engine.get_current_transformation_state()

    # If not in Phase 1, fall back to original behavior
    if engine.get_current_phase() != TransformationPhase.PHASE_1_WORD_BY_WORD:
        new_state = engine.process_next_sensor_trigger()

        event = {
            "sequence_index": sequence_index,
            "timestamp": None,
            "unit_level": "poem",
            "unit_path": None,
            "previous_state": prev_state,
            "new_state": new_state,
            "reason": "trigger",
            "confidence": 0.8,
            "alternatives": [],
            "triggered_by_context": False,
            "context_snapshot": {}
        }

        _append_event_to_jsonl(event)
        asyncio.create_task(_broadcast_event(event))
        sequence_index += 1
        return {"new_state": new_state}

    # Phase 1 behavior: serialize cycles with a lock so only one cycle runs at a time
    # If engine.trigger_count already past words, fall back to process_next_sensor_trigger()
    if engine.trigger_count >= len(engine.original_poem_words):
        new_state = engine.process_next_sensor_trigger()
        event = {
            "sequence_index": sequence_index,
            "timestamp": None,
            "unit_level": "poem",
            "unit_path": None,
            "previous_state": prev_state,
            "new_state": new_state,
            "reason": "trigger",
            "confidence": 0.8,
            "alternatives": [],
            "triggered_by_context": False,
            "context_snapshot": {}
        }
        _append_event_to_jsonl(event)
        asyncio.create_task(_broadcast_event(event))
        sequence_index += 1
        return {"new_state": new_state}

    # Determine which word to cycle for this trigger (do not increment trigger_count here)
    word_index = engine.trigger_count

    # Create task to run cycle but serialize using lock
    async def _task():
        async with _cycle_lock:
            # Use current sequence_index value for final event index
            seq_idx = sequence_index
            await _run_synonym_cycle_for_word(word_index, seq_idx, prev_state)

    asyncio.create_task(_task())

    # Return accepted — the full cycle will run asynchronously and clients will receive intermediate/broadcasts
    return {"status": "accepted", "word_index": word_index}


@app.get("/languages")
async def languages():
    """List the language pairs a poem can be entered with."""
    return {
        "source_languages": config.SUPPORTED_SOURCE_LANGUAGES,
        "target_languages": config.SUPPORTED_TARGET_LANGUAGES,
        "default_source_code": config.SOURCE_LANGUAGE_CODE,
        "default_target_code": config.TARGET_LANGUAGE_CODE,
    }


@app.get("/poems")
async def poems():
    """List previously saved poems, newest first."""
    return {"poems": engine.database_manager.retrieve_all_poem_entries()}


@app.post("/load_poem")
async def load_poem(payload: LoadPoemRequest):
    """Load poem text into the engine and save it with its language pair."""
    poem = payload.poem.strip()
    if not poem:
        raise HTTPException(status_code=400, detail="Poem text is empty")

    source = _resolve_language(
        payload.source_language_code, config.SUPPORTED_SOURCE_LANGUAGES, "source"
    )
    target = _resolve_language(
        payload.target_language_code, config.SUPPORTED_TARGET_LANGUAGES, "target"
    )

    source_code = source["code"] if source else engine.source_language_code
    target_code = target["code"] if target else engine.target_language_code
    if source_code == target_code:
        raise HTTPException(
            status_code=400,
            detail="Source and target languages must differ"
        )

    engine.initialize_poem_with_text(
        poem,
        source_language=source["name"] if source else None,
        source_language_code=source["code"] if source else None,
        target_language=target["name"] if target else None,
        target_language_code=target["code"] if target else None,
    )

    language_pair = _current_language_pair()

    poem_id = engine.database_manager.store_or_update_poem_entry(
        raw_text=poem,
        title=payload.title,
        stanza_delimiter=payload.stanza_delimiter,
        **language_pair
    )

    event = {
        "sequence_index": 0,
        "timestamp": None,
        "unit_level": "poem",
        "unit_path": None,
        "previous_state": None,
        "new_state": engine.get_current_transformation_state(),
        "reason": "poem_loaded",
        "confidence": 1.0,
        "alternatives": [],
        "triggered_by_context": False,
        "context_snapshot": {
            "total_words": len(engine.original_poem_words),
            "poem_id": poem_id,
            **language_pair
        }
    }

    _append_event_to_jsonl(event)
    asyncio.create_task(_broadcast_event(event))

    return {"status": "ok", "poem_id": poem_id, **language_pair}


@app.get("/state")
async def state():
    return {
        "current_state": engine.get_current_transformation_state(),
        "stats": engine.get_transformation_statistics(),
        **_current_language_pair()
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # send initial state
        init_event = {
            "sequence_index": 0,
            "timestamp": None,
            "unit_level": "poem",
            "unit_path": None,
            "previous_state": None,
            "new_state": engine.get_current_transformation_state(),
            "reason": "initial_state",
            "confidence": 1.0,
            "alternatives": [],
            "triggered_by_context": False,
            "context_snapshot": _current_language_pair()
        }
        await manager.send_personal_message(json.dumps(init_event, ensure_ascii=False), websocket)

        while True:
            # keep connection open; ignore incoming messages
            await websocket.receive_text()

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


# Registered last on purpose: a mount at "/" matches every path and every scope
# type, so any route declared after it would be unreachable.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
