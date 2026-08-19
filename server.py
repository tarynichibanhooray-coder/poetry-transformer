from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import asyncio
import json
import os
from pathlib import Path
from typing import Dict, List, Optional
import random

import config

from poem_transformer_engine import PoemTransformerEngine, TransformationPhase


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
# The poem currently on screen, so "next" can walk the library.
current_poem_id = None

# Synonym cycling config
SYNONYM_CYCLE_INTERVAL = float(os.environ.get("SYNONYM_CYCLE_INTERVAL", "1.0"))
LOG_INTERMEDIATE_SYNONYMS = os.environ.get("LOG_INTERMEDIATE_SYNONYMS", "false").lower() in ("1", "true", "yes")

# Lock to serialize synonym cycles so they don't overlap
_cycle_lock = asyncio.Lock()

OPENING_POEM = {
    "title": "Libro de las preguntas",
    "raw_text": "Dime, la rosa está desnuda\no sólo tiene ese vestido?",
    "final_translation": "Tell me, is the rose naked\nor is that her only dress?",
    "source_language": config.SOURCE_LANGUAGE,
    "source_language_code": config.SOURCE_LANGUAGE_CODE,
    "target_language": config.TARGET_LANGUAGE,
    "target_language_code": config.TARGET_LANGUAGE_CODE,
}


def _stage_stored_poem(stored_poem: Dict, broadcast: bool = True) -> Dict:
    """Initialize the engine from a saved poem, optionally telling clients."""
    global current_poem_id

    language_pair = {
        "source_language": stored_poem.get("source_language") or engine.source_language,
        "source_language_code": stored_poem.get("source_language_code") or engine.source_language_code,
        "target_language": stored_poem.get("target_language") or engine.target_language,
        "target_language_code": stored_poem.get("target_language_code") or engine.target_language_code,
    }

    engine.initialize_poem_with_text(
        stored_poem["raw_text"],
        final_translation=stored_poem.get("final_translation"),
        **language_pair
    )
    current_poem_id = stored_poem["id"]

    if broadcast:
        event = {
            "sequence_index": 0,
            "timestamp": None,
            "unit_level": "poem",
            "unit_path": None,
            "previous_state": None,
            **_render_snapshot(),
            "reason": "poem_loaded",
            "confidence": 1.0,
            "alternatives": [],
            "triggered_by_context": False,
            "context_snapshot": {
                "total_words": len(engine.original_poem_words),
                "poem_id": current_poem_id,
                "phase": engine.get_current_phase().name,
                **language_pair
            }
        }
        _append_event_to_jsonl(event)
        asyncio.create_task(_broadcast_event(event))

    return {"status": "ok", "poem_id": current_poem_id, **language_pair}


def _ensure_opening_poem() -> None:
    """Put a poem on stage as soon as the server starts, with no click required.

    A random saved poem if the library has any; otherwise the default rose
    couplet, which is stored so Next has something to walk.
    """
    poems = engine.database_manager.retrieve_all_poem_entries()
    if not poems:
        poem_id = engine.database_manager.store_or_update_poem_entry(
            raw_text=OPENING_POEM["raw_text"],
            title=OPENING_POEM["title"],
            final_translation=OPENING_POEM["final_translation"],
            source_language=OPENING_POEM["source_language"],
            source_language_code=OPENING_POEM["source_language_code"],
            target_language=OPENING_POEM["target_language"],
            target_language_code=OPENING_POEM["target_language_code"],
        )
        stored = engine.database_manager.retrieve_poem_entry_by_id(poem_id)
        if stored:
            _stage_stored_poem(stored, broadcast=False)
        return

    _stage_stored_poem(random.choice(poems), broadcast=False)


_ensure_opening_poem()


class LoadPoemRequest(BaseModel):
    """Payload for loading a poem, including the language it was written in."""
    poem: str
    title: Optional[str] = None
    source_language_code: Optional[str] = None
    target_language_code: Optional[str] = None
    stanza_delimiter: Optional[str] = None
    # The translation the poem should come to rest on. Left out, the closing
    # pass writes its own.
    final_translation: Optional[str] = None


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


def _render_snapshot(words: List[str] = None) -> Dict:
    """Slot-aligned rendering data for clients.

    The state string alone is ambiguous once a slot holds a multi-word
    translation, because splitting it on whitespace no longer lines up with
    word indices. Sending the slots lets a client map a word index to the
    exact span it should highlight.
    """
    words = engine.current_words if words is None else words
    return {
        "new_state": engine.rebuild_transformation_state(words),
        "words": list(words),
        "separators": list(engine.word_separators),
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

    # The phase this change belongs to. Settling the last word moves the engine
    # on to Phase 2, so reading it afterwards would mislabel the event.
    acting_phase = engine.get_current_phase().name

    original_word = engine.original_poem_words[word_index]

    # Fetch translation and synonyms (may populate cache). The call is
    # blocking, so it runs off the event loop to keep broadcasts flowing.
    translation_data = await asyncio.to_thread(
        engine.get_or_fetch_word_translation_with_synonyms,
        original_word,
        engine.get_original_line_for_word_index(word_index)
    )
    synonyms_list = translation_data.get('synonyms') or []
    primary = translation_data.get('target_word') or translation_data.get('primary_translation') or (synonyms_list[0] if synonyms_list else original_word)

    # Deduplicate while preserving order
    seen = set()
    dedup_synonyms = []
    for s in synonyms_list:
        if s not in seen:
            dedup_synonyms.append(s)
            seen.add(s)
    # If no synonyms, just set primary and finish
    if not dedup_synonyms:
        engine.replace_word_in_transformation_state(word_index, primary)
        engine.word_synonym_cycle_index[word_index] = 0
        engine.note_phase_1_word_completed()

        event = {
            "sequence_index": seq_idx_start,
            "timestamp": None,
            "unit_level": "poem",
            "unit_path": None,
            "previous_state": prev_state,
            **_render_snapshot(),
            "reason": "trigger",
            "confidence": 0.8,
            "alternatives": [],
            "triggered_by_context": False,
            "context_snapshot": {
                "word_index": word_index,
                "phase": acting_phase,
                "phase_after": engine.get_current_phase().name,
            }
        }
        _append_event_to_jsonl(event)
        await _broadcast_event(event)
        sequence_index += 1
        return

    # Broadcast each synonym in place (intermediate). Do not persist intermediates unless configured.
    for syn in dedup_synonyms:
        inter_event = {
            "sequence_index": None,
            "timestamp": None,
            "unit_level": "poem",
            "unit_path": None,
            "previous_state": prev_state,
            **_render_snapshot(engine.preview_word_slots(word_index, syn)),
            "reason": "synonym_cycle",
            "confidence": 0.0,
            "alternatives": dedup_synonyms,
            "intermediate": True,
            "triggered_by_context": False,
            "context_snapshot": {
                "word_index": word_index,
                "phase": acting_phase,
                "phase_after": acting_phase,
            }
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

    engine.note_phase_1_word_completed()

    # Final event — persist and broadcast
    event = {
        "sequence_index": seq_idx_start,
        "timestamp": None,
        "unit_level": "poem",
        "unit_path": None,
        "previous_state": prev_state,
        **_render_snapshot(),
        "reason": "trigger",
        "confidence": 0.8,
        "alternatives": dedup_synonyms,
        "triggered_by_context": False,
        "context_snapshot": {
            "word_index": word_index,
            "phase": acting_phase,
            "phase_after": engine.get_current_phase().name,
        }
    }

    _append_event_to_jsonl(event)
    await _broadcast_event(event)
    sequence_index += 1


async def _run_block_trigger(seq_idx_start: int, prev_state: str):
    """Advance one block-level trigger, for the phases after word-by-word.

    Gathering and the return rewrite a whole span at once, so there is nothing
    to cycle through: a single event carries the new state.
    """
    global sequence_index

    acting_phase = engine.get_current_phase().name
    await asyncio.to_thread(engine.process_next_sensor_trigger)

    if engine.last_action_phase:
        acting_phase = engine.last_action_phase.name

    start_index, end_index = engine.last_changed_span or (None, None)

    event = {
        "sequence_index": seq_idx_start,
        "timestamp": None,
        "unit_level": "poem",
        "unit_path": None,
        "previous_state": prev_state,
        **_render_snapshot(),
        # What the pass said it bettered, so a run can be read back as a
        # record of the decisions and not only of their results.
        "reason": engine.last_block_improvement or "trigger",
        "confidence": 0.8,
        # The versions the closing pass wrote and chose between, kept in the
        # stream so a run can be read back with its roads not taken.
        "alternatives": ['\n'.join(draft) for draft in engine.last_block_drafts],
        "triggered_by_context": False,
        "context_snapshot": {
            "phase": acting_phase,
            "phase_after": engine.get_current_phase().name,
            "block_start": start_index,
            "block_end": end_index,
            **_current_language_pair(),
        }
    }

    _append_event_to_jsonl(event)
    await _broadcast_event(event)
    sequence_index += 1


@app.post("/trigger")
async def trigger():
    """Advance the transformation by one trigger and broadcast the change.

    In Phase 1 a trigger picks the next word from the poem's shuffled order and
    cycles its synonyms, broadcasting intermediates at SYNONYM_CYCLE_INTERVAL
    before the final choice is appended to the JSONL. After that a trigger
    rewrites one block, first gathering toward the target and later, once the
    target is on the page, working the poem back into the original language.

    The work runs as a background task so the request returns immediately;
    clients see the result over the WebSocket.
    """
    if not engine.original_poem_words:
        raise HTTPException(status_code=400, detail="No poem loaded")

    async def _task():
        # One lock across every phase. Without it, triggers arriving in quick
        # succession would interleave and rewrite the same part of the poem.
        async with _cycle_lock:
            if engine.get_current_phase() == TransformationPhase.COMPLETE:
                return

            prev_state = engine.get_current_transformation_state()

            in_phase_1 = (
                engine.get_current_phase() == TransformationPhase.PHASE_1_WORD_BY_WORD
            )
            word_index = engine.claim_next_phase_1_word_index() if in_phase_1 else None

            if word_index is None:
                await _run_block_trigger(sequence_index, prev_state)
                return

            await _run_synonym_cycle_for_word(word_index, sequence_index, prev_state)

    asyncio.create_task(_task())

    return {"status": "accepted"}


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

    language_pair = {
        "source_language": source["name"] if source else engine.source_language,
        "source_language_code": source_code,
        "target_language": target["name"] if target else engine.target_language,
        "target_language_code": target_code,
    }

    # Saving before loading, so a poem loaded again without its final
    # translation typed out still ends where it was always meant to.
    poem_id = engine.database_manager.store_or_update_poem_entry(
        raw_text=poem,
        title=payload.title,
        stanza_delimiter=payload.stanza_delimiter,
        final_translation=(payload.final_translation or "").strip() or None,
        **language_pair
    )
    stored_poem = engine.database_manager.retrieve_poem_entry_by_id(poem_id) or {
        "id": poem_id,
        "raw_text": poem,
        "final_translation": (payload.final_translation or "").strip() or None,
        **language_pair
    }
    return _stage_stored_poem(stored_poem)


@app.post("/next_poem")
async def next_poem():
    """Put the next saved poem on stage, wrapping around the library."""
    poems = engine.database_manager.retrieve_all_poem_entries()
    if not poems:
        raise HTTPException(status_code=404, detail="No poems saved yet")

    # The list comes newest-first. Reverse so "next" walks in the order they
    # were added, then around again.
    poems = list(reversed(poems))
    ids = [poem["id"] for poem in poems]

    if current_poem_id in ids:
        next_index = (ids.index(current_poem_id) + 1) % len(ids)
    else:
        next_index = 0

    return _stage_stored_poem(poems[next_index])


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
            **_render_snapshot(),
            "reason": "initial_state",
            "confidence": 1.0,
            "alternatives": [],
            "triggered_by_context": False,
            "context_snapshot": {
                "phase": engine.get_current_phase().name,
                **_current_language_pair()
            }
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
