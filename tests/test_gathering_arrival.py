"""Stage 3 shows a field of complete attempts, worst first, and lands on the
chosen rendering. The poem always turns around and comes home."""

import unittest

import config
from poem_transformer_engine import PoemTransformerEngine, TransformationPhase
from translation_units import UnitPoem, reading_distance
from word_senses import anchor_word_to_origin

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
    """Never moves anything, so the engine's own rules are what is tested."""

    def request_word_translation_with_synonyms(self, word, src=None, tgt=None, **kwargs):
        return {"primary_translation": f"<{word}>", "synonyms": [], "tokens_used": 1}

    def validate_word_translation_response(self, response):
        return True

    def request_phrase_translation(self, scrap_source, **kwargs):
        reading = kwargs.get("current_reading") or scrap_source
        return {
            "lines": [reading],
            "segments": [reading],
            "unchanged": True,
            "improvement": "echo",
            "translation_state": {},
            "tokens_used": 1,
        }

    def request_poem_variations(self, source_poem, current_reading, **kwargs):
        return []

    def validate_block_translation_response(self, response):
        return True


class VariationTranslator(EchoTranslator):
    """Three ranked attempts, worst first, none of them the chosen rendering."""

    ATTEMPTS = [
        "Say, the rose goes bare\nor wears just that gown?",
        "Tell me, the rose is bare\nor has it only that dress?",
        "Tell me, is the rose naked\nor is that her one dress?",
    ]

    def request_poem_variations(self, source_poem, current_reading, **kwargs):
        return [
            {"rank": position, "translation": text, "captures": f"reading {position}"}
            for position, text in enumerate(self.ATTEMPTS, start=1)
        ]


def make_engine(poem=COUPLET, destination=CHOSEN):
    engine = PoemTransformerEngine(random_seed=1)
    engine.database_manager = FakeDatabase()
    engine.ai_translator = EchoTranslator()
    engine.initialize_poem_with_text(poem, final_translation=destination)
    return engine


def start_lines(engine, *lines):
    """Put a reading on the page and drop the engine into stage 3."""
    engine.phase_1_word_queue = []
    engine.transition_to_phrases()
    engine.phrase_span_queue = []
    for line_index, line in enumerate(lines):
        engine.place_line_reading(line_index, line)
    engine.transition_to_lines()


class UnitStateTests(unittest.TestCase):
    def test_a_unit_may_hold_more_words_than_its_source(self):
        engine = make_engine()
        engine.replace_word_in_transformation_state(0, "Tell me,")
        self.assertEqual(engine.current_words[0], "Tell me,")
        self.assertTrue(
            engine.get_current_transformation_state().startswith("Tell me,")
        )

    def test_emptied_units_keep_the_line_break(self):
        poem = UnitPoem.from_text(COUPLET)
        poem.units[4].text = ""
        rendered = poem.render()
        self.assertEqual(len(rendered.split("\n")), 2)
        self.assertNotIn("desnuda", rendered)

    def test_the_page_keeps_one_span_per_unit(self):
        engine = make_engine()
        self.assertEqual(
            len(engine.current_words),
            len(engine.word_separators),
        )
        self.assertEqual(len(engine.current_words), len(engine.original_poem_words))



class StageThreeVariationTests(unittest.TestCase):
    def test_there_is_no_numbered_plan_to_the_target(self):
        engine = make_engine()
        stats = engine.get_transformation_statistics()
        self.assertIsNone(stats["planned_operations"])
        self.assertEqual(engine.destination_lines, CHOSEN.split("\n"))

    def test_attempts_arrive_one_per_trigger_worst_first(self):
        engine = make_engine()
        engine.ai_translator = VariationTranslator()
        start_lines(engine, "Tell me, the rose is naked", "or only has that dress?")

        shown = []
        for _ in range(len(VariationTranslator.ATTEMPTS) + 1):
            engine.process_next_sensor_trigger()
            shown.append(engine.get_current_transformation_state())

        self.assertEqual(shown[:3], VariationTranslator.ATTEMPTS)
        self.assertEqual(shown[3], CHOSEN)

    def test_the_chosen_rendering_is_shown_last(self):
        engine = make_engine()
        engine.ai_translator = VariationTranslator()
        start_lines(engine, "Tell me, the rose is naked", "or only has that dress?")

        last = None
        for _ in range(20):
            if engine.on_return_journey:
                break
            engine.process_next_sensor_trigger()
            last = engine.get_current_transformation_state()

        self.assertEqual(last, CHOSEN)
        self.assertTrue(engine.on_return_journey)

    def test_an_attempt_that_is_already_the_rendering_is_not_shown_twice(self):
        engine = make_engine()

        class ArrivingTranslator(EchoTranslator):
            def request_poem_variations(self, source_poem, current_reading, **kwargs):
                return [
                    {"rank": 1, "translation": "Say, the rose goes bare\nor wears that gown?",
                     "captures": "loose"},
                    {"rank": 2, "translation": CHOSEN, "captures": "exact"},
                ]

        engine.ai_translator = ArrivingTranslator()
        start_lines(engine, "Tell me, the rose is naked", "or only has that dress?")

        readings = []
        for _ in range(2):
            engine.process_next_sensor_trigger()
            readings.append(engine.get_current_transformation_state())

        self.assertEqual(readings[-1], CHOSEN)
        self.assertEqual(readings.count(CHOSEN), 1)
        self.assertTrue(engine.on_return_journey)

    def test_every_attempt_rewrites_the_whole_poem(self):
        engine = make_engine()
        engine.ai_translator = VariationTranslator()
        start_lines(engine, "Tell me, the rose is naked", "or only has that dress?")
        engine.process_next_sensor_trigger()

        reading = engine.get_current_transformation_state()
        self.assertEqual(len(reading.split("\n")), 2)
        self.assertEqual(reading, VariationTranslator.ATTEMPTS[0])
        self.assertEqual(engine.last_changed_span, (0, len(engine.poem.units)))

    def test_the_attempts_are_kept_as_roads_not_taken(self):
        engine = make_engine()
        engine.ai_translator = VariationTranslator()
        start_lines(engine, "Tell me, the rose is naked", "or only has that dress?")
        engine.process_next_sensor_trigger()

        self.assertEqual(
            engine.last_block_drafts,
            VariationTranslator.ATTEMPTS + [CHOSEN],
        )

    def test_an_attempt_with_the_wrong_line_count_leaves_nothing_stale(self):
        engine = make_engine()

        class OneLineTranslator(EchoTranslator):
            def request_poem_variations(self, source_poem, current_reading, **kwargs):
                return [{
                    "rank": 1,
                    "translation": "Is the rose bare or is that all it wears?",
                    "captures": "one line",
                }]

        engine.ai_translator = OneLineTranslator()
        start_lines(engine, "Tell me, the rose is naked", "or only has that dress?")
        engine.process_next_sensor_trigger()

        reading = engine.get_current_transformation_state()
        self.assertNotIn("only has that dress", reading)
        self.assertNotIn("Tell me, the rose is naked", reading)
        self.assertIn("bare", reading)

    def test_a_silent_model_still_lands_on_the_rendering(self):
        engine = make_engine()
        start_lines(engine, "Tell me, the rose is naked", "or only has that dress?")
        engine.process_next_sensor_trigger()
        self.assertEqual(engine.get_current_transformation_state(), CHOSEN)
        self.assertTrue(engine.on_return_journey)


class RoundTripTests(unittest.TestCase):
    def walk_to_the_rendering(self, engine):
        for _ in range(20):
            if engine.on_return_journey:
                return
            engine.process_next_sensor_trigger()

    def test_reaching_the_rendering_swaps_the_languages(self):
        engine = make_engine()
        engine.ai_translator = VariationTranslator()
        start_lines(engine, "Tell me, the rose is naked", "or only has that dress?")
        self.walk_to_the_rendering(engine)

        self.assertTrue(engine.on_return_journey)
        self.assertEqual(engine.get_current_phase(), TransformationPhase.WORDS)
        self.assertEqual(engine.source_language, "English")
        self.assertEqual(engine.target_language, "Spanish")

        live = engine.get_current_transformation_state()
        self.assertIn("Tell me", live)
        self.assertNotIn("rosa", live)
        self.assertTrue(engine.phase_1_word_queue)

    def test_the_return_journey_aims_at_the_original(self):
        engine = make_engine()
        engine.ai_translator = VariationTranslator()
        start_lines(engine, "Tell me, the rose is naked", "or only has that dress?")
        self.walk_to_the_rendering(engine)
        self.assertEqual(engine.destination_lines, COUPLET.split("\n"))

    def test_the_return_does_not_paste_the_original_spanish(self):
        engine = make_engine()
        engine.ai_translator = VariationTranslator()
        start_lines(engine, "Tell me, the rose is naked", "or only has that dress?")
        self.walk_to_the_rendering(engine)

        engine.process_next_sensor_trigger()
        self.assertNotEqual(
            engine.get_current_transformation_state().casefold(),
            COUPLET.casefold(),
        )
        self.assertNotEqual(engine.get_current_phase(), TransformationPhase.COMPLETE)

    def test_coming_home_completes_the_piece(self):
        engine = make_engine()
        engine.ai_translator = VariationTranslator()
        start_lines(engine, "Tell me, the rose is naked", "or only has that dress?")
        self.walk_to_the_rendering(engine)

        start_lines(engine, *COUPLET.split("\n"))
        for _ in range(20):
            if engine.get_current_phase() == TransformationPhase.COMPLETE:
                break
            engine.process_next_sensor_trigger()

        self.assertEqual(engine.get_current_phase(), TransformationPhase.COMPLETE)
        self.assertEqual(engine.get_current_transformation_state(), COUPLET)

    def test_arrival_is_punctuation_exact(self):
        engine = make_engine()
        engine.poem = engine.poem
        start_lines(engine, "Tell me, is the rose naked", "or is that her only dress")
        self.assertFalse(engine.poem_has_arrived())
        start_lines(engine, *CHOSEN.split("\n"))
        self.assertTrue(engine.poem_has_arrived())

    def test_case_difference_still_counts_as_arrival(self):
        engine = make_engine()
        start_lines(engine, "tell me, is the rose naked", "Or is that her only dress?")
        self.assertTrue(engine.poem_has_arrived())


class SpanishToEnglish(EchoTranslator):
    """A plain outbound stage 1, so the origins recorded are realistic."""

    GLOSSES = {
        "Dime,": ("Tell me", []),
        "la": ("the", []),
        "rosa": ("rose", ["pink"]),
        "está": ("is", []),
        "desnuda": ("naked", ["bare"]),
        "o": ("or", []),
        "sólo": ("only", ["just"]),
        "tiene": ("has", []),
        "ese": ("that", []),
        "vestido?": ("dress", ["clothed"]),
    }

    def __init__(self):
        self.origins_seen = []

    def request_word_translation_with_synonyms(
        self, word, src=None, tgt=None, origin_word=None, **kwargs
    ):
        self.origins_seen.append((word, origin_word))
        primary, synonyms = self.GLOSSES.get(word, (word, []))
        return {
            "primary_translation": primary,
            "synonyms": list(synonyms),
            "tokens_used": 1,
        }


def walk_stage_one(engine):
    while engine.get_current_phase() == TransformationPhase.WORDS:
        engine.process_next_sensor_trigger()


class WordOriginTests(unittest.TestCase):
    """A word going out is ambiguous. Coming back it is not: it has been
    through here, and the sense it used is the sense it has."""

    def outbound_engine(self):
        engine = make_engine()
        engine.ai_translator = SpanishToEnglish()
        walk_stage_one(engine)
        return engine

    def test_a_one_word_reading_records_where_it_came_from(self):
        engine = self.outbound_engine()
        self.assertEqual(engine.word_origins["rose"], "rosa")
        self.assertEqual(engine.word_origins["dress"], "vestido?")

    def test_a_reading_of_two_words_records_no_origin(self):
        engine = self.outbound_engine()
        # "Dime," arrived as "Tell me". Filing Dime under both halves would
        # bring the poem home saying it twice.
        self.assertNotIn("tell", engine.word_origins)
        self.assertNotIn("me", engine.word_origins)

    def test_going_out_a_word_is_told_nothing_about_its_origin(self):
        engine = self.outbound_engine()
        self.assertIsNone(engine.origin_for_word("rosa"))
        self.assertTrue(
            all(origin is None for _, origin in engine.ai_translator.origins_seen)
        )

    def test_coming_back_the_origin_is_remembered(self):
        engine = self.outbound_engine()
        engine.on_return_journey = True
        self.assertEqual(engine.origin_for_word("rose"), "rosa")
        self.assertEqual(engine.origin_for_word("Rose"), "rosa")
        self.assertEqual(engine.origin_for_word("rose,"), "rosa")

    def test_a_word_the_poem_never_made_has_no_origin(self):
        engine = self.outbound_engine()
        engine.on_return_journey = True
        # Stage 3 is free to introduce words of its own; they have no history.
        self.assertIsNone(engine.origin_for_word("her"))

    def test_the_origins_survive_the_turnaround(self):
        engine = make_engine()
        engine.ai_translator = VariationTranslator()
        start_lines(engine, "Tell me, the rose is naked", "or only has that dress?")
        engine.word_origins = {"rose": "rosa"}

        for _ in range(20):
            if engine.on_return_journey:
                break
            engine.process_next_sensor_trigger()

        self.assertTrue(engine.on_return_journey)
        self.assertEqual(engine.origin_for_word("rose"), "rosa")

    def test_the_return_asks_with_the_origin_attached(self):
        engine = self.outbound_engine()
        engine.on_return_journey = True
        engine.ai_translator.origins_seen.clear()
        engine.get_or_fetch_word_translation_with_synonyms("rose")
        self.assertEqual(engine.ai_translator.origins_seen, [("rose", "rosa")])

    def test_a_new_poem_forgets_the_last_one(self):
        engine = self.outbound_engine()
        self.assertTrue(engine.word_origins)
        engine.initialize_poem_with_text(COUPLET, final_translation=CHOSEN)
        self.assertEqual(engine.word_origins, {})


class OriginAnchorTests(unittest.TestCase):
    """The reading a returning word settles on is decided here, not asked for."""

    def test_the_word_settles_on_its_origin(self):
        response = anchor_word_to_origin(
            {"primary_translation": "subió", "synonyms": ["ascendió"]},
            "rosa",
        )
        self.assertEqual(response["primary_translation"], "rosa")
        self.assertEqual(response["target_word"], "rosa")

    def test_the_origin_is_not_also_offered_as_a_flicker(self):
        response = anchor_word_to_origin(
            {"primary_translation": "rosa", "synonyms": ["Rosa", "flor"]},
            "rosa",
        )
        self.assertEqual(response["synonyms"], ["flor"])

    def test_a_word_with_no_origin_is_left_alone(self):
        response = anchor_word_to_origin(
            {"primary_translation": "su", "synonyms": ["de ella"]},
            None,
        )
        self.assertEqual(response["primary_translation"], "su")
        self.assertEqual(response["synonyms"], ["de ella"])


if __name__ == "__main__":
    unittest.main()
