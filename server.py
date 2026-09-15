from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
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
from translation_units import normalize_reading


config.validate_required_settings()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
OUTPUT_JSONL_PATH = config.STREAM_OUTPUT_JSONL_PATH
OUTPUT_JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
if not OUTPUT_JSONL_PATH.exists():
    OUTPUT_JSONL_PATH.write_text("")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = PoemTransformerEngine()
sequence_index = 1
# The poem currently on screen, so "next" knows what it is following.
current_poem_id = None
# Last presentation event. Open walls receive it on /events; /state is the
# one-time load for a page that just opened.
last_client_event = None
event_id = 0
_event_listeners: List[asyncio.Queue] = []

# The order poems come up in. Shuffled, and every poem in the rotation is
# shown once before any of them comes round again.
poem_deck = PoemDeck()

# Lock to serialize synonym cycles so they don't overlap
_cycle_lock = asyncio.Lock()
SYNONYM_CYCLE_INTERVAL = float(os.environ.get("SYNONYM_CYCLE_INTERVAL", "1.2"))
LOG_INTERMEDIATE_SYNONYMS = os.environ.get(
    "LOG_INTERMEDIATE_SYNONYMS", "false"
).lower() in ("1", "true", "yes")
_background_tasks: set = set()


def _spawn(coro) -> asyncio.Task:
    """Keep a background trigger alive until it finishes."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task

OPENING_POEM = {
    "title": "Libro de las preguntas",
    "raw_text": "Dime, la rosa está desnuda\no sólo tiene ese vestido?",
    "final_translation": "Tell me, is the rose naked\nor is that her only dress?",
    "source_language": config.SOURCE_LANGUAGE,
    "source_language_code": config.SOURCE_LANGUAGE_CODE,
    "target_language": config.TARGET_LANGUAGE,
    "target_language_code": config.TARGET_LANGUAGE_CODE,
}


def _make_poem_live(stored_poem: Dict, record_event: bool = True) -> Dict:
    """Make a saved poem live and return its HTTP presentation event.

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
    # Keep the current library identity in memory for rotation/UI state.
    engine.poem_id = current_poem_id

    event = {
        "status": "ok",
        "poem_id": current_poem_id,
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
        },
        **language_pair,
    }
    if record_event:
        _append_event_to_jsonl(event)
    return _publish_event(event)


def _ensure_opening_poem() -> None:
    """Make a poem live as soon as the server starts, with no click required.

    The first card off the shuffled deck if the rotation has anything in it,
    so the installation does not open on the same poem every morning.
    Otherwise the default rose couplet is stored so the installation has
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
            _make_poem_live(stored, record_event=False)
        return

    _make_poem_live(poem_deck.deal(poems), record_event=False)


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
        with OUTPUT_JSONL_PATH.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as error:
        print(f"✗ Failed to write event to JSONL: {error}")


def _is_presentation(event: dict) -> bool:
    """True when the payload can paint the poem, not only report an error."""
    return event.get("new_state") is not None or isinstance(event.get("words"), list)


def _publish_event(event: dict, *, remember: bool = True) -> dict:
    """Push a presentation to every open /events listener.

    /state is the one-time load for a page that just opened. It must keep
    the last payload that can draw the poem. Errors go to open walls only.
    """
    global last_client_event, event_id
    payload = dict(event)
    getter = getattr(engine, "get_last_debug_exchange", None)
    if callable(getter):
        payload["debug"] = getter()
    event_id += 1
    payload["event_id"] = event_id
    if remember and _is_presentation(payload):
        last_client_event = payload
    for listener in list(_event_listeners):
        try:
            listener.put_nowait(payload)
        except Exception as error:
            print(f"✗ Dropped a live-wall event: {error}")
    return payload


def _publish_error(message: str) -> None:
    """Tell open walls a trigger failed without replacing the poem on /state."""
    _publish_event({"reason": "error", "error": message}, remember=False)


_ensure_opening_poem()


def _event_for_clients(event: dict) -> dict:
    """Attach debug info and publish the event for the live wall."""
    return _publish_event(event)


async def _run_synonym_cycle_for_word(word_index: int, seq_idx_start: int, prev_state: str):
    """One trigger: show every sense of this word, then settle on the primary.

    Each synonym is published as an intermediate so every open wall can play
    the cycle. Only the settled reading is stored as the trigger's result.
    """
    global sequence_index

    if word_index < 0 or word_index >= len(engine.original_poem_words):
        return None

    acting_phase = engine.get_current_phase().name
    original_word = engine.original_poem_words[word_index]

    engine.begin_debug_trigger()
    translation_data = await asyncio.to_thread(
        engine.get_or_fetch_word_translation_with_synonyms,
        original_word,
        engine.get_original_line_for_word_index(word_index)
    )
    readings = engine.unique_word_readings(translation_data, original_word)
    primary = readings[0] if readings else original_word

    current = engine.current_words[word_index]
    for reading in readings:
        if normalize_reading(reading) == normalize_reading(primary):
            continue
        if normalize_reading(reading) == normalize_reading(current):
            continue
        current = reading
        inter_event = {
            "sequence_index": None,
            "timestamp": None,
            "unit_level": "poem",
            "unit_path": None,
            "previous_state": prev_state,
            **_render_snapshot(engine.preview_word_slots(word_index, reading)),
            "reason": "synonym_cycle",
            "confidence": 0.0,
            "alternatives": readings,
            "intermediate": True,
            "triggered_by_context": False,
            "context_snapshot": {
                "word_index": word_index,
                "phase": acting_phase,
                "phase_after": acting_phase,
            },
            "presentation_indices": [word_index],
        }
        _publish_event(inter_event)
        if LOG_INTERMEDIATE_SYNONYMS:
            logged = dict(inter_event)
            logged['sequence_index'] = sequence_index
            _append_event_to_jsonl(logged)
            sequence_index += 1
        await asyncio.sleep(SYNONYM_CYCLE_INTERVAL)

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
        "alternatives": readings,
        "triggered_by_context": False,
        "context_snapshot": {
            "word_index": word_index,
            "phase": acting_phase,
            "phase_after": engine.get_current_phase().name,
        },
        "presentation_indices": [word_index],
    }
    _append_event_to_jsonl(event)
    sequence_index += 1
    return _event_for_clients(event)


async def _run_block_trigger(seq_idx_start: int, prev_state: str):
    """Advance one block-level trigger, for the phases after word-by-word.

    Gathering rewrites a whole span at once, so there is nothing to cycle
    through: a single event carries the new state. Hitting the target only
    turns the engine around; the reverse word-by-word work starts on the
    next trigger.
    """
    global sequence_index

    acting_phase = engine.get_current_phase().name
    await asyncio.to_thread(engine.process_next_sensor_trigger)

    if engine.last_action_phase:
        acting_phase = engine.last_action_phase.name

    start_index, end_index = engine.last_changed_span or (None, None)
    # Turning around rebuilds the engine's queues and clears last_changed_span.
    # The line-stage trigger still acted on the whole poem, even when the
    # chosen reading was already on the wall.
    if start_index is None and acting_phase == TransformationPhase.LINES.name:
        start_index, end_index = 0, len(engine.current_words)

    presentation_indices = (
        list(range(start_index, end_index))
        if start_index is not None and end_index is not None
        else []
    )

    event = {
        "sequence_index": seq_idx_start,
        "timestamp": None,
        "unit_level": "poem",
        "unit_path": None,
        "previous_state": prev_state,
        **_render_snapshot(),
        # The trigger must change the page. These indices mark what it tried
        # so the wall can draw the new wording.
        "presentation_indices": presentation_indices,
        # What the pass said it bettered, so a run can be read back as a
        # record of the decisions and not only of their results.
        "reason": engine.last_block_improvement or "trigger",
        "confidence": 0.8,
        # The alternatives remain transiently available to this response.
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
    sequence_index += 1
    return _event_for_clients(event)


def _change_to_next_poem() -> Optional[Dict]:
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
        return None

    return _event_for_clients(_make_poem_live(following))


async def _run_one_trigger() -> None:
    """Do the work of one trigger without holding the HTTP request open.

    Stage 1 sleeps between synonyms. If that sleep happens inside POST
    /trigger, Render's proxy gives up and the wall sees 502.
    """
    try:
        async with _cycle_lock:
            if engine.get_current_phase() == TransformationPhase.COMPLETE:
                event = _change_to_next_poem()
                if event is None:
                    _publish_error("No poem is available to show next")
                return

            prev_state = engine.get_current_transformation_state()
            if engine.get_current_phase() == TransformationPhase.WORDS:
                if (
                    not engine.phase_1_word_queue
                    and engine.trigger_count == 0
                    and engine.last_action_phase is None
                ):
                    engine.phase_1_word_queue = engine.build_phase_1_word_queue()
                word_index = engine.claim_next_phase_1_word_index()
                if word_index is None:
                    engine.transition_to_phrases()
                    return
                try:
                    await _run_synonym_cycle_for_word(
                        word_index, sequence_index, prev_state
                    )
                except Exception:
                    engine.return_phase_1_word(word_index)
                    raise
                return
            await _run_block_trigger(sequence_index, prev_state)
    except Exception as error:
        print(f"✗ Trigger failed: {error}")
        _publish_error(str(error))


@app.post("/trigger")
async def trigger():
    """Start one trigger and return immediately.

    In Phase 1 a trigger takes one word and cycles every synonym through
    that slot on the wall, then settles on the primary. After that a trigger
    rewrites one block, gathering toward the target. Once the target is on
    the page, the next triggers run that same word-then-gather process back
    toward the original language.

    Once a poem has finished its whole journey, the next trigger changes the
    poem instead of translating: the sensor is the only thing driving an
    unattended wall, so the rotation has to turn on it.

    The cycle is published on /events. This response only means the trigger
    was accepted, so a long synonym walk cannot time out the proxy.
    """
    if not engine.original_poem_words:
        raise HTTPException(status_code=400, detail="No poem loaded")

    _spawn(_run_one_trigger())
    return {"status": "ok", "accepted": True}


@app.get("/languages")
async def languages():
    """List the language pairs a poem can be entered with."""
    return {
        "source_languages": config.SUPPORTED_SOURCE_LANGUAGES,
        "target_languages": config.SUPPORTED_TARGET_LANGUAGES,
        "default_source_code": config.SOURCE_LANGUAGE_CODE,
        "default_target_code": config.TARGET_LANGUAGE_CODE,
    }


class EditPoemRequest(BaseModel):
    """Authored poem fields that may be changed in place."""
    title: Optional[str] = None
    source_language_code: Optional[str] = None
    raw_text: Optional[str] = None
    target_language_code: Optional[str] = None
    final_translation: Optional[str] = None
    active: Optional[bool] = None


STAGE_NAMES = ("words", "phrases", "lines")


class NewIterationRequest(BaseModel):
    """A stage reading explicitly authored by a person."""
    stage: str
    content: str
    source_text: Optional[str] = None
    note: Optional[str] = None
    journey: Optional[str] = "out"


class EditIterationRequest(BaseModel):
    """Changes to a saved API or hand-authored stage reading."""
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
            detail=f"Unknown stage '{stage}'. Expected one of: {', '.join(STAGE_NAMES)}",
        )
    return stage


@app.get("/api/poems")
async def list_poems():
    """Every saved poem, newest first."""
    poems = engine.database_manager.retrieve_all_poem_entries()
    for poem in poems:
        counts = engine.database_manager.count_poem_iterations_by_stage(poem["id"])
        poem["iteration_counts"] = {
            stage: counts.get(stage, 0) for stage in STAGE_NAMES
        }
        poem["iteration_total"] = sum(counts.values())
        poem["is_live"] = poem["id"] == current_poem_id
    return {"poems": poems}


@app.get("/api/poems/{poem_id}")
async def read_poem(poem_id: int):
    """One poem and every saved API or hand-authored stage record."""
    poem = _require_poem(poem_id)
    stages = {stage: [] for stage in STAGE_NAMES}
    for iteration in engine.database_manager.retrieve_poem_iterations(poem_id):
        stages.setdefault(iteration["stage"], []).append(iteration)
    return {
        "poem": poem,
        "stages": stages,
        "is_live": poem_id == current_poem_id,
    }


@app.patch("/api/poems/{poem_id}")
async def edit_poem(poem_id: int, payload: EditPoemRequest):
    """Update authored poem content and metadata without changing its id."""
    existing = _require_poem(poem_id)
    supplied = getattr(payload, "model_fields_set", None)
    if supplied is None:
        supplied = getattr(payload, "__fields_set__", set())
    if not supplied:
        raise HTTPException(status_code=400, detail="Nothing to change")

    raw_text = (
        payload.raw_text if "raw_text" in supplied else existing["raw_text"]
    )
    raw_text = (raw_text or "").strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="Original poem text cannot be empty")

    source_code = (
        payload.source_language_code
        if "source_language_code" in supplied
        else existing["source_language_code"]
    )
    target_code = (
        payload.target_language_code
        if "target_language_code" in supplied
        else existing["target_language_code"]
    )
    source = _resolve_language(
        source_code, config.SUPPORTED_SOURCE_LANGUAGES, "source"
    )
    target = _resolve_language(
        target_code, config.SUPPORTED_TARGET_LANGUAGES, "target"
    )
    if source["code"] == target["code"]:
        raise HTTPException(
            status_code=400, detail="Source and target languages must differ"
        )

    title = payload.title if "title" in supplied else existing["title"]
    title = (title or "").strip() or None
    final_translation = (
        payload.final_translation
        if "final_translation" in supplied
        else existing["final_translation"]
    )
    final_translation = (final_translation or "").strip() or None
    active = payload.active if "active" in supplied else existing["active"]

    try:
        updated = engine.database_manager.update_poem_entry(
            poem_id=poem_id,
            title=title,
            raw_text=raw_text,
            source_language=source["name"],
            source_language_code=source["code"],
            target_language=target["name"],
            target_language_code=target["code"],
            final_translation=final_translation,
            active=bool(active),
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    event = None
    if poem_id == current_poem_id:
        event = _event_for_clients(_make_poem_live(updated))
    return {
        "poem": updated,
        "is_live": poem_id == current_poem_id,
        "event": event,
    }


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
    return _event_for_clients(_make_poem_live(poem))


@app.delete("/api/poems/{poem_id}")
async def remove_poem(poem_id: int):
    """Delete a poem.

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

    engine.database_manager.delete_poem_entry(poem_id)
    return {"status": "deleted", "id": poem_id}


@app.post("/api/poems/{poem_id}/iterations")
async def add_iteration(poem_id: int, payload: NewIterationRequest):
    """Save one stage reading explicitly entered through the editor."""
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
    return {
        "iteration": engine.database_manager.retrieve_poem_iteration_by_id(
            iteration_id
        )
    }


@app.patch("/api/iterations/{iteration_id}")
async def edit_iteration(iteration_id: int, payload: EditIterationRequest):
    """Update a saved API or hand-authored stage reading."""
    if payload.content is not None and not payload.content.strip():
        raise HTTPException(status_code=400, detail="A reading cannot be empty")
    iteration = engine.database_manager.update_poem_iteration(
        iteration_id,
        content=payload.content,
        note=payload.note,
        source_text=payload.source_text,
    )
    if not iteration:
        raise HTTPException(
            status_code=404, detail=f"No reading with id {iteration_id}"
        )
    return {"iteration": iteration}


@app.delete("/api/iterations/{iteration_id}")
async def remove_iteration(iteration_id: int):
    """Delete a saved API or hand-authored stage reading."""
    if not engine.database_manager.delete_poem_iteration(iteration_id):
        raise HTTPException(
            status_code=404, detail=f"No reading with id {iteration_id}"
        )
    return {"status": "deleted", "id": iteration_id}


@app.get("/poems", include_in_schema=False)
async def poems_page():
    """The library, as a page."""
    return FileResponse(STATIC_DIR / "poems.html")


@app.get("/poems/{poem_id}", include_in_schema=False)
async def poem_page(poem_id: int):
    """Edit the poem and every saved Stage 1, 2, and 3 iteration."""
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


SSE_KEEPALIVE_SECONDS = 15


@app.get("/events")
async def events():
    """Push each trigger to every open live page.

    A new connection is given the last drawable presentation so a refresh
    or a dropped stream can catch up. Comments keep the proxy from closing
    an idle wall.
    """
    listener: asyncio.Queue = asyncio.Queue()
    _event_listeners.append(listener)

    async def stream():
        try:
            if last_client_event is not None and _is_presentation(last_client_event):
                yield f"data: {json.dumps(last_client_event, ensure_ascii=False)}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(
                        listener.get(),
                        timeout=SSE_KEEPALIVE_SECONDS,
                    )
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            if listener in _event_listeners:
                _event_listeners.remove(listener)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/state")
async def state():
    if last_client_event is not None:
        return last_client_event
    event = {
        "sequence_index": sequence_index,
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
            "poem_id": current_poem_id,
            **_current_language_pair(),
        },
        "stats": engine.get_transformation_statistics(),
        **_current_language_pair()
    }
    return _publish_event(event)


# Registered last on purpose: a mount at "/" matches every path and every scope
# type, so any route declared after it would be unreachable.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
