"""
Poem Transformer Engine for Poetry Transformer
Core logic for multi-phase word-to-phrase transformation
"""

from typing import List, Dict, Tuple, Optional
from enum import Enum
import random
import re

import config
from database_manager import DatabaseManager
from openai_translator import OpenAITranslator


WHITESPACE_RUN_PATTERN = re.compile(r'(\s+)')


def split_words_and_separators(text: str) -> Tuple[List[str], List[str]]:
    """
    Split text into words plus the whitespace run that follows each word

    Args:
        text: Text to split

    Returns:
        Tuple of (words, separators) where separators[i] follows words[i].
        The word list matches str.split() so indices stay consistent with
        original_poem_words.
    """
    parts = WHITESPACE_RUN_PATTERN.split(text.strip())
    return parts[0::2], parts[1::2]


class TransformationPhase(Enum):
    """Enum for transformation phases

    Phase 1 replaces every word once, in random order, cycling its real
    synonyms before it settles. After that the poem is gathered: each trigger
    picks a span and tries to leave it better, with any chosen ending as a
    direction rather than a countdown. There is no booked number of steps to
    the target; the work ends when the poem already reads as that target, or
    it simply keeps going.
    """
    PHASE_1_WORD_BY_WORD = 1
    PHASE_2_GROWING_BLOCKS = 2
    PHASE_3_ARRIVAL = 3
    COMPLETE = 4


class PoemTransformerEngine:
    """Core engine for transforming poems through multiple translation phases"""

    def __init__(
        self,
        source_language: str = config.SOURCE_LANGUAGE,
        target_language: str = config.TARGET_LANGUAGE,
        source_language_code: str = config.SOURCE_LANGUAGE_CODE,
        target_language_code: str = config.TARGET_LANGUAGE_CODE,
        random_seed: int = None
    ):
        """
        Initialize the poem transformer engine
        
        Args:
            source_language: Name of source language
            target_language: Name of target language
            source_language_code: ISO code for source language
            target_language_code: ISO code for target language
            random_seed: Seed for the transformation order, defaulting to the
                configured one. Set it to replay an identical run.
        """
        self.source_language = source_language
        self.target_language = target_language
        self.source_language_code = source_language_code
        self.target_language_code = target_language_code
        
        self.database_manager = DatabaseManager()
        self.ai_translator = OpenAITranslator()
        
        self.random_generator = random.Random(
            config.TRANSFORMATION_RANDOM_SEED if random_seed is None else random_seed
        )

        self.original_poem = None
        self.original_poem_words = []
        self.final_translation = None
        self.current_words = []
        self.word_separators = []
        self.current_transformation_state = None
        self.current_phase = TransformationPhase.PHASE_1_WORD_BY_WORD
        self.trigger_count = 0

        # Spans of word indices, as [start, end) pairs
        self.line_spans = []
        self.stanza_spans = []

        # Phase 1 still has a finite word list, because each word is visited
        # once. After that there is no playlist of remaining steps.
        self.phase_1_word_queue = []
        self.destination_lines = []
        self.gathering_steps = 0

        # What the last trigger did, for clients that highlight or label it
        self.last_changed_span = None
        self.last_action_phase = None
        self.last_block_drafts = []
        self.last_block_improvement = None

        # Caching for word translations during phase 1
        self.word_synonym_cycle_index = {}
        
        if config.DEBUG_MODE:
            print(f"✓ Poem Transformer Engine initialized")
            print(f"  Source: {source_language} → Target: {target_language}")

    def load_poem_from_file(self, file_path: str) -> str:
        """
        Load a poem from a text file
        
        Args:
            file_path: Path to poem file
            
        Returns:
            The poem text
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                poem_text = file.read().strip()
            
            self.initialize_poem_with_text(poem_text)
            return poem_text
            
        except FileNotFoundError:
            print(f"✗ Poem file not found: {file_path}")
            raise
        except Exception as error:
            print(f"✗ Error loading poem: {error}")
            raise

    def initialize_poem_with_text(
        self,
        poem_text: str,
        source_language: str = None,
        source_language_code: str = None,
        target_language: str = None,
        target_language_code: str = None,
        final_translation: str = None
    ) -> None:
        """
        Initialize the poem transformer with poem text

        Language is a property of the poem rather than the engine, so each poem
        can declare what it was written in. Omitted values keep whatever the
        engine was last using.

        Args:
            poem_text: The complete poem as a string
            source_language: Name of the poem's language, e.g. "Spanish"
            source_language_code: ISO code of the poem's language, e.g. "es"
            target_language: Name of the language to translate into
            target_language_code: ISO code of the language to translate into
            final_translation: The translation the poem should come to rest on.
                Given one, the closing pass uses it instead of writing its own.
        """
        if source_language:
            self.source_language = source_language
        if source_language_code:
            self.source_language_code = source_language_code
        if target_language:
            self.target_language = target_language
        if target_language_code:
            self.target_language_code = target_language_code

        poem_text = poem_text.strip()

        self.final_translation = (final_translation or '').strip() or None
        self.original_poem = poem_text
        self.original_poem_words = self.extract_words_from_poem_text(poem_text)

        # One slot per original word. A slot may hold a multi-word translation
        # without shifting the indices of the words after it.
        _, self.word_separators = split_words_and_separators(poem_text)
        self.current_words = list(self.original_poem_words)
        self.current_transformation_state = self.rebuild_transformation_state()
        self.trigger_count = 0
        self.current_phase = TransformationPhase.PHASE_1_WORD_BY_WORD
        self.word_synonym_cycle_index = {}
        self.last_changed_span = None
        self.last_action_phase = None
        self.last_block_drafts = []
        self.last_block_improvement = None

        self.line_spans = self.compute_line_spans()
        self.stanza_spans = self.compute_stanza_spans()
        self.phase_1_word_queue = self.build_phase_1_word_queue()
        self.destination_lines = self.build_destination_lines()
        self.gathering_steps = 0

        if config.DEBUG_MODE:
            print(f"✓ Poem initialized with {len(self.original_poem_words)} words")
            print(f"  {self.source_language} → {self.target_language}")
            print(
                f"  {len(self.line_spans)} lines, {len(self.stanza_spans)} stanzas, "
                f"{len(self.phase_1_word_queue)} words to visit"
            )

    def extract_words_from_poem_text(self, poem_text: str) -> List[str]:
        """
        Extract individual words from poem text preserving order
        
        Args:
            poem_text: The poem text
            
        Returns:
            List of words in order
        """
        # Split on whitespace but preserve word order
        words = poem_text.split()
        return words

    def compute_line_spans(self) -> List[Tuple[int, int]]:
        """
        Find the word indices belonging to each line of the poem

        Returns:
            List of [start, end) word index pairs, one per line
        """
        spans = []
        line_start = 0

        for index in range(len(self.original_poem_words)):
            separator = (
                self.word_separators[index]
                if index < len(self.word_separators)
                else ''
            )
            is_last_word = index == len(self.original_poem_words) - 1

            if '\n' in separator or is_last_word:
                spans.append((line_start, index + 1))
                line_start = index + 1

        return spans

    def compute_stanza_spans(self) -> List[Tuple[int, int]]:
        """
        Find the word indices belonging to each stanza of the poem

        A blank line, meaning a separator holding more than one newline, ends a
        stanza.

        Returns:
            List of [start, end) word index pairs, one per stanza
        """
        spans = []
        stanza_start = 0

        for index in range(len(self.original_poem_words)):
            separator = (
                self.word_separators[index]
                if index < len(self.word_separators)
                else ''
            )
            is_last_word = index == len(self.original_poem_words) - 1

            if separator.count('\n') > 1 or is_last_word:
                spans.append((stanza_start, index + 1))
                stanza_start = index + 1

        return spans

    def build_phase_1_word_queue(self) -> List[int]:
        """
        Build the random order in which Phase 1 replaces words

        Shuffling the whole list up front, rather than picking a random word per
        trigger, guarantees each word is transformed exactly once and the phase
        ends when the poem is wholly in the target language.

        Returns:
            Word indices in the order they will be transformed
        """
        word_indices = list(range(len(self.original_poem_words)))
        self.random_generator.shuffle(word_indices)
        return word_indices

    def split_run_into_blocks(
        self,
        start_index: int,
        end_index: int,
        size: int
    ) -> List[Tuple[int, int]]:
        """
        Divide a run of words into blocks of roughly the given size

        Dividing the run evenly rather than taking fixed-size bites off the
        front means no block is left as an orphaned word at the end. The edges
        are then nudged a word either way, so carving the same run at the same
        size twice groups the words differently the second time.

        Args:
            start_index: First word index of the run
            end_index: Word index just past the run
            size: Roughly how many words each block should hold

        Returns:
            Block spans as [start, end) word index pairs
        """
        length = end_index - start_index
        if length <= 0:
            return []

        # A one-word block is just the word pass again, so blocks keep a floor
        # of two words and the run is cut into fewer of them if it must be.
        smallest_block = 1 if size <= 1 else 2
        block_count = max(1, min(round(length / size), length // smallest_block))
        if block_count == 1:
            return [(start_index, end_index)]

        edges = [start_index]
        for block_number in range(1, block_count):
            even_edge = start_index + round(length * block_number / block_count)
            nudged = even_edge + self.random_generator.choice((-1, 0, 1))

            # Every block before this one is wide enough, and so must every
            # block after it be.
            earliest = edges[-1] + smallest_block
            latest = end_index - smallest_block * (block_count - block_number)
            edges.append(max(earliest, min(nudged, latest)))

        edges.append(end_index)
        return [(edges[index], edges[index + 1]) for index in range(len(edges) - 1)]

    def partition_poem_into_blocks(self, size: int) -> List[Tuple[int, int]]:
        """
        Cover the whole poem with adjacent blocks of roughly the given size

        Blocks stay inside a line wherever the line is long enough to hold one.
        A line too short for that borrows from the line below, which is the only
        case where a block crosses a break.

        Args:
            size: Roughly how many words each block should hold

        Returns:
            Block spans as [start, end) word index pairs, in reading order
        """
        total_words = len(self.original_poem_words)
        blocks = []
        carried_start = None

        for line_start, line_end in self.line_spans:
            if line_end <= line_start:
                continue

            run_start = carried_start if carried_start is not None else line_start
            carried_start = None

            if line_end - run_start < size:
                # Not enough words here to make a block, so they wait for the
                # next line and the block crosses the break.
                carried_start = run_start
                continue

            blocks.extend(self.split_run_into_blocks(run_start, line_end, size))

        if carried_start is not None:
            # The tail of the poem is too short to stand alone, so it joins the
            # block before it.
            if blocks:
                blocks[-1] = (blocks[-1][0], total_words)
            else:
                blocks.append((carried_start, total_words))

        return blocks

    def build_structural_blocks(self, structure: str) -> List[Tuple[int, int]]:
        """
        Cover the poem with blocks made of its own units

        Args:
            structure: "line", "line_pair" or "stanza"

        Returns:
            Block spans as [start, end) word index pairs, in reading order
        """
        lines = [span for span in self.line_spans if span[1] > span[0]]

        if structure == "line":
            return lines

        if structure == "stanza":
            return [span for span in self.stanza_spans if span[1] > span[0]]

        if structure == "line_pair":
            return [
                (lines[index][0], lines[min(index + 1, len(lines) - 1)][1])
                for index in range(0, len(lines), 2)
            ]

        return []

    def process_next_sensor_trigger(self) -> str:
        """
        Process the next sensor trigger and advance transformation
        
        Returns:
            The transformed poem after this trigger
        """
        self.trigger_count += 1
        
        if self.current_phase == TransformationPhase.PHASE_1_WORD_BY_WORD:
            self.advance_transformation_in_phase_1_word_by_word()
        elif self.current_phase == TransformationPhase.PHASE_2_GROWING_BLOCKS:
            self.advance_transformation_in_phase_2_growing_blocks()
        elif self.current_phase == TransformationPhase.PHASE_3_ARRIVAL:
            # Arrival is no longer a booked pass; keep gathering.
            self.current_phase = TransformationPhase.PHASE_2_GROWING_BLOCKS
            self.advance_transformation_in_phase_2_growing_blocks()
        
        if config.DEBUG_MODE:
            print(f"✓ Trigger #{self.trigger_count} processed")
        
        return self.current_transformation_state

    def claim_next_phase_1_word_index(self) -> Optional[int]:
        """
        Take the next word index from the Phase 1 queue

        Claiming and removing in one step means two triggers arriving together
        can't both pick up the same word.

        Returns:
            The word index to transform, or None if Phase 1 has no words left
        """
        if not self.phase_1_word_queue:
            return None
        return self.phase_1_word_queue.pop(0)

    def note_phase_1_word_completed(self) -> None:
        """
        Record that a Phase 1 word has settled on its final choice

        Once no words remain the poem is wholly in the target language, which is
        what ends the phase.
        """
        self.trigger_count += 1
        if not self.phase_1_word_queue:
            self.transition_to_phase_2_growing_blocks()

    def advance_transformation_in_phase_1_word_by_word(self) -> None:
        """
        Advance Phase 1: Replace one randomly chosen word with a cycled synonym
        """
        word_index = self.claim_next_phase_1_word_index()

        if word_index is None:
            self.transition_to_phase_2_growing_blocks()
            return
        
        original_word = self.original_poem_words[word_index]
        
        # Get or fetch translation with synonyms
        word_translation_data = self.get_or_fetch_word_translation_with_synonyms(
            original_word,
            context_line=self.get_original_line_for_word_index(word_index)
        )

        synonyms_list = word_translation_data.get('synonyms') or []
        primary = word_translation_data.get('target_word') or original_word

        if not synonyms_list:
            self.replace_word_in_transformation_state(word_index, primary)
            return

        # Cycle through synonyms
        if word_index not in self.word_synonym_cycle_index:
            self.word_synonym_cycle_index[word_index] = 0

        current_synonym_index = self.word_synonym_cycle_index[word_index]
        synonym_to_use = synonyms_list[current_synonym_index % len(synonyms_list)]
        
        # Update cycle index for next trigger on this word
        self.word_synonym_cycle_index[word_index] = (current_synonym_index + 1) % len(synonyms_list)
        
        # Replace word in transformation state
        self.replace_word_in_transformation_state(
            word_index,
            synonym_to_use
        )

    def advance_transformation_in_phase_2_growing_blocks(self) -> None:
        """
        Gather the poem: pick a span and try to leave it better

        There is no remaining-steps list. A trigger chooses a short block or a
        line (later, sometimes a stanza) and asks for an improvement. A chosen
        ending, if the poem has one, is a direction in the prompt, not a text
        that will be pasted after N clicks. The work stops when the poem already
        reads as that ending.
        """
        if self.poem_has_arrived():
            self.mark_transformation_complete()
            return

        self.gathering_steps += 1

        for _ in range(config.MAX_BLOCKS_PER_TRIGGER):
            span = self.pick_gathering_span()
            if span is None:
                return

            start_index, end_index = span
            if self.translate_and_replace_block(start_index, end_index):
                if self.poem_has_arrived():
                    self.mark_transformation_complete()
                return

    def pick_gathering_span(self) -> Optional[Tuple[int, int]]:
        """
        Choose the next span to work on, without a fixed itinerary

        Early gathering favours two- and three-word blocks inside a line.
        Later triggers raise the chance of a whole line, then a stanza, so the
        unit can grow without ever being promised on a given step.

        Returns:
            A [start, end) word span, or None if the poem has no words
        """
        total_words = len(self.original_poem_words)
        if total_words == 0:
            return None

        whole_poem = (0, total_words)
        short_blocks = []
        for size in config.BLOCK_GROWTH_WORD_SIZES:
            short_blocks.extend(
                span for span in self.partition_poem_into_blocks(size)
                if span != whole_poem
            )
        lines = [
            span for span in self.line_spans
            if span[1] > span[0] and span != whole_poem
        ]
        stanzas = [
            span for span in self.stanza_spans
            if span[1] > span[0] and span != whole_poem
        ]

        # Weights drift toward larger units as gathering continues, but a
        # short block is always possible, so the target cannot be timed.
        line_weight = min(0.55, 0.1 + 0.04 * self.gathering_steps)
        stanza_weight = min(0.2, max(0.0, 0.03 * (self.gathering_steps - 4))) if stanzas else 0.0
        short_weight = max(0.25, 1.0 - line_weight - stanza_weight)

        buckets = []
        weights = []
        if short_blocks:
            buckets.append(short_blocks)
            weights.append(short_weight)
        if lines:
            buckets.append(lines)
            weights.append(line_weight)
        if stanzas:
            buckets.append(stanzas)
            weights.append(stanza_weight)

        if not buckets:
            return whole_poem

        chosen_bucket = self.random_generator.choices(buckets, weights=weights, k=1)[0]
        return self.random_generator.choice(chosen_bucket)

    def build_destination_lines(self) -> List[str]:
        """
        Split a chosen ending across the poem's lines, if one was given

        Returns:
            One string per line, or an empty list when the poem has no chosen
            ending
        """
        if not self.final_translation or not self.line_spans:
            return []

        return self.fit_segments_to_line_count(
            self.final_translation.split('\n'),
            len(self.line_spans),
            [end - start for start, end in self.line_spans]
        )

    def poem_has_arrived(self) -> bool:
        """
        True when the poem already reads as its chosen ending

        Without a chosen ending there is nothing to arrive at, so gathering
        simply continues.

        Returns:
            Whether the current text matches the destination
        """
        if not self.destination_lines:
            return False

        current_lines = self.fit_segments_to_line_count(
            self.get_current_transformation_state().split('\n'),
            len(self.destination_lines)
        )
        return [
            ' '.join(line.split()) for line in current_lines
        ] == [
            ' '.join(line.split()) for line in self.destination_lines
        ]

    def mark_transformation_complete(self) -> None:
        """Record that the poem now reads as its destination."""
        self.current_phase = TransformationPhase.COMPLETE
        if config.DEBUG_MODE:
            print("✓ Poem transformation complete!")

    def translate_and_replace_block(self, start_index: int, end_index: int) -> bool:
        """
        Translate one span of the original poem and put it on the page

        Args:
            start_index: First word index of the block
            end_index: Word index just past the block

        Returns:
            True if the poem reads differently now
        """
        # Recorded so clients can label the change; gathering has no next
        # phase waiting to steal the trigger.
        self.last_action_phase = self.current_phase

        start_index, end_index = self.expand_span_to_whole_phrases(start_index, end_index)
        text_before = self.get_current_text_for_span(start_index, end_index)

        segments = self.get_or_fetch_block_translation(start_index, end_index)
        self.replace_block_in_transformation_state(start_index, end_index, segments)

        return self.get_current_text_for_span(start_index, end_index) != text_before

    def expand_span_to_whole_phrases(self, start_index: int, end_index: int) -> Tuple[int, int]:
        """
        Widen a block so it never cuts a phrase an earlier pass already fused

        Once a span has been translated as one phrase it lives in a single slot,
        and overwriting part of that slot would either duplicate its words or
        drop them. A later pass whose edges fall inside such a phrase therefore
        takes in the whole of it. In Phase 2 the widening stays inside the
        line: a two-word block must not become the whole poem.

        Args:
            start_index: First word index of the block
            end_index: Word index just past the block

        Returns:
            The block widened to the phrases it touches
        """
        filled = [index for index, word in enumerate(self.current_words) if word]
        if not filled:
            return start_index, end_index

        last_index = max(start_index, end_index - 1)

        starts_before = [index for index in filled if index <= start_index]
        widened_start = starts_before[-1] if starts_before else start_index

        starts_after = [index for index in filled if index > last_index]
        widened_end = starts_after[0] if starts_after else len(self.current_words)

        if self.current_phase == TransformationPhase.PHASE_2_GROWING_BLOCKS:
            line_start, line_end = self.line_span_containing(start_index)
            widened_start = max(widened_start, line_start)
            widened_end = min(widened_end, line_end)

        return widened_start, widened_end

    def line_span_containing(self, word_index: int) -> Tuple[int, int]:
        """
        Return the [start, end) word span of the line a word sits on

        Args:
            word_index: A word index in the original poem

        Returns:
            The line's span, or a span of just that word if no line is known
        """
        for line_start, line_end in self.line_spans:
            if line_start <= word_index < line_end:
                return line_start, line_end
        return word_index, word_index + 1

    def get_or_fetch_word_translation_with_synonyms(
        self,
        word: str,
        context_line: str = None
    ) -> Dict:
        """
        Get word translation from cache or fetch from AI
        
        Args:
            word: Word to translate
            context_line: Poem line the word appears in, sent to the AI so it
                picks the sense that fits. Part of the cache key, so the same
                word in another line is looked up again rather than inheriting
                a sense chosen for somewhere else.
            
        Returns:
            Dictionary with translation and synonyms
        """
        # Try to get from cache
        cached_translation = self.database_manager.retrieve_cached_word_translation(
            word,
            self.source_language_code,
            self.target_language_code,
            context_line or '',
            self.final_translation or ''
        )
        
        if cached_translation:
            if config.VERBOSE_LOGGING:
                print(f"  ✓ Found cached translation for: {word}")
            return cached_translation
        
        # Fetch from AI
        if config.VERBOSE_LOGGING:
            print(f"  → Requesting translation from AI for: {word}")
        
        ai_response = self.ai_translator.request_word_translation_with_synonyms(
            word,
            self.source_language,
            self.target_language,
            context_line=context_line,
            whole_poem=self.original_poem,
            arriving_at=self.final_translation
        )
        
        if not self.ai_translator.validate_word_translation_response(ai_response):
            raise ValueError(f"Invalid AI response for word: {word}")
        
        # Store in cache
        self.database_manager.store_new_word_translation_with_synonyms(
            word,
            ai_response['primary_translation'],
            ai_response['synonyms'],
            self.source_language_code,
            self.target_language_code,
            context_line or '',
            self.final_translation or ''
        )
        
        # Record in history
        self.database_manager.record_translation_history_entry(
            'word',
            word,
            ai_response['primary_translation'],
            self.source_language_code,
            self.target_language_code,
            ai_response.get('tokens_used')
        )
        
        return {
            'source_word': word,
            'target_word': ai_response['primary_translation'],
            'synonyms': ai_response['synonyms']
        }

    def split_span_by_lines(self, start_index: int, end_index: int) -> List[Tuple[int, int]]:
        """
        Cut a span of words at the poem's line breaks

        Args:
            start_index: First word index of the span
            end_index: Word index just past the span

        Returns:
            One [start, end) pair per line the span covers
        """
        portions = []

        for line_start, line_end in self.line_spans:
            portion_start = max(line_start, start_index)
            portion_end = min(line_end, end_index)
            if portion_start < portion_end:
                portions.append((portion_start, portion_end))

        return portions or [(start_index, end_index)]

    def get_current_text_for_span(self, start_index: int, end_index: int) -> str:
        """
        Get how a span of the poem reads right now, line breaks included

        Args:
            start_index: First word index of the span
            end_index: Word index just past the span

        Returns:
            The current text of the span
        """
        portions = []
        for portion_start, portion_end in self.split_span_by_lines(start_index, end_index):
            words = [word for word in self.current_words[portion_start:portion_end] if word]
            portions.append(' '.join(words))
        return '\n'.join(portions)

    def get_source_lines_for_span(self, start_index: int, end_index: int) -> List[str]:
        """
        Get the original text of a span, one string per line it covers

        Args:
            start_index: First word index of the span
            end_index: Word index just past the span

        Returns:
            The source text of the span, split at the poem's line breaks
        """
        return [
            ' '.join(self.original_poem_words[portion_start:portion_end])
            for portion_start, portion_end in self.split_span_by_lines(start_index, end_index)
        ]

    def fit_segments_to_line_count(
        self,
        segments: List[str],
        line_count: int,
        line_weights: List[int] = None
    ) -> List[str]:
        """
        Force a translation to have one segment per line of the block

        A block that crosses a line break must come back with the break intact,
        so a model that merges or splits lines is redistributed rather than
        allowed to change the shape of the poem.

        Args:
            segments: Lines of translated text as returned
            line_count: Number of lines the block covers
            line_weights: Word count of each source line, used to place the
                breaks when a merged translation has to be split back up

        Returns:
            Exactly line_count segments
        """
        if line_count <= 0:
            return []

        cleaned = [
            ' '.join(str(segment).split())
            for segment in segments
            if str(segment).strip()
        ]

        if len(cleaned) == line_count:
            return cleaned
        if not cleaned:
            return [''] * line_count
        if len(cleaned) > line_count:
            # Extra lines are almost always another rendering of the last line,
            # not a continuation of it. Folding them on produced the doubled
            # ending ("fire from its fire? fire of its fire?"). Keep the first
            # line_count and drop the rest; the prompt already asked for that many.
            return cleaned[:line_count]

        # Too few lines came back, so the words are spread over the lines in
        # proportion to the original, which puts the breaks close to where the
        # poem had them.
        weights = line_weights or []
        if len(weights) != line_count or sum(weights) <= 0:
            weights = [1] * line_count

        words = ' '.join(cleaned).split()
        total_weight = sum(weights)
        fitted = []
        taken = 0
        weight_so_far = 0
        for weight in weights:
            weight_so_far += weight
            up_to = round(len(words) * weight_so_far / total_weight)
            fitted.append(' '.join(words[taken:up_to]))
            taken = up_to
        return fitted

    def choose_translation_mode_for_block(self, start_index: int, end_index: int) -> str:
        """
        Decide how much licence a block's translation should take

        Short blocks are still assembling the sentence, so they stay literal.
        A line or more is translated as poetry. Nothing pastes a booked ending.

        Args:
            start_index: First word index of the block
            end_index: Word index just past the block

        Returns:
            One of the keys of config.BLOCK_TRANSLATION_MODES
        """
        if end_index - start_index <= config.LITERAL_BLOCK_MAX_WORDS:
            return config.BLOCK_TRANSLATION_MODE_LITERAL

        return config.BLOCK_TRANSLATION_MODE_POETIC

    def get_or_fetch_block_translation(
        self,
        start_index: int,
        end_index: int,
        mode: str = None
    ) -> List[str]:
        """
        Work out how a block should read, given how it reads now

        Every pass is shown the original passage and the poem's current
        rendering of it, and is asked to better that rendering or to say that
        it cannot. The answer therefore depends on the state of the poem, which
        is why the phrase cache is off by default: a cached answer would be the
        answer to a question about a poem in a different condition.

        Args:
            start_index: First word index of the block
            end_index: Word index just past the block
            mode: Translation mode to use, defaulting to the one this phase
                would choose for the span

        Returns:
            The translation, one segment per line the block covers
        """
        source_lines = self.get_source_lines_for_span(start_index, end_index)
        source_block = '\n'.join(source_lines)
        line_weights = [len(line.split()) for line in source_lines]
        mode = mode or self.choose_translation_mode_for_block(start_index, end_index)
        current_reading = self.get_current_text_for_span(start_index, end_index).split('\n')

        self.last_block_drafts = []
        self.last_block_improvement = None

        cached_translation = self.database_manager.retrieve_cached_phrase_translation(
            source_block,
            self.source_language_code,
            self.target_language_code,
            mode
        ) if config.CACHE_BLOCK_TRANSLATIONS else None

        if cached_translation:
            if config.VERBOSE_LOGGING:
                print(f"  ✓ Found cached {mode} translation for block: {source_block!r}")
            return self.fit_segments_to_line_count(
                cached_translation['target_phrase'].split('\n'),
                len(source_lines),
                line_weights
            )

        if config.VERBOSE_LOGGING:
            print(f"  → Working on {mode} passage: {source_block!r}")

        ai_response = self.ai_translator.request_block_translation(
            source_lines,
            self.source_language,
            self.target_language,
            poem_so_far=self.current_transformation_state,
            whole_poem=self.original_poem,
            mode=mode,
            current_reading=current_reading,
            arriving_at=self.final_translation
        )

        if not self.ai_translator.validate_block_translation_response(ai_response):
            raise ValueError(f"Invalid AI response for block: {source_block!r}")

        segments = self.fit_segments_to_line_count(
            ai_response['lines'],
            len(source_lines),
            line_weights
        )
        translated_block = '\n'.join(segments)

        self.last_block_drafts = [
            self.fit_segments_to_line_count(draft, len(source_lines), line_weights)
            for draft in ai_response.get('drafts') or []
        ]
        self.last_block_improvement = (
            str(ai_response.get('improvement')).strip()
            if ai_response.get('improvement') else None
        )

        if config.VERBOSE_LOGGING and self.last_block_improvement:
            kept = " (left alone)" if ai_response.get('unchanged') else ""
            print(f"    · {self.last_block_improvement}{kept}")

        if config.CACHE_BLOCK_TRANSLATIONS:
            self.database_manager.store_new_phrase_translation(
                source_block,
                translated_block,
                self.source_language_code,
                self.target_language_code,
                mode
            )

        self.database_manager.record_translation_history_entry(
            'phrase',
            source_block,
            translated_block,
            self.source_language_code,
            self.target_language_code,
            ai_response.get('tokens_used')
        )

        return segments

    def replace_word_in_transformation_state(self, word_index: int, replacement_word: str) -> None:
        """
        Replace a single word in the current transformation state
        
        Args:
            word_index: Index of word to replace
            replacement_word: New word to use
        """
        self.current_words[word_index] = replacement_word.strip()
        self.last_changed_span = (word_index, word_index + 1)
        self.current_transformation_state = self.rebuild_transformation_state()

    def rebuild_transformation_state(self, words: List[str] = None) -> str:
        """
        Reassemble the poem text from per-word slots, keeping line breaks

        Args:
            words: Slot list to render, defaulting to the current one

        Returns:
            The poem as text
        """
        words = self.current_words if words is None else words

        # Slots emptied by a phrase replacement are skipped, and the surviving
        # word takes the whitespace that ran up to the next surviving word, so
        # a line break after a collapsed span is preserved.
        filled = [index for index, word in enumerate(words) if word.strip()]

        pieces = []
        for position, index in enumerate(filled):
            pieces.append(words[index].strip())
            if position + 1 < len(filled):
                separator_index = filled[position + 1] - 1
                pieces.append(
                    self.word_separators[separator_index]
                    if separator_index < len(self.word_separators)
                    else ' '
                )
        return ''.join(pieces)

    def preview_word_slots(self, word_index: int, replacement_word: str) -> List[str]:
        """
        Build the slot list as it would look with one word swapped, without changing state

        Args:
            word_index: Index of the word to swap
            replacement_word: Word to show in its place

        Returns:
            A copy of the slot list with the swap applied
        """
        preview_words = list(self.current_words)
        preview_words[word_index] = replacement_word
        return preview_words

    def preview_word_replacement(self, word_index: int, replacement_word: str) -> str:
        """
        Render the poem as it would look with one word swapped, without changing state

        Args:
            word_index: Index of the word to swap
            replacement_word: Word to show in its place

        Returns:
            The poem as text
        """
        return self.rebuild_transformation_state(
            self.preview_word_slots(word_index, replacement_word)
        )

    def get_original_line_for_word_index(self, word_index: int) -> str:
        """
        Get the original poem line a word belongs to

        Used as translation context so the model can pick the sense that fits
        the poem rather than the most common sense of the word alone.

        Args:
            word_index: Index of the word

        Returns:
            The line of the original poem containing that word
        """
        if word_index < 0 or word_index >= len(self.original_poem_words):
            return ''

        start = word_index
        while start > 0 and '\n' not in self.word_separators[start - 1]:
            start -= 1

        end = word_index
        while (end < len(self.word_separators)
               and '\n' not in self.word_separators[end]):
            end += 1

        return ' '.join(self.original_poem_words[start:end + 1])

    def replace_block_in_transformation_state(
        self,
        start_index: int,
        end_index: int,
        segments: List[str]
    ) -> None:
        """
        Replace a span of words with a translation, keeping the poem's lines

        Args:
            start_index: Starting word index (inclusive)
            end_index: Ending word index (exclusive)
            segments: Translated text, one segment per line the span covers
        """
        portions = self.split_span_by_lines(start_index, end_index)
        segments = self.fit_segments_to_line_count(
            segments,
            len(portions),
            [portion_end - portion_start for portion_start, portion_end in portions]
        )

        for (portion_start, portion_end), segment in zip(portions, segments):
            # The line's portion collapses into its first slot and the rest are
            # emptied, so later words keep their original indices. Each line
            # keeps a slot of its own, which is what preserves the line break.
            self.current_words[portion_start] = segment.strip()
            for index in range(portion_start + 1, min(portion_end, len(self.current_words))):
                self.current_words[index] = ''

        self.last_changed_span = (start_index, end_index)
        self.current_transformation_state = self.rebuild_transformation_state()

    def transition_to_phase_2_growing_blocks(self) -> None:
        """Transition from Phase 1 to Phase 2"""
        self.current_phase = TransformationPhase.PHASE_2_GROWING_BLOCKS
        if config.DEBUG_MODE:
            print("✓ Transitioned to Phase 2: Gathering")

    def get_current_transformation_state(self) -> str:
        """
        Get the current state of the transforming poem
        
        Returns:
            The poem in its current transformation state
        """
        return self.current_transformation_state

    def get_current_phase(self) -> TransformationPhase:
        """
        Get the current transformation phase
        
        Returns:
            Current TransformationPhase
        """
        return self.current_phase

    def get_transformation_progress_percentage(self) -> float:
        """
        How far the poem has moved, not how many booked steps remain

        Phase 1 is the share of words already visited. After that, if a
        destination was given, it is the share of lines that already read as
        that destination. There is no third number that counts down to a paste
        of the ending.

        Returns:
            Progress as percentage (0-100)
        """
        if self.current_phase == TransformationPhase.COMPLETE:
            return 100.0

        total_words = len(self.original_poem_words)
        if total_words == 0:
            return 0.0

        if self.current_phase == TransformationPhase.PHASE_1_WORD_BY_WORD:
            visited = total_words - len(self.phase_1_word_queue)
            return (visited / total_words) * 100.0

        if self.destination_lines:
            current_lines = self.fit_segments_to_line_count(
                self.get_current_transformation_state().split('\n'),
                len(self.destination_lines)
            )
            matched = sum(
                1
                for current, destination in zip(current_lines, self.destination_lines)
                if ' '.join(current.split()) == ' '.join(destination.split())
            )
            return (matched / len(self.destination_lines)) * 100.0

        return 0.0

    def count_remaining_operations(self) -> int:
        """
        Words still waiting in Phase 1. After that, nothing is queued.

        Returns:
            Remaining Phase 1 words, else 0
        """
        if self.current_phase == TransformationPhase.PHASE_1_WORD_BY_WORD:
            return len(self.phase_1_word_queue)
        return 0

    def get_transformation_statistics(self) -> Dict:
        """
        Get statistics about the transformation
        
        Returns:
            Dictionary with transformation stats
        """
        return {
            "trigger_count": self.trigger_count,
            "current_phase": self.current_phase.name,
            "total_words": len(self.original_poem_words),
            "total_lines": len(self.line_spans),
            "remaining_operations": self.count_remaining_operations(),
            "planned_operations": None,
            "progress_percentage": self.get_transformation_progress_percentage(),
            "cached_words": self.database_manager.count_cached_word_translations(),
            "cached_phrases": self.database_manager.count_cached_phrase_translations(),
            "api_requests": self.database_manager.count_total_api_requests_made(),
            "total_tokens_used": self.database_manager.calculate_total_tokens_used()
        }
