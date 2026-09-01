from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import asyncio
import json
import os
from pathlib import Path
from typing import Dict, List, Optional

import config

from poem_rotation import PoemDeck
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
# The poem currently on screen, so "next" knows what it is following.
current_poem_id = None

# The order poems come up in. Shuffled, and every poem in the rotation is
# shown once before any of them comes round again.
poem_deck = PoemDeck()

# Synonym cycling config
# Long enough for a word to fade out and back in before the next synonym.
SYNONYM_CYCLE_INTERVAL = float(os.environ.get("SYNONYM_CYCLE_INTERVAL", "2.4"))
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


def _make_poem_live(stored_poem: Dict, broadcast: bool = True) -> Dict:
    """Make a saved poem the live one, optionally telling connected clients.

    Only one poem is live at a time: the one the screen is showing and the
    one the motion sensor advances.
    """
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
    # Which library row the stages should file their readings under.
    engine.poem_id = current_poem_id

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
    """Make a poem live as soon as the server starts, with no click required.

    The first card off the shuffled deck if the rotation has anything in it,
    so the installation does not open on the same poem every morning.
    Otherwise the default rose couplet, which is stored so Next has
    something to walk. A library where every poem has been switched off is
    treated as an empty one, so the screen starts on the default rather than
    on a poem that was deliberately taken out of the rotation.
    """
    poems = engine.database_manager.retrieve_active_poem_entries()
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
        # The opening poem may already be in the library and switched off,
        # which is how we got here. It cannot become live while it is out of
        # the rotation, so put it back in.
        stored = engine.database_manager.set_poem_active(poem_id, True)
        if stored:
            _make_poem_live(stored, broadcast=False)
        return

    _make_poem_live(poem_deck.deal(poems), broadcast=False)


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
    await manager.broadcast(json.dumps(_event_for_clients(event), ensure_ascii=False))


def _event_for_clients(event: dict) -> dict:
    """Attach the last model exchange for the temporary debug panel."""
    payload = dict(event)
    getter = getattr(engine, "get_last_debug_exchange", None)
    if callable(getter):
        payload["debug"] = getter()
    return payload


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
    engine.begin_debug_trigger()
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

    Gathering rewrites a whole span at once, so there is nothing to cycle
    through: a single event carries the new state. Hitting the target only
    turns the engine around; the reverse word-by-word work starts on the
    next trigger.
    """
    global sequence_index

    acting_phase = engine.get_current_phase().name
    try:
        await asyncio.to_thread(engine.process_next_sensor_trigger)
    except Exception as exc:
        print(f"✗ Trigger failed: {exc}")

    if engine.last_action_phase:
        acting_phase = engine.last_action_phase.name

    start_index, end_index = engine.last_changed_span or (None, None)
    new_state = engine.get_current_transformation_state()
    text_changed = ' '.join((prev_state or '').split()) != ' '.join((new_state or '').split())
    if not text_changed:
        start_index, end_index = None, None

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
        "alternatives": [
            '\n'.join(str(part) for part in draft)
            if isinstance(draft, (list, tuple)) else str(draft)
            for draft in (engine.last_block_drafts or [])
        ],
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


def _change_to_next_poem() -> bool:
    """Put the next poem up once the one on screen has finished.

    The trigger that lands on a finished poem spends itself on the change.
    The new poem goes up in its original language, untranslated, and the
    triggers after it do the translating: one trigger, one action.

    Nothing is asked of the model here. The engine only rebuilds its queues
    around the new text, so a poem change costs nothing.

    Call this with _cycle_lock held. It re-initialises the engine, and every
    other trigger path assumes that state holds still underneath it.
    """
    poems = engine.database_manager.retrieve_active_poem_entries()
    following = poem_deck.deal(poems, previous_id=current_poem_id)
    if following is None:
        # Nothing is switched on, so there is nowhere to move to. Hold the
        # finished poem rather than blanking the wall.
        return False

    # Broadcasts down the same path load_poem and next_poem use, so screens
    # already connected change over without a reload.
    _make_poem_live(following)
    return True


@app.post("/trigger")
async def trigger():
    """Advance the transformation by one trigger and broadcast the change.

    In Phase 1 a trigger picks the next word from the poem's shuffled order and
    cycles its synonyms, broadcasting intermediates at SYNONYM_CYCLE_INTERVAL
    before the final choice is appended to the JSONL. After that a trigger
    rewrites one block, gathering toward the target. Once the target is on the
    page, the next triggers run that same word-then-gather process back toward
    the original language.

    Once a poem has finished its whole journey, the next trigger changes the
    poem instead of translating: the sensor is the only thing driving an
    unattended wall, so the rotation has to turn on it.

    The work runs as a background task so the request returns immediately;
    clients see the result over the WebSocket.
    """
    if not engine.original_poem_words:
        raise HTTPException(status_code=400, detail="No poem loaded")

    async def _task():
        # One lock across every phase. Without it, triggers arriving in quick
        # succession would interleave and rewrite the same part of the poem.
        async with _cycle_lock:
            # Read inside the lock, never captured before it. Two triggers
            # arriving together on a finished poem both queue here; the
            # first changes the poem, and the second must see the new
            # poem's phase rather than the finished one's, or it would deal
            # a second poem and skip one entirely.
            if engine.get_current_phase() == TransformationPhase.COMPLETE:
                _change_to_next_poem()
                return

            prev_state = engine.get_current_transformation_state()

            in_phase_1 = (
                engine.get_current_phase() == TransformationPhase.WORDS
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


STAGE_NAMES = ("words", "phrases", "lines")


class EditPoemRequest(BaseModel):
    """Changes to the poem itself rather than to one of its readings."""
    active: Optional[bool] = None


class NewIterationRequest(BaseModel):
    """A reading typed in by hand rather than returned by the model."""
    stage: str
    content: str
    source_text: Optional[str] = None
    note: Optional[str] = None
    journey: Optional[str] = "out"


class EditIterationRequest(BaseModel):
    """A correction to a reading already on the record."""
    content: Optional[str] = None
    source_text: Optional[str] = None
    note: Optional[str] = None


def _require_poem(poem_id: int) -> Dict:
    poem = engine.database_manager.retrieve_poem_entry_by_id(poem_id)
    if not poem:
        raise HTTPException(status_code=404, detail=f"No poem with id {poem_id}")
    return poem


def _require_stage(stage: str) -> str:
    stage = (stage or "").strip().lower()
    if stage not in STAGE_NAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown stage '{stage}'. Expected one of: {', '.join(STAGE_NAMES)}"
        )
    return stage


@app.get("/api/poems")
async def list_poems():
    """Every saved poem, newest first, with how much of a record it has."""
    poems = engine.database_manager.retrieve_all_poem_entries()
    for poem in poems:
        counts = engine.database_manager.count_poem_iterations_by_stage(poem["id"])
        poem["iteration_counts"] = {stage: counts.get(stage, 0) for stage in STAGE_NAMES}
        poem["iteration_total"] = sum(counts.values())
        poem["is_live"] = poem["id"] == current_poem_id
    return {"poems": poems}


@app.get("/api/poems/{poem_id}")
async def read_poem(poem_id: int):
    """One poem and every reading recorded for it, grouped by stage."""
    poem = _require_poem(poem_id)
    iterations = engine.database_manager.retrieve_poem_iterations(poem_id)

    stages = {stage: [] for stage in STAGE_NAMES}
    for iteration in iterations:
        stages.setdefault(iteration["stage"], []).append(iteration)

    return {
        "poem": poem,
        "stages": stages,
        "is_live": poem_id == current_poem_id,
    }


@app.patch("/api/poems/{poem_id}")
async def edit_poem(poem_id: int, payload: EditPoemRequest):
    """Switch a poem into or out of the rotation."""
    _require_poem(poem_id)

    if payload.active is None:
        raise HTTPException(status_code=400, detail="Nothing to change")

    return {"poem": engine.database_manager.set_poem_active(poem_id, payload.active)}


@app.post("/api/poems/{poem_id}/live")
async def make_poem_live(poem_id: int):
    """Show a saved poem on the screen right now.

    A hand override, so the poem's place in the rotation is left as it is: a
    poem that has been switched off can be shown without being switched back
    on, and the deck goes on stepping over it afterwards. Nothing is pinned
    either -- the next trigger deals the next card as usual, only never this
    same poem twice running.
    """
    poem = _require_poem(poem_id)
    _make_poem_live(poem)
    return {"poem": poem, "is_live": True}


@app.delete("/api/poems/{poem_id}")
async def remove_poem(poem_id: int):
    """Delete a poem and every reading recorded for it.

    The live poem cannot be deleted while the screen is showing it, because
    the engine is already holding it and would go on displaying a poem that
    no longer exists. Switch it off or move on to another one first.
    """
    _require_poem(poem_id)

    if poem_id == current_poem_id:
        raise HTTPException(
            status_code=409,
            detail="This poem is live. Move to another poem before deleting it."
        )

    readings = len(engine.database_manager.retrieve_poem_iterations(poem_id))
    engine.database_manager.delete_poem_entry(poem_id)
    return {"status": "deleted", "id": poem_id, "readings_deleted": readings}


@app.post("/api/poems/{poem_id}/iterations")
async def add_iteration(poem_id: int, payload: NewIterationRequest):
    """Add a reading of your own to a poem's record."""
    _require_poem(poem_id)
    stage = _require_stage(payload.stage)

    content = (payload.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="A reading cannot be empty")

    iteration_id = engine.database_manager.record_poem_iteration(
        poem_id,
        stage,
        content,
        source_text=(payload.source_text or "").strip(),
        note=(payload.note or "").strip(),
        journey=(payload.journey or "out").strip().lower(),
        origin="hand",
    )
    return {"iteration": engine.database_manager.retrieve_poem_iteration_by_id(iteration_id)}


@app.patch("/api/iterations/{iteration_id}")
async def edit_iteration(iteration_id: int, payload: EditIterationRequest):
    """Change a reading, whether the model wrote it or you did."""
    if payload.content is not None and not payload.content.strip():
        raise HTTPException(status_code=400, detail="A reading cannot be empty")

    iteration = engine.database_manager.update_poem_iteration(
        iteration_id,
        content=payload.content,
        note=payload.note,
        source_text=payload.source_text,
    )
    if not iteration:
        raise HTTPException(status_code=404, detail=f"No reading with id {iteration_id}")
    return {"iteration": iteration}


@app.delete("/api/iterations/{iteration_id}")
async def remove_iteration(iteration_id: int):
    """Take a reading off the record."""
    if not engine.database_manager.delete_poem_iteration(iteration_id):
        raise HTTPException(status_code=404, detail=f"No reading with id {iteration_id}")
    return {"status": "deleted", "id": iteration_id}


@app.get("/poems", include_in_schema=False)
async def poems_page():
    """The library, as a page."""
    return FileResponse(STATIC_DIR / "poems.html")


@app.get("/poems/{poem_id}", include_in_schema=False)
async def poem_page(poem_id: int):
    """One poem's record, as a page. The id is read back from the URL."""
    _require_poem(poem_id)
    return FileResponse(STATIC_DIR / "poem.html")


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
    return _make_poem_live(stored_poem)


@app.post("/next_poem")
async def next_poem():
    """Make another poem in the rotation live, chosen at random.

    Random, but dealt from a shuffled deck rather than drawn fresh each
    time: every poem in the rotation comes up once before any of them comes
    round again, and a new cut never opens on the poem that was just up.

    Only poems that are switched on are dealt. A poem that has been turned
    off keeps its place in the library and its record, and is simply stepped
    over here. If the rotation is empty there is nothing to move to, and the
    poem already up stays where it is.
    """
    poems = engine.database_manager.retrieve_active_poem_entries()
    if not poems:
        raise HTTPException(
            status_code=404,
            detail="No poems are switched on. Turn one on from the poems page."
        )

    return _make_poem_live(poem_deck.deal(poems, previous_id=current_poem_id))


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
        await manager.send_personal_message(
            json.dumps(_event_for_clients(init_event), ensure_ascii=False),
            websocket
        )

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
