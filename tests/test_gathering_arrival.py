"""Gathering has no click budget; arrival is an exact match, then a stall land."""

import unittest

import config
from poem_transformer_engine import PoemTransformerEngine, TransformationPhase

COUPLET = "Dime, la rosa está desnuda\no sólo tiene ese vestido?"
CHOSEN = "Tell me, is the rose naked\nor is that her only dress?"


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


class EchoTranslator:
    """Always returns the live English, so gathering cannot invent the target."""

    def request_word_translation_with_synonyms(
        self, word, src, tgt, context_line=None, whole_poem=None, arriving_at=None
    ):
        return {"primary_translation": f"<{word}>", "synonyms": [], "tokens_used": 1}

    def validate_word_translation_response(self, response):
        return True

    def request_block_translation(
        self,
        source_lines,
        src,
        tgt,
        poem_so_far=None,
        whole_poem=None,
        mode="poetic",
        current_reading=None,
        arriving_at=None,
        returning=False,
        original_language=None,
        already_used=None,
    ):
        lines = list(current_reading or source_lines)
        return {
            "lines": lines,
            "drafts": [],
            "tokens_used": 1,
            "unchanged": True,
            "improvement": "echo",
        }

    def validate_block_translation_response(self, response):
        return True


def make_engine():
    engine = PoemTransformerEngine(random_seed=1)
    engine.database_manager = FakeDatabase()
    engine.ai_translator = EchoTranslator()
    engine.initialize_poem_with_text(COUPLET, final_translation=CHOSEN)
    return engine


def start_gathering(engine, first_line, second_line):
    engine.phase_1_word_queue = []
    engine.transition_to_phase_2_growing_blocks()
    engine.replace_block_in_transformation_state(0, 5, [first_line])
    engine.replace_block_in_transformation_state(5, 10, [second_line])
    engine.unchanged_gathers = 0
    engine.seen_span_readings = {}
    engine.seen_poem_readings = set()
    engine.settled_spans = set()
    engine.settled_line_indices = set()


class GatheringArrivalTests(unittest.TestCase):
    def test_there_is_no_numbered_plan_to_the_target(self):
        engine = make_engine()
        stats = engine.get_transformation_statistics()
        self.assertIsNone(stats["planned_operations"])
        self.assertEqual(engine.destination_lines, CHOSEN.split("\n"))

    def test_echoed_gathers_do_not_arrive_before_a_stall(self):
        engine = make_engine()
        start_gathering(
            engine,
            "Tell me, the rose is naked",
            "or is that her only dress?",
        )
        self.assertFalse(engine.poem_has_arrived())

        original_threshold = config.GATHER_STALL_BEFORE_LANDING
        config.GATHER_STALL_BEFORE_LANDING = 99
        try:
            for _ in range(12):
                engine.process_next_sensor_trigger()
                self.assertFalse(engine.poem_has_arrived())
                self.assertEqual(
                    engine.get_current_phase(),
                    TransformationPhase.PHASE_2_GROWING_BLOCKS,
                )
        finally:
            config.GATHER_STALL_BEFORE_LANDING = original_threshold

    def test_stalled_gathering_lands_destination_lines_until_arrival(self):
        engine = make_engine()
        start_gathering(
            engine,
            "Tell me, the rose is naked",
            "or is that her only dress?",
        )

        for _ in range(config.GATHER_STALL_BEFORE_LANDING):
            engine.process_next_sensor_trigger()
            self.assertFalse(engine.poem_has_arrived())
            self.assertEqual(
                engine.get_current_phase(),
                TransformationPhase.PHASE_2_GROWING_BLOCKS,
            )

        engine.process_next_sensor_trigger()
        self.assertIn(
            "Tell me, is the rose naked",
            engine.get_current_transformation_state(),
        )

        if not engine.poem_has_arrived():
            for _ in range(config.GATHER_STALL_BEFORE_LANDING + 1):
                engine.process_next_sensor_trigger()
                if engine.poem_has_arrived():
                    break

        self.assertTrue(engine.on_return_journey)
        self.assertEqual(
            engine.get_current_phase(),
            TransformationPhase.PHASE_1_WORD_BY_WORD,
        )
        self.assertEqual(engine.source_language, "English")
        self.assertEqual(engine.target_language, "Spanish")

    def test_destination_wording_is_not_treated_as_a_repeat(self):
        engine = make_engine()
        start_gathering(
            engine,
            "Tell me, the rose is naked",
            "or is that her only dress?",
        )
        destination = ["Tell me, is the rose naked"]
        engine.seen_span_readings[(0, 5)] = {engine.normalize_reading(destination[0])}
        self.assertFalse(
            engine.reading_is_repeat(
                0,
                5,
                destination,
                "Tell me, the rose is naked",
            )
        )

    def test_gathering_does_not_overwrite_a_destination_line(self):
        engine = make_engine()
        start_gathering(
            engine,
            "Tell me, the rose is naked",
            "or is that her only dress?",
        )
        self.assertEqual(engine.destination_matched_line_indices(), {1})

        class WanderTranslator(EchoTranslator):
            def request_block_translation(self, source_lines, *args, **kwargs):
                return {
                    "lines": ["or is that her sole attire?"],
                    "drafts": [],
                    "tokens_used": 1,
                    "unchanged": False,
                    "improvement": "wander",
                }

        engine.ai_translator = WanderTranslator()
        engine.process_next_sensor_trigger()
        live_lines = engine.get_current_transformation_state().split("\n")
        self.assertEqual(
            engine.normalize_reading(live_lines[1]),
            engine.normalize_reading("or is that her only dress?"),
        )
        self.assertEqual(engine.destination_matched_line_indices(), {1})

    def test_current_reading_is_not_forbidden(self):
        engine = make_engine()
        start_gathering(
            engine,
            "Tell me, is the rose naked",
            "or is that her only dress?",
        )
        forbidden = engine.forbidden_readings_for_span(0, 5)
        self.assertNotIn(
            engine.normalize_reading("Tell me, is the rose naked"),
            forbidden,
        )

    def test_vacuous_rewrite_is_left_alone(self):
        engine = make_engine()
        start_gathering(
            engine,
            "another fire",
            "burns from its fire?",
        )
        before = engine.get_current_transformation_state()

        class PrettyTranslator(EchoTranslator):
            def request_block_translation(self, source_lines, *args, **kwargs):
                return {
                    "lines": ["another glow"],
                    "drafts": [],
                    "tokens_used": 1,
                    "unchanged": False,
                    "defect": "none",
                    "improvement": "more poetic",
                }

        engine.ai_translator = PrettyTranslator()
        engine.process_next_sensor_trigger()
        self.assertEqual(engine.get_current_transformation_state(), before)

    def test_named_defect_is_allowed_to_improve(self):
        engine = make_engine()
        start_gathering(
            engine,
            "another glow",
            "or is that her only dress?",
        )

        class FixTranslator(EchoTranslator):
            def request_block_translation(self, source_lines, *args, **kwargs):
                return {
                    "lines": ["another fire"],
                    "drafts": [],
                    "tokens_used": 1,
                    "unchanged": False,
                    "defect": "wrong_sense",
                    "improvement": "glow is not fuego",
                }

        engine.ai_translator = FixTranslator()
        engine.process_next_sensor_trigger()
        live = engine.get_current_transformation_state()
        self.assertIn("fire", live.casefold())
        self.assertNotIn("glow", live.casefold())

    def test_good_passages_are_skipped_until_the_rest_is_good(self):
        engine = make_engine()
        start_gathering(
            engine,
            "Tell me, the rose is naked",
            "or does she wear only that dress?",
        )
        first_line = engine.line_spans[0]
        second_line = engine.line_spans[1]
        engine.mark_span_settled(*first_line)

        self.assertFalse(engine.span_is_open_for_gathering(*first_line))
        self.assertTrue(engine.span_is_open_for_gathering(*second_line))
        self.assertFalse(
            engine.span_is_open_for_gathering(first_line[0], first_line[0] + 2)
        )

        engine.mark_span_settled(*second_line)
        self.assertFalse(engine.span_is_open_for_gathering(*second_line))
        self.assertTrue(
            engine.span_is_open_for_gathering(*first_line, ignore_settle=True)
        )

        picked = engine.pick_gathering_span(prefer_line=True)
        self.assertIsNotNone(picked)

    def test_reaching_the_target_starts_the_return_to_spanish(self):
        engine = make_engine()
        start_gathering(
            engine,
            "Tell me, is the rose naked",
            "or is that her only dress?",
        )
        self.assertTrue(engine.poem_has_arrived())

        engine.process_next_sensor_trigger()
        self.assertTrue(engine.on_return_journey)
        self.assertEqual(
            engine.get_current_phase(),
            TransformationPhase.PHASE_1_WORD_BY_WORD,
        )
        self.assertEqual(engine.source_language, "English")
        self.assertEqual(engine.target_language, "Spanish")
        live = engine.get_current_transformation_state()
        self.assertIn("Tell me", live)
        self.assertNotIn("rosa", live)
        self.assertTrue(engine.phase_1_word_queue)

        engine.process_next_sensor_trigger()
        self.assertEqual(
            engine.get_current_phase(),
            TransformationPhase.PHASE_1_WORD_BY_WORD,
        )
        self.assertNotEqual(
            engine.get_current_transformation_state(),
            "Dime, la rosa está desnuda\no sólo tiene ese vestido?",
        )

    def test_english_first_line_is_not_frozen_during_return(self):
        engine = make_engine()
        start_gathering(
            engine,
            "Is it the same sun of yesterday",
            "or is it another fire of its fire?",
        )
        engine.begin_return_to_source()
        self.assertEqual(
            engine.get_current_phase(),
            TransformationPhase.PHASE_1_WORD_BY_WORD,
        )
        self.assertGreater(len(engine.phase_1_word_queue), 1)

    def test_case_difference_still_counts_as_arrival(self):
        engine = make_engine()
        start_gathering(
            engine,
            "tell me, is the rose naked",
            "Or is that her only dress?",
        )
        self.assertTrue(engine.poem_has_arrived())
        self.assertTrue(engine.all_destination_lines_matched())

    def test_return_does_not_paste_the_original_spanish(self):
        engine = make_engine()
        start_gathering(
            engine,
            "Tell me, is the rose naked",
            "or is that her only dress?",
        )
        engine.begin_return_to_source()
        for _ in range(config.GATHER_STALL_BEFORE_LANDING + 1):
            engine.process_next_sensor_trigger()
        self.assertNotEqual(
            engine.normalize_reading(engine.get_current_transformation_state()),
            engine.normalize_reading(COUPLET),
        )
        self.assertNotEqual(
            engine.get_current_phase(),
            TransformationPhase.COMPLETE,
        )

    def test_empty_word_translation_does_not_erase_the_source_word(self):
        engine = make_engine()
        tiene_index = engine.original_poem_words.index("tiene")
        engine.replace_word_in_transformation_state(tiene_index, "")
        self.assertEqual(engine.current_words[tiene_index], "tiene")
        engine.replace_word_in_transformation_state(tiene_index, "   ")
        self.assertEqual(engine.current_words[tiene_index], "tiene")
        engine.replace_word_in_transformation_state(tiene_index, "has")
        self.assertEqual(engine.current_words[tiene_index], "has")

    def test_tidy_folds_leftover_echoes_into_the_real_couplet(self):
        engine = make_engine()
        self.assertEqual(
            engine.collapse_repeated_wording("or is that  is that her only dress?"),
            "or is that her only dress?",
        )
        self.assertEqual(
            engine.fold_overlapping_leftover(
                "or is that",
                "is that her only dress?",
            ),
            "or is that her only dress?",
        )


if __name__ == "__main__":
    unittest.main()
