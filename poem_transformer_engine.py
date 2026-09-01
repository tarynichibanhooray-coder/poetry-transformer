"""Poem Transformer Engine.

The poem is a list of translation units, not a grid of one slot per source
word. A unit holds whatever the target language needs for the source it
covers, so "Dime," can become "Tell me," without anything having to be
clipped, scattered, or repaired afterwards.

Four stages, then the poem turns around:

  1) WORDS    one source word per trigger, translated in strict isolation
  2) PHRASES  a two or three word scrap per trigger, its line visible as context
  3) LINES    one revision per trigger, each leaving the line closer to the
              rendering it is travelling toward
  4) origin and target swap and the same three stages run back the other way,
     each word remembering what it was translated from on the way out

Stage 3 is the only stage that sees where it is going, and it is only ever
allowed one change at a time.
"""

from typing import List, Dict, Tuple, Optional
from enum import Enum
import random

import config
from database_manager import DatabaseManager
from openai_translator import OpenAITranslator
from translation_units import (
    UnitPoem,
    distribute_words,
    drops_content_words,
    normalize_reading,
    reading_distance,
    render_units,
    split_words_and_separators,
)
from word_senses import source_stem


class TransformationPhase(Enum):
    """The live poem walks these stages, then swaps languages and repeats."""

    WORDS = 1
    PHRASES = 2
    LINES = 3
    COMPLETE = 4


class PoemTransformerEngine:
    """Core engine for transforming poems through the translation stages."""

    def __init__(
        self,
        source_language: str = config.SOURCE_LANGUAGE,
        target_language: str = config.TARGET_LANGUAGE,
        source_language_code: str = config.SOURCE_LANGUAGE_CODE,
        target_language_code: str = config.TARGET_LANGUAGE_CODE,
        random_seed: int = None
    ):
        self.source_language = source_language
        self.target_language = target_language
        self.source_language_code = source_language_code
        self.target_language_code = target_language_code

        self.database_manager = DatabaseManager()
        self.ai_translator = OpenAITranslator()

        self.random_generator = random.Random(
            config.TRANSFORMATION_RANDOM_SEED if random_seed is None else random_seed
        )

        self.poem = UnitPoem([])
        # The library row the readings are filed under. None when the engine
        # was handed a poem directly, which is normal in a test.
        self.poem_id = None
        self.original_poem = None
        self.home_poem = None
        self.final_translation = None
        self.destination_lines = []
        self.current_phase = TransformationPhase.WORDS
        self.trigger_count = 0
        self.on_return_journey = False

        self.phase_1_word_queue = []
        self.phrase_span_queue = []
        self.variation_queue = []
        self.span_states = {}
        self.word_synonym_cycle_index = {}
        self.word_origins = {}

        self.last_changed_span = None
        self.last_action_phase = None
        self.last_block_drafts = []
        self.last_block_improvement = None
        self.last_block_unchanged = False
        self.last_block_defect = None
        self.last_block_mode = None
        self.last_debug_note = None

        if config.DEBUG_MODE:
            print("✓ Poem Transformer Engine initialized")
            print(f"  Source: {source_language} → Target: {target_language}")

    # ------------------------------------------------------------------ setup

    def load_poem_from_file(self, file_path: str) -> str:
        with open(file_path, 'r', encoding='utf-8') as file:
            poem_text = file.read().strip()
        self.initialize_poem_with_text(poem_text)
        return poem_text

    def initialize_poem_with_text(
        self,
        poem_text: str,
        source_language: str = None,
        source_language_code: str = None,
        target_language: str = None,
        target_language_code: str = None,
        final_translation: str = None
    ) -> None:
        """Make a poem live and build the translation stage queues for it."""
        if source_language:
            self.source_language = source_language
        if source_language_code:
            self.source_language_code = source_language_code
        if target_language:
            self.target_language = target_language
        if target_language_code:
            self.target_language_code = target_language_code

        poem_text = (poem_text or '').strip()
        self.final_translation = (final_translation or '').strip() or None
        self.original_poem = poem_text
        self.home_poem = poem_text
        self.on_return_journey = False
        # A new poem knows nothing about the last one's passage, and has no
        # library row until whoever made it live says which one.
        self.word_origins = {}
        self.poem_id = None

        self.stage_text(poem_text, self.final_translation)

        if config.DEBUG_MODE:
            print(f"✓ Poem initialized with {len(self.poem.units)} units")
            print(f"  {self.source_language} → {self.target_language}")
            print(
                f"  {len(self.poem.line_spans())} lines, "
                f"{len(self.phase_1_word_queue)} words to visit"
            )

    def stage_text(self, poem_text: str, destination: Optional[str]) -> None:
        """Rebuild every stage queue around a new starting text."""
        self.poem = UnitPoem.from_text(poem_text)
        self.destination_lines = [
            line.strip() for line in (destination or '').split('\n') if line.strip()
        ]
        self.current_phase = TransformationPhase.WORDS
        self.trigger_count = 0
        self.phase_1_word_queue = self.build_phase_1_word_queue()
        self.phrase_span_queue = []
        self.variation_queue = []
        self.span_states = {}
        self.word_synonym_cycle_index = {}
        self.last_changed_span = None
        self.last_action_phase = None
        self.last_block_drafts = []
        self.last_block_improvement = None
        self.last_block_unchanged = False
        self.last_block_defect = None
        self.last_block_mode = None
        self.last_debug_note = None

    def build_phase_1_word_queue(self) -> List[int]:
        """Every unit index, in a shuffled but replayable order."""
        indices = list(range(len(self.poem.units)))
        self.random_generator.shuffle(indices)
        return indices

    def build_phrase_span_queue(self) -> List[Tuple[int, int]]:
        """Cut each line into two and three unit scraps, left to right."""
        sizes = list(config.BLOCK_GROWTH_WORD_SIZES) or [2, 3]
        spans = []
        for start, end in self.poem.line_spans():
            cursor = start
            while cursor < end:
                size = self.random_generator.choice(sizes)
                stop = min(cursor + size, end)
                # A single unit left over joins the scrap before it rather
                # than going back through the stage alone.
                if end - stop == 1:
                    stop = end
                spans.append((cursor, stop))
                cursor = stop
        return spans

    # ------------------------------------------------------- server surface

    @property
    def original_poem_words(self) -> List[str]:
        return self.poem.sources()

    @property
    def current_words(self) -> List[str]:
        return self.poem.texts()

    @property
    def word_separators(self) -> List[str]:
        return self.poem.separators()

    @property
    def line_spans(self) -> List[Tuple[int, int]]:
        return self.poem.line_spans()

    def rebuild_transformation_state(self, words: List[str] = None) -> str:
        if words is None:
            return self.poem.render()
        return render_units(list(words), self.poem.separators())

    def get_current_transformation_state(self) -> str:
        return self.poem.render()

    def get_current_phase(self) -> TransformationPhase:
        return self.current_phase

    def get_original_line_for_word_index(self, word_index: int) -> str:
        line_index = self.poem.line_index_for(word_index)
        return self.poem.source_line(line_index)

    def replace_word_in_transformation_state(
        self,
        word_index: int,
        replacement_word: str
    ) -> None:
        if 0 <= word_index < len(self.poem.units):
            self.poem.units[word_index].text = (replacement_word or '').strip()
            self.poem.units[word_index].visited = True
            self.last_changed_span = (word_index, word_index + 1)

    def preview_word_slots(self, word_index: int, replacement_word: str) -> List[str]:
        words = self.poem.texts()
        if 0 <= word_index < len(words):
            words[word_index] = (replacement_word or '').strip()
        return words

    def preview_word_replacement(self, word_index: int, replacement_word: str) -> str:
        return render_units(
            self.preview_word_slots(word_index, replacement_word),
            self.poem.separators(),
        )

    def claim_next_phase_1_word_index(self) -> Optional[int]:
        """Take the next word for stage 1, if stage 1 is still running."""
        if self.current_phase != TransformationPhase.WORDS:
            return None
        while self.phase_1_word_queue:
            index = self.phase_1_word_queue.pop(0)
            if 0 <= index < len(self.poem.units):
                return index
        return None

    def note_phase_1_word_completed(self) -> None:
        """Count a settled word and move on to scraps once none are left."""
        self.trigger_count += 1
        self.last_action_phase = TransformationPhase.WORDS
        if not self.phase_1_word_queue:
            self.transition_to_phrases()

    # ------------------------------------------------------------- triggers

    def process_next_sensor_trigger(self) -> str:
        """Advance the poem by one step and return the new reading."""
        if self.current_phase == TransformationPhase.COMPLETE:
            return self.get_current_transformation_state()

        self.trigger_count += 1
        self.last_changed_span = None
        self.last_action_phase = self.current_phase
        self.last_block_drafts = []
        self.last_block_improvement = None
        self.last_block_unchanged = False
        self.last_block_defect = None
        self.last_block_mode = None

        if self.current_phase == TransformationPhase.WORDS:
            self.advance_words()
        elif self.current_phase == TransformationPhase.PHRASES:
            self.advance_phrases()
        elif self.current_phase == TransformationPhase.LINES:
            self.advance_lines()

        return self.get_current_transformation_state()

    # -------------------------------------------------------------- stage 1

    def advance_words(self) -> None:
        """One source word, translated with nothing around it."""
        index = self.claim_next_phase_1_word_index()
        if index is None:
            self.transition_to_phrases()
            return

        source_word = self.poem.units[index].source
        self.last_block_mode = 'word'
        try:
            translation = self.get_or_fetch_word_translation_with_synonyms(
                source_word,
                self.get_original_line_for_word_index(index),
            )
        except Exception as error:
            print(f"✗ Word stage failed on {source_word!r}: {error}")
            self.last_debug_note = f"word {source_word!r} failed: {error}"
            if not self.phase_1_word_queue:
                self.transition_to_phrases()
            return

        chosen = (translation.get('target_word') or '').strip() or source_word
        self.replace_word_in_transformation_state(index, chosen)
        self.last_block_improvement = f"{source_word} → {chosen}"

        if not self.phase_1_word_queue:
            self.transition_to_phrases()

    def record_iteration(
        self,
        stage: str,
        content: str,
        source_text: str = '',
        note: str = '',
        alternatives: List[str] = None,
    ) -> None:
        """File one reading under the poem it belongs to.

        Kept out of the way of the stages themselves: a failure to write the
        record must never take down the pass that produced it, because the
        poem on the wall matters more than the notebook about it.
        """
        if not self.poem_id:
            return
        try:
            self.database_manager.record_poem_iteration(
                self.poem_id,
                stage,
                content,
                source_text=source_text,
                note=note,
                alternatives=alternatives,
                journey='home' if self.on_return_journey else 'out',
            )
        except Exception as error:
            print(f"✗ Could not record a {stage} reading: {error}")

    def remember_word_origin(self, source_word: str, reading: str) -> None:
        """Record that `reading` reached the page by way of `source_word`.

        Only a one-word reading is worth recording. "Dime" arriving as "Tell
        me" gives no honest per-word origin, and inventing one would file
        Dime under both halves and bring the poem home saying it twice.
        """
        reading = (reading or '').strip()
        if not reading or len(reading.split()) != 1:
            return
        key = source_stem(reading)
        if key:
            self.word_origins[key] = source_word

    def origin_for_word(self, word: str) -> Optional[str]:
        """The word this one was translated from, on the way back only.

        Going out, a lone word is meant to be ambiguous and no origin is
        offered. Coming back there is nothing to be ambiguous about: the
        poem has already been through here.
        """
        if not self.on_return_journey:
            return None
        return self.word_origins.get(source_stem(word))

    def get_or_fetch_word_translation_with_synonyms(
        self,
        word: str,
        context_line: str = None
    ) -> Dict:
        """Translate one word. The context line is a cache key, never a prompt.

        Stage 1 is strictly isolated: the model is shown the bare word and
        nothing else, because a word alone is genuinely ambiguous and that
        ambiguity is what the stage is for. The single exception is a word
        on the way home, which is sent the word it came from.
        """
        self.last_action_phase = self.current_phase
        origin_word = self.origin_for_word(word)
        cached = None
        if config.CACHE_WORD_TRANSLATIONS:
            cached = self.database_manager.retrieve_cached_word_translation(
                word,
                self.source_language_code,
                self.target_language_code,
                context_line or '',
                self.final_translation or ''
            )

        if cached:
            if config.VERBOSE_LOGGING:
                print(f"  ✓ Found cached translation for: {word}")
            self.last_debug_note = f"cached word {word!r}; no new model call"
            self.remember_word_origin(word, cached.get('target_word'))
            return cached

        if config.VERBOSE_LOGGING:
            print(f"  → Requesting translation from AI for: {word}")

        ai_response = self.ai_translator.request_word_translation_with_synonyms(
            word,
            self.source_language,
            self.target_language,
            origin_word=origin_word,
        )

        if not self.ai_translator.validate_word_translation_response(ai_response):
            raise ValueError(f"Invalid AI response for word: {word}")

        if config.CACHE_WORD_TRANSLATIONS:
            self.database_manager.store_new_word_translation_with_synonyms(
                word,
                ai_response['primary_translation'],
                ai_response['synonyms'],
                self.source_language_code,
                self.target_language_code,
                context_line or '',
                self.final_translation or ''
            )

        self.database_manager.record_translation_history_entry(
            'word',
            word,
            ai_response['primary_translation'],
            self.source_language_code,
            self.target_language_code,
            ai_response.get('tokens_used')
        )

        if origin_word:
            self.last_debug_note = f"word {word!r} came from {origin_word!r}"
        self.remember_word_origin(word, ai_response['primary_translation'])
        self.record_iteration(
            'words',
            ai_response['primary_translation'],
            source_text=word,
            note=f"came from {origin_word}" if origin_word else '',
            alternatives=ai_response['synonyms'],
        )

        return {
            'source_word': word,
            'target_word': ai_response['primary_translation'],
            'primary_translation': ai_response['primary_translation'],
            'synonyms': ai_response['synonyms'],
        }

    # -------------------------------------------------------------- stage 2

    def advance_phrases(self) -> None:
        """One scrap, translated relationally with its own line as context."""
        if not self.phrase_span_queue:
            self.transition_to_lines()
            return

        start, end = self.phrase_span_queue.pop(0)
        self.last_changed_span = (start, end)
        self.last_block_mode = 'phrase'

        line_index = self.poem.line_index_for(start)
        scrap_source = self.poem.source_for_span(start, end)
        current_reading = self.poem.text_for_span(start, end)

        try:
            response = self.ai_translator.request_phrase_translation(
                scrap_source,
                source_line=self.poem.source_line(line_index),
                current_reading=current_reading,
                previous_state=self.span_states.get((start, end)),
            )
        except Exception as error:
            print(f"✗ Phrase stage failed on {scrap_source!r}: {error}")
            self.last_debug_note = f"phrase {scrap_source!r} failed: {error}"
            if not self.phrase_span_queue:
                self.transition_to_lines()
            return

        segments = response.get('segments') or []
        rewrite = ' '.join(segment for segment in segments if segment)
        if not segments:
            self.last_block_unchanged = True
            self.last_block_improvement = 'nothing returned'
        elif drops_content_words(current_reading, rewrite):
            self.last_block_unchanged = True
            self.last_block_defect = 'dropped_image'
            self.last_block_improvement = 'refused: the scrap lost a word it names'
            self.last_debug_note = (
                f"refused {current_reading!r} → {rewrite!r}: content word dropped"
            )
        else:
            self.poem.place_span(start, end, segments)
            self.remember_span_state(start, end, response.get('translation_state'))
            self.last_block_improvement = response.get('improvement')

        self.record_block_history(scrap_source, self.poem.text_for_span(start, end))
        self.record_iteration(
            'phrases',
            self.poem.text_for_span(start, end),
            source_text=scrap_source,
            note=self.last_block_improvement or '',
        )

        if not self.phrase_span_queue:
            self.transition_to_lines()

    # -------------------------------------------------------------- stage 3

    def advance_lines(self) -> None:
        """Show the next attempt at the whole poem, worst ranked first.

        Stage 3 asks once for a field of complete readings and then spends
        the following triggers walking up through them. The chosen rendering
        is simply the last thing shown, so arrival needs no convincing.
        """
        if not self.variation_queue:
            self.load_variations()
        if not self.variation_queue:
            self.arrive()
            return

        reading, label = self.variation_queue.pop(0)
        self.place_poem_reading(reading)
        self.last_changed_span = (0, len(self.poem.units))
        self.last_block_mode = 'variation'
        self.last_block_improvement = label
        self.last_debug_note = f"{label}; {len(self.variation_queue)} still to come"

        if not self.variation_queue:
            self.arrive()

    def load_variations(self) -> None:
        """Ask once for several readings, and queue them worst to best."""
        source_poem = '\n'.join(
            self.poem.source_line(index)
            for index in range(len(self.poem.line_spans()))
        )
        try:
            variations = self.ai_translator.request_poem_variations(
                source_poem,
                self.get_current_transformation_state(),
                target_language=self.target_language,
                lines_expected=len(self.poem.line_spans()),
            )
        except Exception as error:
            print(f"✗ Variation stage failed: {error}")
            self.last_debug_note = f"variations failed: {error}"
            variations = []

        total = len(variations)
        queue = []
        for position, variation in enumerate(variations, start=1):
            captures = variation.get('captures') or ''
            label = f"attempt {position} of {total}"
            queue.append((variation['translation'], f"{label}: {captures}".strip(': ')))

        destination = '\n'.join(self.destination_lines).strip()
        if destination and not any(
            reading_distance(reading, destination) == 0 for reading, _ in queue
        ):
            queue.append((destination, 'the chosen rendering'))

        self.variation_queue = queue
        self.last_block_drafts = [reading for reading, _ in queue]

        # Recorded here rather than as each one is shown, because the whole
        # ranked field arrived in a single answer and the ones the poem is
        # about to walk past are as much a part of the record as the last.
        for reading, label in queue:
            self.record_iteration(
                'lines', reading, source_text=source_poem, note=label
            )

    def place_poem_reading(self, reading: str) -> None:
        """Write a whole reading back across the poem's lines.

        An attempt is asked to keep the line count and sometimes does not.
        When it does not, the reading is spread across every unit instead,
        because placing the lines it did send would leave the rest of the
        poem showing the previous attempt underneath it.
        """
        spans = self.poem.line_spans()
        lines = [line for line in (reading or '').split('\n') if line.strip()]
        if not spans or not lines:
            return

        if len(lines) == len(spans):
            for line_index, line in enumerate(lines):
                self.place_line_reading(line_index, line)
            return

        words, _ = split_words_and_separators(' '.join(lines))
        spread = distribute_words(words, len(self.poem.units))
        for index, unit in enumerate(self.poem.units):
            unit.text = spread[index]

    def place_line_reading(self, line_index: int, reading: str) -> None:
        """Spread a line across its units, so the page keeps its spans."""
        spans = self.poem.line_spans()
        if line_index >= len(spans):
            return
        start, end = spans[line_index]
        words, _ = split_words_and_separators(reading)
        spread = distribute_words(words, end - start)
        for offset in range(start, end):
            self.poem.units[offset].text = spread[offset - start]

    def destination_line_for_index(self, line_index: int) -> str:
        if 0 <= line_index < len(self.destination_lines):
            return self.destination_lines[line_index]
        return ''

    # ------------------------------------------------------------- stage 4

    def arrive(self) -> None:
        """The poem reached its rendering. Turn it around, or finish."""
        if self.on_return_journey:
            self.mark_transformation_complete()
            return
        self.begin_return_to_source()

    def begin_return_to_source(self) -> None:
        """Swap origin and target and walk the same three stages back."""
        arrived_text = self.get_current_transformation_state()

        self.source_language, self.target_language = (
            self.target_language, self.source_language
        )
        self.source_language_code, self.target_language_code = (
            self.target_language_code, self.source_language_code
        )

        # word_origins deliberately survives this. It is the only thing the
        # poem carries across the turn, and without it a word that went out
        # as rosa comes back as the past tense of rise.
        self.stage_text(arrived_text, self.home_poem)
        self.original_poem = arrived_text
        self.final_translation = self.home_poem
        self.on_return_journey = True

        if config.DEBUG_MODE:
            print(
                f"↩ Turning around: {self.source_language} → {self.target_language}"
            )

    def mark_transformation_complete(self) -> None:
        self.current_phase = TransformationPhase.COMPLETE
        if config.DEBUG_MODE:
            print("✓ The poem came home.")

    def transition_to_phrases(self) -> None:
        if self.current_phase == TransformationPhase.PHRASES:
            return
        self.current_phase = TransformationPhase.PHRASES
        self.phrase_span_queue = self.build_phrase_span_queue()
        if config.DEBUG_MODE:
            print(f"→ Stage 2: phrases ({len(self.phrase_span_queue)} scraps)")

    def transition_to_lines(self) -> None:
        if self.current_phase == TransformationPhase.LINES:
            return
        self.current_phase = TransformationPhase.LINES
        self.variation_queue = []
        if config.DEBUG_MODE:
            print("→ Stage 3: variations")

    # -------------------------------------------------------------- records

    def remember_span_state(self, start: int, end: int, state: Dict = None) -> None:
        """Keep the structured state a span came back with, for its next pass."""
        state = state or {}
        self.span_states[(start, end)] = {
            "translation": state.get("translation") or self.poem.text_for_span(start, end),
            "units": list(state.get("units") or []),
            "revisions": list(state.get("revisions") or []),
            "ambiguities": list(state.get("ambiguities") or []),
        }

    def record_block_history(self, source_text: str, result_text: str) -> None:
        try:
            self.database_manager.record_translation_history_entry(
                'phrase',
                source_text,
                result_text,
                self.source_language_code,
                self.target_language_code,
                None,
            )
        except Exception:
            pass

    # --------------------------------------------------------------- status

    def poem_has_arrived(self) -> bool:
        destination = '\n'.join(self.destination_lines).strip()
        return bool(destination) and reading_distance(
            self.get_current_transformation_state(), destination
        ) == 0

    def poem_has_returned(self) -> bool:
        return (
            self.on_return_journey
            and normalize_reading(self.get_current_transformation_state())
            == normalize_reading(self.home_poem or '')
        )

    def get_transformation_progress_percentage(self) -> float:
        """How far the whole round trip has come, as a rough fraction."""
        if self.current_phase == TransformationPhase.COMPLETE:
            return 100.0

        total_units = max(1, len(self.poem.units))
        words_done = (total_units - len(self.phase_1_word_queue)) / total_units

        if self.current_phase == TransformationPhase.WORDS:
            leg = words_done / 3.0
        elif self.current_phase == TransformationPhase.PHRASES:
            spans = max(1, len(self.build_phrase_span_queue()))
            leg = (1.0 + (spans - len(self.phrase_span_queue)) / spans) / 3.0
        else:
            leg = (2.0 + self.variation_stage_progress()) / 3.0

        half = 50.0 * leg
        return round(half + 50.0 if self.on_return_journey else half, 1)

    def variation_stage_progress(self) -> float:
        """How far up the ranked attempts the poem has climbed."""
        shown = len(self.last_block_drafts or [])
        if not shown:
            return 0.0
        return (shown - len(self.variation_queue)) / shown

    def count_remaining_operations(self) -> int:
        if self.current_phase == TransformationPhase.WORDS:
            return len(self.phase_1_word_queue)
        if self.current_phase == TransformationPhase.PHRASES:
            return len(self.phrase_span_queue)
        return len(self.variation_queue)

    def begin_debug_trigger(self) -> None:
        """Clear stale prompt text before a click so the panel matches this trigger."""
        self.last_debug_note = None
        clearer = getattr(self.ai_translator, 'clear_last_exchange', None)
        if callable(clearer):
            clearer()

    def get_last_debug_exchange(self) -> Dict:
        """Stage, prompt, and model reply for the live debug panel."""
        phase = (self.last_action_phase or self.current_phase).name
        labels = {
            'WORDS': '1 — words',
            'PHRASES': '2 — phrases',
            'LINES': '3 — lines',
            'COMPLETE': 'Complete',
        }
        stage = labels.get(phase, phase)
        if self.on_return_journey and phase in labels:
            stage = f"return {stage}"

        exchange = getattr(self.ai_translator, 'last_exchange', None) or {}
        kind = exchange.get('kind') or self.last_block_mode
        if kind:
            stage = f"{stage} ({kind})"

        parts = []
        if exchange.get('system'):
            parts.append(f"SYSTEM\n{exchange['system'].strip()}")
        if exchange.get('developer'):
            parts.append(f"STAGE\n{exchange['developer'].strip()}")
        if exchange.get('user'):
            label = "PAYLOAD" if exchange.get('developer') else "USER"
            parts.append(f"{label}\n{exchange['user'].strip()}")
        request = '\n\n'.join(parts)

        response = exchange.get('response') or ''
        if exchange.get('error'):
            response = (response + '\n\nERROR: ' + str(exchange['error'])).strip()

        extras = []
        if self.last_block_defect:
            extras.append(f"defect: {self.last_block_defect}")
        if self.last_block_unchanged:
            extras.append('unchanged: true')
        if self.last_block_improvement:
            extras.append(f"improvement: {self.last_block_improvement}")
        if extras:
            stage = f"{stage} · {'; '.join(extras)}"

        return {
            "stage": stage,
            "note": self.last_debug_note or '',
            "request": request,
            "response": response,
        }

    def get_transformation_statistics(self) -> Dict:
        return {
            "trigger_count": self.trigger_count,
            "current_phase": self.current_phase.name,
            "total_words": len(self.poem.units),
            "total_lines": len(self.poem.line_spans()),
            "remaining_operations": self.count_remaining_operations(),
            "planned_operations": None,
            "progress_percentage": self.get_transformation_progress_percentage(),
            "cached_words": self.database_manager.count_cached_word_translations(),
            "cached_phrases": self.database_manager.count_cached_phrase_translations(),
            "api_requests": self.database_manager.count_total_api_requests_made(),
            "total_tokens_used": self.database_manager.calculate_total_tokens_used()
        }
