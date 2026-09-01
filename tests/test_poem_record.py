"""A poem keeps a record of every reading it has been given.

The event stream in output/ is a log of one performance. This is the poem's
own notebook: what the model answered at each stage, and what was corrected
by hand afterwards.
"""

import tempfile
import unittest
from pathlib import Path

from database_manager import DatabaseManager
from poem_transformer_engine import PoemTransformerEngine, TransformationPhase

COUPLET = "Dime, la rosa está desnuda\no sólo tiene ese vestido?"
CHOSEN = "Tell me, is the rose naked\nor is that her only dress?"

LANGUAGE_PAIR = {
    "source_language": "Spanish",
    "source_language_code": "es",
    "target_language": "English",
    "target_language_code": "en",
}


class WordTranslator:
    """Stage 1 only, with a fixed gloss for every word of the couplet."""

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

    def request_word_translation_with_synonyms(self, word, src=None, tgt=None, **kwargs):
        primary, synonyms = self.GLOSSES.get(word, (word, []))
        return {
            "primary_translation": primary,
            "synonyms": list(synonyms),
            "tokens_used": 1,
        }

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
        return [
            {"rank": 1, "translation": "Say, the rose goes bare\nor wears that gown?",
             "captures": "loses the asking"},
            {"rank": 2, "translation": "Tell me, is the rose bare\nor is that its one dress?",
             "captures": "keeps the asking"},
        ]

    def validate_block_translation_response(self, response):
        return True


class RecordTestCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = DatabaseManager(
            database_path=Path(self.directory.name) / "record.db"
        )
        self.poem_id = self.database.store_or_update_poem_entry(
            raw_text=COUPLET,
            title="Libro de las preguntas",
            final_translation=CHOSEN,
            **LANGUAGE_PAIR
        )

    def tearDown(self):
        self.database.close_database_connection()
        self.directory.cleanup()

    def make_engine(self, with_poem_id=True):
        engine = PoemTransformerEngine(random_seed=1)
        engine.database_manager = self.database
        engine.ai_translator = WordTranslator()
        engine.initialize_poem_with_text(COUPLET, final_translation=CHOSEN)
        if with_poem_id:
            engine.poem_id = self.poem_id
        return engine

    def walk_stage_one(self, engine):
        while engine.get_current_phase() == TransformationPhase.WORDS:
            engine.process_next_sensor_trigger()

    def readings(self, stage=None):
        rows = self.database.retrieve_poem_iterations(self.poem_id)
        if stage:
            rows = [row for row in rows if row["stage"] == stage]
        return rows


class StoringReadingsTests(RecordTestCase):
    def test_a_reading_comes_back_as_it_went_in(self):
        self.database.record_poem_iteration(
            self.poem_id, "words", "rose",
            source_text="rosa", note="the flower", alternatives=["pink"]
        )
        reading = self.readings("words")[0]
        self.assertEqual(reading["content"], "rose")
        self.assertEqual(reading["source_text"], "rosa")
        self.assertEqual(reading["note"], "the flower")
        self.assertEqual(reading["alternatives"], ["pink"])
        self.assertEqual(reading["origin"], "api")
        self.assertFalse(reading["edited"])

    def test_each_stage_numbers_its_own_readings(self):
        for word in ("rose", "naked", "dress"):
            self.database.record_poem_iteration(self.poem_id, "words", word)
        self.database.record_poem_iteration(self.poem_id, "lines", "Tell me")

        self.assertEqual([row["position"] for row in self.readings("words")], [1, 2, 3])
        self.assertEqual([row["position"] for row in self.readings("lines")], [1])

    def test_an_empty_reading_is_not_recorded(self):
        self.assertIsNone(
            self.database.record_poem_iteration(self.poem_id, "words", "   ")
        )
        self.assertEqual(self.readings(), [])

    def test_a_poem_with_no_library_row_has_nowhere_to_file_a_reading(self):
        self.assertIsNone(self.database.record_poem_iteration(None, "words", "rose"))

    def test_the_stages_are_counted_separately(self):
        self.database.record_poem_iteration(self.poem_id, "words", "rose")
        self.database.record_poem_iteration(self.poem_id, "words", "naked")
        self.database.record_poem_iteration(self.poem_id, "lines", "Tell me")

        self.assertEqual(
            self.database.count_poem_iterations_by_stage(self.poem_id),
            {"words": 2, "lines": 1},
        )


class EditingReadingsTests(RecordTestCase):
    def test_changing_a_model_answer_marks_it_edited(self):
        reading_id = self.database.record_poem_iteration(
            self.poem_id, "words", "subió", source_text="rose"
        )
        updated = self.database.update_poem_iteration(reading_id, content="rosa")

        self.assertEqual(updated["content"], "rosa")
        self.assertTrue(updated["edited"])
        self.assertEqual(updated["origin"], "api")

    def test_a_reading_written_by_hand_is_not_called_edited(self):
        reading_id = self.database.record_poem_iteration(
            self.poem_id, "lines", "Tell me, is the rose bare", origin="hand"
        )
        updated = self.database.update_poem_iteration(
            reading_id, content="Tell me, is the rose naked"
        )

        self.assertEqual(updated["origin"], "hand")
        self.assertFalse(updated["edited"])

    def test_a_note_can_be_changed_without_touching_the_reading(self):
        reading_id = self.database.record_poem_iteration(
            self.poem_id, "words", "rose", note="first thought"
        )
        updated = self.database.update_poem_iteration(reading_id, note="second thought")

        self.assertEqual(updated["content"], "rose")
        self.assertEqual(updated["note"], "second thought")
        self.assertFalse(updated["edited"])

    def test_a_reading_cannot_be_emptied(self):
        reading_id = self.database.record_poem_iteration(self.poem_id, "words", "rose")
        self.assertIsNone(self.database.update_poem_iteration(reading_id, content="  "))
        self.assertEqual(self.readings("words")[0]["content"], "rose")

    def test_editing_something_that_is_not_there(self):
        self.assertIsNone(self.database.update_poem_iteration(9999, content="rosa"))

    def test_a_reading_can_be_taken_off_the_record(self):
        reading_id = self.database.record_poem_iteration(self.poem_id, "words", "rose")
        self.assertTrue(self.database.delete_poem_iteration(reading_id))
        self.assertEqual(self.readings(), [])
        self.assertFalse(self.database.delete_poem_iteration(reading_id))


class EngineRecordsItsPassageTests(RecordTestCase):
    def test_every_word_the_model_answered_is_on_the_record(self):
        engine = self.make_engine()
        self.walk_stage_one(engine)

        words = self.readings("words")
        self.assertEqual(len(words), len(engine.original_poem_words))
        self.assertEqual(
            {row["source_text"]: row["content"] for row in words}["rosa"], "rose"
        )

    def test_the_senses_offered_alongside_are_kept(self):
        engine = self.make_engine()
        self.walk_stage_one(engine)

        rosa = next(row for row in self.readings("words") if row["source_text"] == "rosa")
        self.assertEqual(rosa["alternatives"], ["pink"])

    def test_the_whole_ranked_field_is_recorded_not_only_what_was_shown(self):
        engine = self.make_engine()
        engine.load_variations()

        lines = self.readings("lines")
        # Two attempts, plus the chosen rendering the walk ends on.
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[-1]["content"], CHOSEN)
        self.assertIn("attempt 1", lines[0]["note"])

    def test_a_scrap_rewrite_is_recorded_with_what_it_bettered(self):
        engine = self.make_engine()
        self.walk_stage_one(engine)
        engine.process_next_sensor_trigger()

        phrases = self.readings("phrases")
        self.assertTrue(phrases)
        self.assertEqual(phrases[0]["note"], "echo")

    def test_the_way_home_is_marked_as_such(self):
        engine = self.make_engine()
        engine.on_return_journey = True
        engine.get_or_fetch_word_translation_with_synonyms("rosa")

        self.assertEqual(self.readings("words")[0]["journey"], "home")

    def test_an_engine_with_no_poem_behind_it_records_nothing(self):
        engine = self.make_engine(with_poem_id=False)
        self.walk_stage_one(engine)
        self.assertEqual(self.readings(), [])


class ActiveFlagTests(RecordTestCase):
    """A poem leaves the rotation by being switched off, not by being deleted."""

    def test_a_new_poem_is_in_the_rotation(self):
        poem = self.database.retrieve_poem_entry_by_id(self.poem_id)
        self.assertTrue(poem["active"])

    def test_switching_a_poem_off_leaves_it_in_the_library(self):
        self.database.set_poem_active(self.poem_id, False)

        self.assertFalse(self.database.retrieve_poem_entry_by_id(self.poem_id)["active"])
        self.assertEqual(len(self.database.retrieve_all_poem_entries()), 1)
        self.assertEqual(self.database.retrieve_active_poem_entries(), [])

    def test_switching_a_poem_off_keeps_its_record(self):
        self.database.record_poem_iteration(self.poem_id, "words", "sun")
        self.database.set_poem_active(self.poem_id, False)

        self.assertEqual(len(self.readings()), 1)

    def test_a_poem_can_come_back(self):
        self.database.set_poem_active(self.poem_id, False)
        poem = self.database.set_poem_active(self.poem_id, True)

        self.assertTrue(poem["active"])
        self.assertEqual(len(self.database.retrieve_active_poem_entries()), 1)

    def test_switching_something_that_is_not_there(self):
        self.assertIsNone(self.database.set_poem_active(9999, False))

    def test_re_saving_a_poem_does_not_put_it_back_in_the_rotation(self):
        self.database.set_poem_active(self.poem_id, False)
        self.database.store_or_update_poem_entry(
            raw_text=COUPLET, title="Libro de las preguntas", **LANGUAGE_PAIR
        )
        self.assertFalse(self.database.retrieve_poem_entry_by_id(self.poem_id)["active"])


class DeletingAPoemTests(RecordTestCase):
    """Deleting is the destructive option: the readings go with the poem."""

    def test_the_readings_go_with_the_poem(self):
        for stage, content in (("words", "sun"), ("phrases", "the same sun"),
                               ("lines", "Is it the same sun as yesterday")):
            self.database.record_poem_iteration(self.poem_id, stage, content)
        self.assertEqual(len(self.readings()), 3)

        self.assertTrue(self.database.delete_poem_entry(self.poem_id))

        self.assertIsNone(self.database.retrieve_poem_entry_by_id(self.poem_id))
        self.assertEqual(self.database.retrieve_poem_iterations(self.poem_id), [])

    def test_no_reading_is_left_behind_anywhere(self):
        self.database.record_poem_iteration(self.poem_id, "words", "sun")
        self.database.delete_poem_entry(self.poem_id)

        # Straight at the table, not filtered by poem, so an orphan would show.
        self.database.cursor.execute("SELECT COUNT(*) AS count FROM poem_iterations")
        self.assertEqual(self.database.cursor.fetchone()["count"], 0)

    def test_foreign_keys_are_switched_on(self):
        # The cascade above is only enforced because of this pragma, and it is
        # set per connection, so it is worth asserting rather than assuming.
        self.database.cursor.execute("PRAGMA foreign_keys")
        self.assertEqual(self.database.cursor.fetchone()[0], 1)

    def test_deleting_one_poem_leaves_another_alone(self):
        other_id = self.database.store_or_update_poem_entry(
            raw_text="Es el mismo sol de ayer", title="Sun", **LANGUAGE_PAIR
        )
        self.database.record_poem_iteration(self.poem_id, "words", "rose")
        self.database.record_poem_iteration(other_id, "words", "sun")

        self.database.delete_poem_entry(self.poem_id)

        kept = self.database.retrieve_poem_iterations(other_id)
        self.assertEqual([row["content"] for row in kept], ["sun"])

    def test_deleting_something_that_is_not_there(self):
        self.assertFalse(self.database.delete_poem_entry(9999))


if __name__ == "__main__":
    unittest.main()
