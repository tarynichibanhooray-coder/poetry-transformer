"""Print the live poem after each trigger, without the UI.

Run:
    python tests/test_live_poem_print.py

Skipped by `unittest discover` unless LIVE_POEM=1, so the ordinary suite
does not call OpenAI.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from openai_translator import OpenAITranslator
from poem_transformer_engine import PoemTransformerEngine, TransformationPhase

COUPLET = "Dime, la rosa está desnuda\no sólo tiene ese vestido?"
CHOSEN = "Tell me, is the rose naked\nor is that her only dress?"
MAX_TRIGGERS = 120


class FakeDatabase:
    def retrieve_cached_word_translation(self, *args, **kwargs):
        return None

    def store_new_word_translation_with_synonyms(self, *args, **kwargs):
        return 1

    def retrieve_cached_phrase_translation(self, *args, **kwargs):
        return None

    def store_new_phrase_translation(self, *args, **kwargs):
        return 1

    def record_translation_history_entry(self, *args, **kwargs):
        return 1

    def count_cached_word_translations(self):
        return 0

    def count_cached_phrase_translations(self):
        return 0

    def count_total_api_requests_made(self):
        return 0

    def calculate_total_tokens_used(self):
        return 0


def _print_poem(text: str, stage: str = "") -> None:
    poem = (text or "").rstrip()
    if stage:
        sys.stdout.write(f"[{stage}]\n")
    sys.stdout.write(poem + "\n\n")
    sys.stdout.flush()


def _stage_label(engine) -> str:
    phase = engine.get_current_phase().name
    if engine.on_return_journey and phase != "COMPLETE":
        return f"return {phase.lower()}"
    return phase.lower()


def _phase_1_synonyms(translation_data, original_word):
    synonyms = list(translation_data.get("synonyms") or [])
    primary = (
        translation_data.get("target_word")
        or translation_data.get("primary_translation")
        or original_word
    )
    seen = set()
    unique = []
    for synonym in synonyms:
        if synonym not in seen:
            unique.append(synonym)
            seen.add(synonym)
    return unique, primary


def walk_and_print(poem=COUPLET, destination=CHOSEN, max_triggers=MAX_TRIGGERS):
    config.validate_required_settings()
    config.DEBUG_MODE = False
    config.VERBOSE_LOGGING = False

    engine = PoemTransformerEngine(random_seed=1)
    engine.database_manager = FakeDatabase()
    engine.ai_translator = OpenAITranslator()
    engine.initialize_poem_with_text(poem, final_translation=destination)

    last_printed = None

    def show(stage=None):
        nonlocal last_printed
        current = engine.get_current_transformation_state()
        if current == last_printed:
            return
        last_printed = current
        # The stage that did the work, not the one the engine moved on to.
        # Arrival swaps the languages inside the same trigger that shows the
        # chosen rendering, so reading the label afterwards misreports it.
        _print_poem(current, stage or _stage_label(engine))

    show()
    triggers = 0

    while (
        triggers < max_triggers
        and engine.get_current_phase() != TransformationPhase.COMPLETE
    ):
        if engine.get_current_phase() == TransformationPhase.WORDS:
            word_index = engine.claim_next_phase_1_word_index()
            if word_index is None:
                engine.transition_to_phrases()
                continue
            original_word = engine.original_poem_words[word_index]
            translation_data = engine.get_or_fetch_word_translation_with_synonyms(
                original_word
            )
            synonyms, primary = _phase_1_synonyms(translation_data, original_word)
            if not synonyms:
                engine.replace_word_in_transformation_state(word_index, primary)
                show()
            else:
                for synonym in synonyms:
                    engine.replace_word_in_transformation_state(word_index, synonym)
                    show()
                engine.replace_word_in_transformation_state(word_index, primary)
                show()
            engine.note_phase_1_word_completed()
        else:
            stage = _stage_label(engine)
            engine.process_next_sensor_trigger()
            # Stage 3 ranks its attempts and says what each one holds onto.
            # That reasoning is the whole point of watching this stage.
            note = engine.last_block_improvement
            show(f"{stage} · {note}" if note else stage)
        triggers += 1


class LivePoemPrintTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("LIVE_POEM") == "1",
        "Set LIVE_POEM=1 to print a live OpenAI walk",
    )
    def test_print_each_returned_poem(self):
        walk_and_print()


if __name__ == "__main__":
    walk_and_print()
