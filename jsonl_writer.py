"""
Simple JSONL writer utility for streaming translation events.
Provides a small helper to append a dict as a JSON line to STREAM_OUTPUT_JSONL_PATH.
"""

import json
from pathlib import Path
from typing import Dict, Any

import config


def append_event_to_stream(event: Dict[str, Any]) -> None:
    """Append an event dict to the configured JSONL stream file.

    Ensures parent directory exists before writing. Event dict will be
    written as a single JSON object per line (JSONL), using ensure_ascii=False.
    """
    path = Path(config.STREAM_OUTPUT_JSONL_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
