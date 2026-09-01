"""A finished poem must not hold the wall forever.

The installation is unattended and the motion sensor only ever hits
/trigger. Before this, a poem that reached COMPLETE stayed up no matter how
many people walked past, because the rotation was only consulted at startup
and on the Next button. Now the trigger that lands on a finished poem spends
itself changing the poem, and the triggers after it translate the new one.

These tests drive the real trigger task, lock and all, against a temporary
database. Nothing here may reach the network: the translator is replaced
with a fake, and the poem-change path is given one that raises if it is
called at all, because loading a poem has to stay free.
"""

import asyncio
import shutil
import tempfile
import time
import unittest
from pathlib import Path

import config

# Point the whole app at a scratch database before importing the server,
# which opens its database and picks an opening poem at import time.
_TEMP_DIR = tempfile.mkdtemp(prefix="poem-change-tests-")
config.DATABASE_FILE_PATH = Path(_TEMP_DIR) / "rotation.db"
config.OPENAI_API_KEY = config.OPENAI_API_KEY or "not-a-real-key"

import server  # noqa: E402  (must follow the config patch above)
from poem_rotation import PoemDeck  # noqa: E402

# If the patch above ever stops working, every test in here would run
# against the installation's real library. Refuse to run at all instead.
if Path(server.engine.database_manager.database_path).parent != Path(_TEMP_DIR):
    raise RuntimeError(
        "tests are pointed at the real database; refusing to run"
    )

COMPLETE = server.TransformationPhase.COMPLETE
WORDS = server.TransformationPhase.WORDS


def tearDownModule():
    server.engine.database_manager.close_database_connection()
    shutil.rmtree(_TEMP_DIR, ignore_errors=True)


class Silent:
    """A translator that fails the test if anything asks it for a reading."""

    # The debug panel reads these off the translator on every broadcast, so
    # they have to answer normally or the refusal below fires on the wrong
    # thing. __getattr__ only runs for names not found here.
    last_exchange = {}

    def clear_last_exchange(self):
        pass

    def __getattr__(self, name):
        def refuse(*args, **kwargs):
            raise AssertionError(
                f"the model was called ({name}) on a path that must be free"
            )
        return refuse


class OneWordAtATime:
    """A translator that answers instantly and never offers a synonym."""

    def __init__(self):
        self.calls = 0

    def request_word_translation_with_synonyms(self, word, *args, **kwargs):
        self.calls += 1
        return {
            "primary_translation": f"<{word}>",
            "synonyms": [],
            "tokens_used": 0,
        }

    def validate_word_translation_response(self, response):
        return True

    def clear_last_exchange(self):
        pass

    last_exchange = {}


class FinishesWhileTheNextTriggerWaits:
    """Translates a word slowly, and the poem is finished by the time it ends.

    The slow part matters. The translation runs off the event loop, so a
    trigger arriving during it gets to start its own work and read the phase
    while the poem on screen is still unfinished. That is the moment a
    phase read taken before the lock would go stale.
    """

    def __init__(self, hold=0.05):
        self.hold = hold
        self.calls = 0

    def request_word_translation_with_synonyms(self, word, *args, **kwargs):
        self.calls += 1
        time.sleep(self.hold)
        server.engine.current_phase = COMPLETE
        return {
            "primary_translation": f"<{word}>",
            "synonyms": [],
            "tokens_used": 0,
        }

    def validate_word_translation_response(self, response):
        return True

    def clear_last_exchange(self):
        pass

    last_exchange = {}


async def drain(coroutine):
    """Run a route and then every background task it set going."""
    await coroutine
    while True:
        pending = [
            task for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
        ]
        if not pending:
            return
        await asyncio.gather(*pending)


def fire(count=1):
    """Send count triggers the way the sensor does, and let them finish."""
    async def run():
        for _ in range(count):
            await drain(server.trigger())
    asyncio.run(run())


def fire_together(count=2):
    """Send triggers that all arrive before any of them has been handled."""
    async def run():
        for _ in range(count):
            await server.trigger()
        await drain(asyncio.sleep(0))
    asyncio.run(run())


class PoemChangeTestCase(unittest.TestCase):
    """A small library in a scratch database, with a finished poem up."""

    POEMS = [
        ("First", "uno dos tres\ncuatro cinco"),
        ("Second", "seis siete ocho\nnueve diez"),
        ("Third", "once doce trece\ncatorce quince"),
    ]

    def setUp(self):
        self.database = server.engine.database_manager
        # One library for every test, rebuilt each time so a test that
        # switches poems off cannot leak into the next.
        for row in self.database.retrieve_all_poem_entries():
            self.database.delete_poem_entry(row["id"])

        self.ids = {}
        for title, text in self.POEMS:
            self.ids[title] = self.database.store_or_update_poem_entry(
                raw_text=text,
                title=title,
                source_language="Spanish",
                source_language_code="es",
                target_language="English",
                target_language_code="en",
            )

        server.poem_deck = PoemDeck()
        server.engine.ai_translator = Silent()
        self.original_interval = server.SYNONYM_CYCLE_INTERVAL
        server.SYNONYM_CYCLE_INTERVAL = 0

        # Each test runs its own event loop, and an asyncio.Lock binds to
        # the loop of the first trigger that has to wait on it. Carrying one
        # lock across tests would raise inside a fired-and-forgotten task,
        # where the failure is swallowed and looks like the feature is
        # simply not working.
        server._cycle_lock = asyncio.Lock()

    def tearDown(self):
        server.SYNONYM_CYCLE_INTERVAL = self.original_interval

    def put_up(self, title):
        """Make one poem live, as the deck or a hand pick would."""
        entry = self.database.retrieve_poem_entry_by_id(self.ids[title])
        server._make_poem_live(entry, broadcast=False)

    def finish_the_poem(self):
        """Drop the engine where a poem has run its whole journey."""
        server.engine.current_phase = COMPLETE

    def assert_showing_untouched_source(self):
        """The poem on screen is its own original text, nothing translated.

        Compared case-insensitively: the renderer capitalises the opening
        word, which is presentation rather than translation.
        """
        live = self.database.retrieve_poem_entry_by_id(server.current_poem_id)
        self.assertEqual(
            server.engine.get_current_transformation_state().casefold().split(),
            live["raw_text"].casefold().split(),
            "the new poem should be up in its own language, untranslated"
        )

    def live_title(self):
        for title, poem_id in self.ids.items():
            if poem_id == server.current_poem_id:
                return title
        return None


class AFinishedPoemMakesWay(PoemChangeTestCase):

    def test_a_trigger_on_a_finished_poem_changes_the_poem(self):
        self.put_up("First")
        self.finish_the_poem()

        fire()

        self.assertNotEqual(server.current_poem_id, self.ids["First"])
        self.assertIn(self.live_title(), ("Second", "Third"))

    def test_the_new_poem_starts_at_stage_one_untranslated(self):
        self.put_up("First")
        self.finish_the_poem()

        fire()

        self.assertEqual(server.engine.get_current_phase(), WORDS)
        self.assert_showing_untouched_source()
        self.assertEqual(server.engine.trigger_count, 0)

    def test_the_change_asks_nothing_of_the_model(self):
        # server.engine.ai_translator is Silent(), which raises on any call.
        self.put_up("First")
        self.finish_the_poem()

        fire()

        self.assertEqual(server.engine.get_current_phase(), WORDS)

    def test_the_poem_that_just_finished_is_not_dealt_again(self):
        for _ in range(12):
            self.put_up("First")
            self.finish_the_poem()
            fire()
            self.assertNotEqual(
                server.current_poem_id,
                self.ids["First"],
                "the finished poem came straight back up"
            )
            server.poem_deck = PoemDeck()

    def test_the_wall_keeps_changing_over_a_long_run(self):
        # The bug this closes: one poem for the life of the installation.
        self.put_up("First")
        seen = set()
        for _ in range(9):
            self.finish_the_poem()
            fire()
            seen.add(server.current_poem_id)
        self.assertEqual(seen, set(self.ids.values()))


class OneTriggerOneAction(PoemChangeTestCase):

    def test_the_changing_trigger_does_not_also_translate(self):
        self.put_up("First")
        self.finish_the_poem()

        fire()

        self.assert_showing_untouched_source()

    def test_the_following_trigger_translates_the_new_poem(self):
        self.put_up("First")
        self.finish_the_poem()
        fire()

        translator = OneWordAtATime()
        server.engine.ai_translator = translator
        changed_to = server.current_poem_id

        fire()

        self.assertEqual(translator.calls, 1, "one trigger, one word")
        self.assertEqual(
            server.current_poem_id, changed_to,
            "translating must not change the poem"
        )
        self.assertIn("<", server.engine.get_current_transformation_state())

    def test_a_trigger_mid_journey_translates_and_does_not_change_poem(self):
        self.put_up("Second")
        translator = OneWordAtATime()
        server.engine.ai_translator = translator

        fire()

        self.assertEqual(server.current_poem_id, self.ids["Second"])
        self.assertEqual(server.engine.get_current_phase(), WORDS)
        self.assertEqual(translator.calls, 1)


class TriggersAtTheBoundary(PoemChangeTestCase):
    """Two people walking past at once must not cost a poem."""

    def count_changes(self):
        """Wrap the poem change so a test can count how often it happens."""
        real = server._make_poem_live
        changes = []

        def counted(entry, broadcast=True):
            changes.append(entry["id"])
            return real(entry, broadcast=broadcast)

        server._make_poem_live = counted
        self.addCleanup(setattr, server, "_make_poem_live", real)
        return changes

    def test_two_triggers_together_advance_by_one_poem_not_two(self):
        self.put_up("First")
        self.finish_the_poem()
        changes = self.count_changes()
        server.engine.ai_translator = OneWordAtATime()

        fire_together(2)

        self.assertEqual(
            len(changes), 1,
            f"expected a single poem change, got {changes}"
        )
        self.assertNotEqual(server.current_poem_id, self.ids["First"])

    def test_a_crowd_of_triggers_still_only_changes_the_poem_once(self):
        self.put_up("First")
        self.finish_the_poem()
        changes = self.count_changes()
        server.engine.ai_translator = OneWordAtATime()

        fire_together(5)

        self.assertEqual(len(changes), 1, f"poems were skipped: {changes}")

    def test_a_trigger_waiting_on_the_lock_sees_the_poem_finish(self):
        """The phase must be read under the lock, not before it.

        A trigger that arrives mid-translation and queues behind it has to
        act on the poem's state when its turn comes, not on the state it
        saw on the way in. If it kept the earlier reading it would try to
        translate a poem that had finished while it waited, and the wall
        would stay on the finished poem -- exactly the fault being fixed.
        """
        self.put_up("First")
        translator = FinishesWhileTheNextTriggerWaits()
        server.engine.ai_translator = translator

        async def run():
            await server.trigger()
            # Let the first trigger reach its translation, which runs off
            # the loop, so the second arrives while the poem is unfinished.
            await asyncio.sleep(0)
            await server.trigger()
            await drain(asyncio.sleep(0))

        asyncio.run(run())

        self.assertEqual(translator.calls, 1)
        self.assertNotEqual(
            server.current_poem_id, self.ids["First"],
            "the trigger that waited kept a stale phase and left the "
            "finished poem up"
        )

    def test_the_second_trigger_translates_rather_than_changing_again(self):
        self.put_up("First")
        self.finish_the_poem()
        translator = OneWordAtATime()
        server.engine.ai_translator = translator

        fire_together(2)

        self.assertEqual(
            translator.calls, 1,
            "the trigger behind the change should have translated one word"
        )


class NothingToChangeTo(PoemChangeTestCase):

    def switch_everything_off(self):
        for poem_id in self.ids.values():
            self.database.set_poem_active(poem_id, False)

    def test_an_empty_rotation_holds_the_finished_poem(self):
        self.put_up("First")
        self.switch_everything_off()
        self.finish_the_poem()

        fire()

        self.assertEqual(server.current_poem_id, self.ids["First"])
        self.assertEqual(
            server.engine.get_current_phase(), COMPLETE,
            "the finished poem should still be up, not restarted"
        )

    def test_an_empty_rotation_does_not_raise_on_repeated_triggers(self):
        self.put_up("First")
        self.switch_everything_off()
        self.finish_the_poem()

        fire(4)

        self.assertEqual(server.current_poem_id, self.ids["First"])

    def test_the_wall_moves_again_once_a_poem_comes_back(self):
        self.put_up("First")
        self.switch_everything_off()
        self.finish_the_poem()
        fire()

        self.database.set_poem_active(self.ids["Third"], True)
        fire()

        self.assertEqual(server.current_poem_id, self.ids["Third"])

    def test_a_single_poem_in_the_rotation_restarts_itself(self):
        # Unavoidable and correct: there is nothing else to move to, and the
        # wall should carry on rather than sit on a finished poem.
        for title in ("First", "Second"):
            self.database.set_poem_active(self.ids[title], False)
        self.put_up("Third")
        self.finish_the_poem()

        fire()

        self.assertEqual(server.current_poem_id, self.ids["Third"])
        self.assertEqual(server.engine.get_current_phase(), WORDS)


if __name__ == "__main__":
    unittest.main()
