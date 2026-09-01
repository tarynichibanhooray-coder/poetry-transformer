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
                    {"rank": 1, "translation": "a reading", "captures": "little"},
                    {"rank": 2, "translation": "a truer reading", "captures": "more"},
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
        self.phrase_calls = []
        self.variation_calls = []

    def request_phrase_translation(self, scrap_source, **kwargs):
        self.phrase_calls.append({"scrap_source": scrap_source, **kwargs})
        return super().request_phrase_translation(scrap_source, **kwargs)

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
    def test_a_scrap_is_sent_with_its_line_but_not_the_target(self):
        translator = CapturingTranslator()
        translator.request_phrase_translation(
            "rosa está desnuda",
            source_line="Dime, la rosa está desnuda",
            current_reading="the rose is naked",
        )
        self.assertEqual(translator.captured_stage, "phrase")
        self.assertEqual(translator.captured_prompt, PHRASE_PROMPT)

        payload = translator.captured_payload
        self.assertEqual(payload["visible_text"], "rosa está desnuda")
        self.assertEqual(payload["source_line"], "Dime, la rosa está desnuda")
        self.assertEqual(payload["current_reading"], "the rose is naked")

        blob = payload_blob(payload)
        self.assertNotIn("vestido", blob)
        self.assertNotIn("tell me, is the rose naked", blob)

    def test_the_engine_sends_the_whole_line_as_context(self):
        engine = make_engine()
        spy = SpyTranslator()
        engine.ai_translator = spy
        engine.phase_1_word_queue = []
        engine.transition_to_phrases()
        engine.process_next_sensor_trigger()

        self.assertTrue(spy.phrase_calls)
        call = spy.phrase_calls[-1]
        self.assertIn(call["source_line"], COUPLET.split("\n"))
        self.assertIn(call["scrap_source"], call["source_line"])
        self.assertNotEqual(call["scrap_source"], "")

    def test_a_scrap_is_two_or_three_units(self):
        engine = make_engine()
        engine.phase_1_word_queue = []
        engine.transition_to_phrases()
        self.assertTrue(engine.phrase_span_queue)
        for start, end in engine.phrase_span_queue:
            self.assertGreaterEqual(end - start, 2)
            self.assertLessEqual(end - start, 4)

    def test_the_phrase_prompt_asks_for_movement(self):
        self.assertIn("Move the words", PHRASE_PROMPT)
        self.assertIn("is the rose", PHRASE_PROMPT)
        self.assertIn("Return this scrap alone", PHRASE_PROMPT)
        self.assertIn("has to survive", PHRASE_PROMPT)

    def test_a_scrap_may_not_quietly_lose_a_noun(self):
        engine = make_engine()
        engine.phase_1_word_queue = []
        engine.transition_to_phrases()
        engine.phrase_span_queue = [(2, 5)]
        for index, text in enumerate(["Tell me,", "the", "rose", "is", "naked"]):
            engine.poem.units[index].text = text
        before = engine.get_current_transformation_state()

        class DroppingTranslator(EchoTranslator):
            def request_phrase_translation(self, scrap_source, **kwargs):
                return {
                    "lines": ["is naked"],
                    "segments": ["is naked"],
                    "improvement": "tightened",
                    "tokens_used": 1,
                }

        engine.ai_translator = DroppingTranslator()
        engine.process_next_sensor_trigger()
        self.assertEqual(engine.get_current_transformation_state(), before)
        self.assertEqual(engine.last_block_defect, "dropped_image")


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

        engine.phrase_span_queue = []
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

    def test_the_models_own_segmentation_comes_back_as_segments(self):
        translator = OpenAITranslator.__new__(OpenAITranslator)
        response = translator.block_response_from_state(
            {
                "translation": "is the rose",
                "units": [
                    {"id": "1", "source": "está", "translation": "is",
                     "alternatives": [], "confidence": "resolved"},
                    {"id": "2", "source": "la", "translation": "the",
                     "alternatives": [], "confidence": "resolved"},
                    {"id": "3", "source": "rosa", "translation": "rose",
                     "alternatives": [], "confidence": "resolved"},
                ],
                "revisions": [],
                "ambiguities": [],
            },
            ["the rose is"],
        )
        self.assertEqual(response["segments"], ["is", "the", "rose"])

    def test_an_unsegmented_answer_still_yields_one_segment(self):
        translator = OpenAITranslator.__new__(OpenAITranslator)
        response = translator.block_response_from_state(
            {
                "translation": "is the rose",
                "units": [],
                "revisions": [],
                "ambiguities": [],
            },
            ["the rose is"],
        )
        self.assertEqual(response["segments"], ["is the rose"])


if __name__ == "__main__":
    unittest.main()
