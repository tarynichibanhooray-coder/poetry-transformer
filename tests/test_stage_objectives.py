"""Each stage sees exactly what it is entitled to see, and nothing else."""

import json
import unittest

from openai_translator import OpenAITranslator, clean_word_output
from poem_transformer_engine import TransformationPhase
from translation_prompts import (
    GLOBAL_TRANSLATION_INSTRUCTIONS,
    PHRASE_PROMPT,
    VARIATION_PROMPT,
    WORD_PROMPT,
)
from word_senses import tether_isolated_word

from tests.test_gathering_arrival import (
    CHOSEN,
    COUPLET,
    EchoTranslator,
    make_engine,
    start_lines,
)


class CapturingTranslator(OpenAITranslator):
    """Records the layered request without calling OpenAI."""

    def __init__(self):
        self.last_exchange = None
        self.captured_prompt = None
        self.captured_stage = None
        self.captured_payload = None

    def request_translation_state(self, prompt, payload, **kwargs):
        self.captured_prompt = prompt
        self.captured_stage = payload.get("stage")
        self.captured_payload = payload
        self.last_exchange = {
            "kind": payload.get("stage"),
            "system": GLOBAL_TRANSLATION_INSTRUCTIONS,
            "user": json.dumps(payload, ensure_ascii=False),
        }
        visible = payload.get("visible_text") or ""
        if payload.get("stage") == "variations":
            return {
                "variations": [
                    {"rank": 1, "translation": "a weak reading", "captures": "little"},
                    {"rank": 2, "translation": "a middling reading", "captures": "some"},
                    {"rank": 3, "translation": "a fuller reading", "captures": "more"},
                    {"rank": 4, "translation": "a truer reading", "captures": "most"},
                    {"rank": 5, "translation": "the truest reading", "captures": "all"},
                ],
                "tokens_used": 1,
            }
        if payload.get("stage") == "phrase_edits":
            return {
                "edits": [
                    {"current_reading": "is naked", "translation": "goes bare"},
                    {"current_reading": "that dress", "translation": "only that gown"},
                    {"current_reading": "Tell me", "translation": "Say"},
                ],
                "tokens_used": 1,
            }
        return {
            "translation": "is",
            "units": [
                {
                    "id": "1",
                    "source": visible,
                    "translation": "is",
                    "alternatives": [],
                    "confidence": "open",
                }
            ],
            "revisions": [],
            "ambiguities": [],
            "tokens_used": 1,
        }


class SpyTranslator(EchoTranslator):
    def __init__(self):
        self.phrase_edit_calls = []
        self.variation_calls = []

    def request_phrase_edits(self, source_poem, current_reading, **kwargs):
        self.phrase_edit_calls.append({
            "source_poem": source_poem,
            "current_reading": current_reading,
        })
        return super().request_phrase_edits(source_poem, current_reading, **kwargs)

    def request_poem_variations(self, source_poem, current_reading, **kwargs):
        self.variation_calls.append(
            {
                "source_poem": source_poem,
                "current_reading": current_reading,
                "target_language": kwargs.get("target_language"),
            }
        )
        return super().request_poem_variations(source_poem, current_reading, **kwargs)


def payload_blob(payload):
    return json.dumps(payload or {}, ensure_ascii=False).casefold()


class StageOnePayloadTests(unittest.TestCase):
    def test_a_word_is_sent_completely_alone(self):
        translator = CapturingTranslator()
        translator.request_word_translation_with_synonyms(
            "rosa",
            "Spanish",
            "English",
            context_line="Dime, la rosa está desnuda",
            whole_poem=COUPLET,
            arriving_at=CHOSEN,
        )
        self.assertEqual(translator.captured_stage, "word")
        self.assertEqual(translator.captured_prompt, WORD_PROMPT)

        payload = translator.captured_payload
        self.assertEqual(payload["visible_text"], "rosa")
        self.assertIsNone(payload["previous_state"])
        self.assertEqual(
            set(payload.keys()),
            {"stage", "visible_text", "previous_state"},
        )

        blob = payload_blob(payload)
        self.assertNotIn("desnuda", blob)
        self.assertNotIn("vestido", blob)
        self.assertNotIn("tell me", blob)

    def test_the_engine_never_prompts_a_word_with_its_line(self):
        engine = make_engine()
        translator = CapturingTranslator()
        engine.ai_translator = translator
        engine.get_or_fetch_word_translation_with_synonyms(
            "rosa",
            "Dime, la rosa está desnuda",
        )
        self.assertNotIn("desnuda", payload_blob(translator.captured_payload))

    def test_every_real_sense_survives_but_lookalikes_do_not(self):
        primary, senses = tether_isolated_word("rosa", "rose", ["pink", "rosy"])
        self.assertEqual(primary, "rose")
        self.assertIn("pink", senses)
        self.assertNotIn("rosy", senses)

        primary, senses = tether_isolated_word("sol", "sole", ["soil", "sun", "daylight"])
        self.assertEqual(primary, "sun")
        self.assertNotIn("sole", senses)
        self.assertNotIn("soil", senses)
        self.assertIn("daylight", senses)

        primary, _ = tether_isolated_word("o", "oh", [])
        self.assertEqual(primary, "or")

    def test_a_grammar_note_never_reaches_the_page(self):
        self.assertEqual(clean_word_output("that (singular)"), "that")
        self.assertEqual(clean_word_output("noun: rose"), "rose")
        self.assertEqual(clean_word_output(" \"dress\" "), "dress")

    def test_the_word_prompt_still_forbids_lookalikes(self):
        self.assertIn("never sole", WORD_PROMPT)
        self.assertIn("standing completely alone", WORD_PROMPT)
        self.assertIn("Contractions are not allowed", GLOBAL_TRANSLATION_INSTRUCTIONS)


class StageTwoPayloadTests(unittest.TestCase):
    def test_the_call_is_given_the_poem_and_the_page_but_not_the_target(self):
        translator = CapturingTranslator()
        translator.request_phrase_edits(
            COUPLET,
            "Tell me, the rose is naked\nor only has that dress?",
        )
        self.assertEqual(translator.captured_stage, "phrase_edits")
        self.assertEqual(translator.captured_prompt, PHRASE_PROMPT)

        payload = translator.captured_payload
        self.assertEqual(payload["visible_text"], COUPLET)
        self.assertIn("only has that dress", payload["current_reading"])

        # No stage is told where the poem is going, this one included.
        blob = payload_blob(payload)
        self.assertNotIn("is the rose naked", blob)
        self.assertNotIn("her only dress", blob)

    def test_the_engine_sends_the_whole_poem_and_page_not_a_chosen_span(self):
        engine = make_engine()
        spy = SpyTranslator()
        engine.ai_translator = spy
        engine.phase_1_word_queue = []
        engine.transition_to_phrases()
        engine.process_next_sensor_trigger()

        self.assertTrue(spy.phrase_edit_calls)
        call = spy.phrase_edit_calls[-1]
        self.assertEqual(call["source_poem"], COUPLET)
        self.assertEqual(call["current_reading"], engine.get_current_transformation_state())

    def test_stage_2_requires_at_least_three_edits(self):
        translator = OpenAITranslator.__new__(OpenAITranslator)
        translator.last_exchange = None
        translator.request_translation_state = lambda *a, **k: {
            "edits": [{"current_reading": "a", "translation": "b"}],
            "tokens_used": 1,
        }
        with self.assertRaises(ValueError):
            translator.request_phrase_edits(COUPLET, "a reading")

    def test_the_phrase_prompt_asks_for_movement(self):
        self.assertIn("poetry teacher and a translator", PHRASE_PROMPT)
        self.assertIn("between three and ten", PHRASE_PROMPT)
        self.assertIn("two or three", PHRASE_PROMPT)
        self.assertIn("Reorder, combine, invert a question, fix a wrong sense", PHRASE_PROMPT)
        self.assertIn("Do not decorate", PHRASE_PROMPT)
        self.assertIn("copied verbatim", PHRASE_PROMPT)

    def test_an_edit_may_not_quietly_lose_a_noun(self):
        engine = make_engine()
        engine.phase_1_word_queue = []
        engine.transition_to_phrases()
        before = engine.get_current_transformation_state()

        engine.phrase_edit_queue = [
            # Drops "rosa", a noun the scrap names -- refused.
            {"current_reading": "rosa está desnuda", "translation": "está desnuda"},
            # A real change, further down the same batch.
            {"current_reading": "ese vestido", "translation": "aquel vestido"},
        ]
        engine.process_next_sensor_trigger()

        self.assertNotEqual(engine.get_current_transformation_state(), before)
        self.assertEqual(engine.last_block_defect, "dropped_image")
        self.assertIn("aquel vestido", engine.get_current_transformation_state())
        self.assertEqual(engine.phrase_edit_queue, [])

    def test_a_copy_of_the_current_wording_is_not_applied(self):
        engine = make_engine()
        engine.phase_1_word_queue = []
        engine.transition_to_phrases()
        before = engine.get_current_transformation_state()

        engine.phrase_edit_queue = [
            {"current_reading": "la rosa", "translation": "la rosa"},
        ]
        engine.process_next_sensor_trigger()

        self.assertEqual(engine.get_current_transformation_state(), before)
        self.assertIsNone(engine.last_changed_span)

    def test_an_edit_naming_wording_no_longer_on_the_page_is_skipped(self):
        engine = make_engine()
        engine.phase_1_word_queue = []
        engine.transition_to_phrases()
        before = engine.get_current_transformation_state()

        engine.phrase_edit_queue = [
            {"current_reading": "not on the page at all", "translation": "anything"},
            {"current_reading": "ese vestido", "translation": "aquel vestido"},
        ]
        engine.process_next_sensor_trigger()

        self.assertNotEqual(engine.get_current_transformation_state(), before)
        self.assertIn("aquel vestido", engine.get_current_transformation_state())

    def test_one_applied_edit_is_one_trigger(self):
        engine = make_engine()
        engine.phase_1_word_queue = []
        engine.transition_to_phrases()
        before = engine.get_current_transformation_state()

        engine.phrase_edit_queue = [
            {"current_reading": "la rosa", "translation": "esa rosa"},
            {"current_reading": "ese vestido", "translation": "aquel vestido"},
        ]
        engine.process_next_sensor_trigger()

        self.assertNotEqual(engine.get_current_transformation_state(), before)
        self.assertEqual(len(engine.phrase_edit_queue), 1)
        self.assertEqual(engine.get_current_phase(), TransformationPhase.PHRASES)


class StageThreePayloadTests(unittest.TestCase):
    def test_the_whole_poem_is_sent_and_the_target_is_not(self):
        translator = CapturingTranslator()
        translator.request_poem_variations(
            COUPLET,
            "Tell me, the rose is naked\nor only has that dress?",
            target_language="English",
        )
        self.assertEqual(translator.captured_stage, "variations")
        self.assertEqual(translator.captured_prompt, VARIATION_PROMPT)

        payload = translator.captured_payload
        self.assertEqual(payload["visible_text"], COUPLET)
        self.assertEqual(payload["write_in_language"], "English")
        self.assertIn("only has that dress", payload["current_reading"])

        # No stage is told where the poem is going, this one included.
        blob = payload_blob(payload)
        self.assertNotIn("is the rose naked", blob)
        self.assertNotIn("her only dress", blob)

    def test_the_engine_never_sends_the_chosen_rendering(self):
        engine = make_engine()
        spy = SpyTranslator()
        engine.ai_translator = spy
        start_lines(
            engine,
            "Tell me, the rose is naked",
            "or only has that dress?",
        )
        engine.process_next_sensor_trigger()

        self.assertTrue(spy.variation_calls)
        call = spy.variation_calls[-1]
        self.assertEqual(call["source_poem"], COUPLET)
        self.assertNotIn("her only dress", call["current_reading"])
        self.assertEqual(call["target_language"], "English")

    def test_attempts_come_back_in_rank_order(self):
        translator = OpenAITranslator.__new__(OpenAITranslator)
        variations = translator.variations_from_state(
            {
                "variations": [
                    {"rank": 3, "translation": "best reading", "captures": "all"},
                    {"rank": 1, "translation": "worst reading", "captures": "little"},
                    {"rank": 2, "translation": "middling reading", "captures": "some"},
                ]
            }
        )
        self.assertEqual(
            [item["translation"] for item in variations],
            ["worst reading", "middling reading", "best reading"],
        )

    def test_a_repeated_attempt_is_only_offered_once(self):
        translator = OpenAITranslator.__new__(OpenAITranslator)
        variations = translator.variations_from_state(
            {
                "variations": [
                    {"rank": 1, "translation": "the rose is bare", "captures": ""},
                    {"rank": 2, "translation": "The Rose Is Bare", "captures": ""},
                    {"rank": 3, "translation": "", "captures": ""},
                ]
            }
        )
        self.assertEqual(len(variations), 1)

    def test_the_variation_prompt_asks_for_ranked_whole_readings(self):
        self.assertIn("at least five", VARIATION_PROMPT)
        self.assertIn("capture the original meaning", VARIATION_PROMPT)
        self.assertIn("worst to best", VARIATION_PROMPT)
        self.assertIn("lines_expected", VARIATION_PROMPT)


class StageOrderTests(unittest.TestCase):
    def test_words_then_phrases_then_lines_then_swap(self):
        engine = make_engine()
        self.assertEqual(engine.get_current_phase(), TransformationPhase.WORDS)

        engine.phase_1_word_queue = []
        engine.transition_to_phrases()
        self.assertEqual(engine.get_current_phase(), TransformationPhase.PHRASES)

        engine.phrase_edit_queue = []
        engine.process_next_sensor_trigger()
        self.assertEqual(engine.get_current_phase(), TransformationPhase.LINES)

        start_lines(
            engine,
            "Tell me, is the rose naked",
            "or is that her only dress?",
        )
        self.assertEqual(engine.get_current_phase(), TransformationPhase.LINES)

        for _ in range(20):
            if engine.on_return_journey:
                break
            engine.process_next_sensor_trigger()

        self.assertTrue(engine.on_return_journey)
        self.assertEqual(engine.get_current_phase(), TransformationPhase.WORDS)
        self.assertEqual(engine.source_language, "English")
        self.assertEqual(engine.target_language, "Spanish")

    def test_the_last_word_moves_the_engine_on_to_scraps(self):
        engine = make_engine()
        while engine.phase_1_word_queue:
            engine.process_next_sensor_trigger()
        self.assertEqual(engine.get_current_phase(), TransformationPhase.PHRASES)


class LayeredRequestTests(unittest.TestCase):
    def test_layered_request_sends_three_roles(self):
        translator = OpenAITranslator.__new__(OpenAITranslator)
        captured = {}

        def fake_complete(messages, *args):
            captured["messages"] = messages
            return {
                "translation": "is",
                "units": [],
                "revisions": [],
                "ambiguities": [],
            }

        translator._complete_json = fake_complete
        translator.send_layered_request("STAGE TEXT", '{"stage":"phrase"}')
        messages = captured["messages"]
        self.assertEqual(
            [message["role"] for message in messages],
            ["system", "developer", "user"],
        )
        self.assertEqual(messages[0]["content"], GLOBAL_TRANSLATION_INSTRUCTIONS)
        self.assertEqual(messages[1]["content"], "STAGE TEXT")
        self.assertEqual(messages[2]["content"], '{"stage":"phrase"}')

    def test_edits_are_deduplicated_and_blank_ones_dropped(self):
        translator = OpenAITranslator.__new__(OpenAITranslator)
        edits = translator.phrase_edits_from_state({
            "edits": [
                {"current_reading": "la rosa", "translation": "esa rosa"},
                {"current_reading": "La Rosa", "translation": "Esa Rosa"},
                {"current_reading": "", "translation": "anything"},
                {"current_reading": "ese vestido", "translation": ""},
            ]
        })
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0]["current_reading"], "la rosa")

    def test_a_no_op_edit_is_not_offered(self):
        translator = OpenAITranslator.__new__(OpenAITranslator)
        edits = translator.phrase_edits_from_state({
            "edits": [
                {"current_reading": "la rosa", "translation": "La Rosa"},
                {"current_reading": "ese vestido", "translation": "aquel vestido"},
            ]
        })
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0]["current_reading"], "ese vestido")


if __name__ == "__main__":
    unittest.main()
