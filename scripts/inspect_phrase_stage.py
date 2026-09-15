"""Print every stage 2 exchange: the scrap, its reading, and what came back.

Run:
    python scripts/inspect_phrase_stage.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from openai_translator import OpenAITranslator
from poem_transformer_engine import PoemTransformerEngine, TransformationPhase

COUPLET = "Dime, la rosa está desnuda\no sólo tiene ese vestido?"
CHOSEN = "Tell me, is the rose naked\nor is that her only dress?"
STAGE_ONE_READING = ["Tell me,", "the", "rose", "is", "naked", "or", "only", "has", "that", "dress?"]


class FakeDatabase:
    def retrieve_cached_word_translation(self, *a, **k):
        return None

    def store_new_word_translation_with_synonyms(self, *a, **k):
        return 1

    def record_translation_history_entry(self, *a, **k):
        return 1

    def count_cached_word_translations(self):
        return 0

    def count_cached_phrase_translations(self):
        return 0

    def count_total_api_requests_made(self):
        return 0

    def calculate_total_tokens_used(self):
        return 0


def main():
    config.validate_required_settings()
    config.DEBUG_MODE = False
    config.VERBOSE_LOGGING = False

    engine = PoemTransformerEngine(random_seed=1)
    engine.database_manager = FakeDatabase()
    engine.ai_translator = OpenAITranslator()
    engine.initialize_poem_with_text(COUPLET, final_translation=CHOSEN)

    for index, text in enumerate(STAGE_ONE_READING):
        engine.poem.units[index].text = text

    engine.phase_1_word_queue = []
    engine.transition_to_phrases()

    before_call = engine.get_current_transformation_state()
    engine.process_next_sensor_trigger()  # first trigger: loads the edit field
    exchange = engine.ai_translator.last_exchange or {}
    print(f"raw response: {exchange.get('response')}\n")
    print(f"edits offered: {engine.last_block_drafts}\n")

    while engine.get_current_phase() == TransformationPhase.PHRASES:
        before = engine.get_current_transformation_state()
        engine.process_next_sensor_trigger()
        after = engine.get_current_transformation_state()
        print(f"  changed : {engine.last_changed_span}")
        print(f"  before  : {before!r}")
        print(f"  after   : {after!r}\n")
        if before == after and engine.last_changed_span is None:
            break

    print(f"final poem: {engine.get_current_transformation_state()!r}")
    print(f"started from: {before_call!r}")


if __name__ == "__main__":
    main()
