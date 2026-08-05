from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import asyncio
import json
import os
from pathlib import Path
from typing import List

import time

from poem_transformer_engine import PoemTransformerEngine


OUTPUT_JSONL_PATH = Path("output/translation_stream.jsonl")
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

# Serve static files from the `static/` directory and return index.html at '/'
app.mount("/", StaticFiles(directory="static", html=True), name="static")

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


def _append_event_to_jsonl(event: dict) -> None:
    try:
        with OUTPUT_JSONL_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"✗ Failed to write event to JSONL: {e}")


async def _broadcast_event(event: dict) -> None:
    await manager.broadcast(json.dumps(event, ensure_ascii=False))


@app.post("/trigger")
async def trigger(request: Request):
    """Advance transformation by one trigger and broadcast the visible change.

    TODO: implement API key validation here (require API key in headers or form data)
    """
    global sequence_index
    # capture previous state
    prev_state = engine.get_current_transformation_state()

    # advance the engine
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
    # broadcast asynchronously (don't await to keep HTTP response snappy)
    asyncio.create_task(_broadcast_event(event))

    sequence_index += 1
    return {"new_state": new_state}


@app.post("/load_poem")
async def load_poem(payload: dict):
    """Load poem text into the engine. Payload: {"poem": "text..."} """
    poem = payload.get("poem")
    if not poem:
        return {"error": "missing poem"}

    engine.initialize_poem_with_text(poem)

    event = {
        "sequence_index": sequence_index,
        "timestamp": None,
        "unit_level": "poem",
        "unit_path": None,
        "previous_state": None,
        "new_state": engine.get_current_transformation_state(),
        "reason": "poem_loaded",
        "confidence": 1.0,
        "alternatives": [],
        "triggered_by_context": False,
        "context_snapshot": {"total_words": len(engine.original_poem_words)}
    }

    _append_event_to_jsonl(event)
    asyncio.create_task(_broadcast_event(event))

    return {"status": "ok"}


@app.get("/state")
async def state():
    return {
        "current_state": engine.get_current_transformation_state(),
        "stats": engine.get_transformation_statistics()
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
            "context_snapshot": {}
        }
        await manager.send_personal_message(json.dumps(init_event, ensure_ascii=False), websocket)

        while True:
            # keep connection open; ignore incoming messages
            await websocket.receive_text()

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
