"""
Poem Transformer Engine for Poetry Transformer
Core logic for multi-phase word-to-phrase transformation
Emits structured translation events to the database and a JSONL stream for animation.
"""

from typing import List, Dict, Tuple, Optional
from enum import Enum
import re
import json
from pathlib import Path

import config
from database_manager import DatabaseManager
from openai_translator import OpenAITranslator


class TransformationPhase(Enum):
    """Enum for transformation phases"""
    PHASE_1_WORD_BY_WORD = 1
    PHASE_2_PAIRS = 2
    PHASE_3_GROWING_PHRASES = 3
    COMPLETE = 4


class PoemTransformerEngine:
    """Core engine for transforming poems through multiple translation phases
    Emits events describing every visible revision so the installation can animate them.
    """

    def __init__(
        self,
        source_language: str = config.SOURCE_LANGUAGE,
        target_language: str = config.TARGET_LANGUAGE,
        source_language_code: str = config.SOURCE_LANGUAGE_CODE,
        target_language_code: str = config.TARGET_LANGUAGE_CODE
    ):
        """
        Initialize the poem transformer engine
        """
        self.source_language = source_language
        self.target_language = target_language
        self.source_language_code = source_language_code
        self.target_language_code = target_language_code

        self.database_manager = DatabaseManager()
        self.ai_translator = OpenAITranslator()

        self.original_poem = None
        self.original_poem_words = []
        self.current_transformation_state = None
        self.current_phase = TransformationPhase.PHASE_1_WORD_BY_WORD
        self.trigger_count = 0

        # Caching for word translations during phase 1
        self.word_synonym_cycle_index = {}

        # Monotonic sequence for events
        self.event_sequence = 1

        # Ensure output directory exists for JSONL stream
        stream_path = Path(config.STREAM_OUTPUT_JSONL_PATH)
        stream_path.parent.mkdir(parents=True, exist_ok=True)
        # Create file if missing
        if not stream_path.exists():
            stream_path.write_text("")

        if config.DEBUG_MODE:
            print(f"✓ Poem Transformer Engine initialized")
            print(f"  Source: {source_language} → Target: {target_language}")

    # -------------------------- Event emission --------------------------
    def emit_event(
        self,
        unit_level: str,
        unit_path: Optional[str],
        previous_state: Optional[str],
        new_state: Optional[str],
        reason: Optional[str],
        confidence: Optional[float] = None,
        alternatives: Optional[List[str]] = None,
        triggered_by_context: bool = False,
        context_snapshot: Optional[Dict] = None
    ) -> None:
        """
        Record an event in the DB and append it to the JSONL stream.
        """
        event = {
            "sequence_index": self.event_sequence,
            "timestamp": None,  # DB will set timestamp; we keep None here for JSONL
            "unit_level": unit_level,
            "unit_path": unit_path,
            "previous_state": previous_state,
            "new_state": new_state,
            "reason": reason,
            "confidence": confidence,
            "alternatives": alternatives or [],
            "triggered_by_context": bool(triggered_by_context),
            "context_snapshot": context_snapshot or {}
        }

        try:
            # Record to DB
            self.database_manager.record_event(event)
        except Exception as e:
            if config.DEBUG_MODE:
                print(f"✗ Failed to record event to DB: {e}")

        # Append to JSONL stream
        try:
            stream_path = Path(config.STREAM_OUTPUT_JSONL_PATH)
            with stream_path.open('a', encoding='utf-8') as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as e:
            if config.DEBUG_MODE:
                print(f"✗ Failed to write event to JSONL stream: {e}")

        self.event_sequence += 1

    # -------------------------- Poem lifecycle --------------------------
    def load_poem_from_file(self, file_path: str) -> str:
        """
        Load a poem from a text file
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

    def initialize_poem_with_text(self, poem_text: str) -> None:
        """
        Initialize the poem transformer with poem text
        """
        self.original_poem = poem_text
        self.original_poem_words = self.extract_words_from_poem_text(poem_text)
        self.current_transformation_state = poem_text
        self.trigger_count = 0
        self.current_phase = TransformationPhase.PHASE_1_WORD_BY_WORD
        self.word_synonym_cycle_index = {}

        # Emit initial event representing the loaded poem
        self.emit_event(
            unit_level="poem",
            unit_path=None,
            previous_state=None,
            new_state=self.current_transformation_state,
            reason="poem_loaded",
            confidence=1.0,
            alternatives=[],
            triggered_by_context=False,
            context_snapshot={"total_words": len(self.original_poem_words)}
        )

        if config.DEBUG_MODE:
            print(f"✓ Poem initialized with {len(self.original_poem_words)} words")

    def extract_words_from_poem_text(self, poem_text: str) -> List[str]:
        """
        Extract individual words from poem text preserving order
        """
        # Split on whitespace but preserve word order
        words = poem_text.split()
        return words

    def process_next_sensor_trigger(self) -> str:
        """
        Process the next sensor trigger and advance transformation
        """
        self.trigger_count += 1

        if self.current_phase == TransformationPhase.PHASE_1_WORD_BY_WORD:
            self.advance_transformation_in_phase_1_word_by_word()
        elif self.current_phase == TransformationPhase.PHASE_2_PAIRS:
            self.advance_transformation_in_phase_2_pairs()
        elif self.current_phase == TransformationPhase.PHASE_3_GROWING_PHRASES:
            self.advance_transformation_in_phase_3_growing_phrases()

        if config.DEBUG_MODE:
            print(f"✓ Trigger #{self.trigger_count} processed")

        return self.current_transformation_state

    # -------------------------- Phase implementations --------------------------
    def advance_transformation_in_phase_1_word_by_word(self) -> None:
        """
        Advance Phase 1: Replace one word at a time with cycled synonyms
        """
        word_index = self.calculate_which_word_to_transform_in_phase_1()

        if word_index >= len(self.original_poem_words):
            # Phase 1 complete, move to Phase 2
            self.transition_to_phase_2_pairs()
            return

        original_word = self.original_poem_words[word_index]

        # Get or fetch translation with synonyms
        word_translation_data = self.get_or_fetch_word_translation_with_synonyms(
            original_word
        )

        # Cycle through synonyms
        if word_index not in self.word_synonym_cycle_index:
            self.word_synonym_cycle_index[word_index] = 0

        synonyms_list = word_translation_data['synonyms'] or [word_translation_data.get('target_word')]
        if not synonyms_list:
            synonyms_list = [word_translation_data.get('target_word') or original_word]

        current_synonym_index = self.word_synonym_cycle_index[word_index]
        synonym_to_use = synonyms_list[current_synonym_index % len(synonyms_list)]

        # Update cycle index for next trigger on this word
        self.word_synonym_cycle_index[word_index] = (current_synonym_index + 1) % len(synonyms_list)

        # Replace word in transformation state
        previous_state = self.current_transformation_state
        self.replace_word_in_transformation_state(
            word_index,
            synonym_to_use
        )

        # Emit event describing this visible change
        self.emit_event(
            unit_level="word",
            unit_path=str(word_index),
            previous_state=previous_state,
            new_state=self.current_transformation_state,
            reason="cycle",
            confidence=0.6,
            alternatives=synonyms_list,
            triggered_by_context=(self.current_phase != TransformationPhase.PHASE_1_WORD_BY_WORD),
            context_snapshot={"source_word": original_word}
        )

    def advance_transformation_in_phase_2_pairs(self) -> None:
        """
        Advance Phase 2: Transform 2-word phrases
        """
        pair_index = self.calculate_which_pair_to_transform_in_phase_2()

        if pair_index * 2 >= len(self.original_poem_words):
            # Phase 2 complete, move to Phase 3
            self.transition_to_phase_3_growing_phrases()
            return

        start_word_index = pair_index * 2
        end_word_index = min(start_word_index + 2, len(self.original_poem_words))

        source_pair = ' '.join(
            self.original_poem_words[start_word_index:end_word_index]
        )

        pair_translation_data = self.get_or_fetch_phrase_translation(source_pair)

        previous_state = self.current_transformation_state
        self.replace_phrase_in_transformation_state(
            start_word_index,
            end_word_index,
            pair_translation_data['translation']
        )

        self.emit_event(
            unit_level="phrase",
            unit_path=f"{start_word_index}-{end_word_index}",
            previous_state=previous_state,
            new_state=self.current_transformation_state,
            reason="pair_replace",
            confidence=0.7,
            alternatives=[pair_translation_data.get('translation')],
            triggered_by_context=True,
            context_snapshot={"source_phrase": source_pair}
        )

    def advance_transformation_in_phase_3_growing_phrases(self) -> None:
        """
        Advance Phase 3: Gradually increase phrase size until full translation
        """
        phrase_size = self.calculate_growing_phrase_size_in_phase_3()

        if phrase_size > len(self.original_poem_words):
            # Transformation complete
            self.current_phase = TransformationPhase.COMPLETE
            if config.DEBUG_MODE:
                print("✓ Poem transformation complete!")
            # Emit finalization event
            self.emit_event(
                unit_level="poem",
                unit_path=None,
                previous_state=None,
                new_state=self.current_transformation_state,
                reason="transformation_complete",
                confidence=1.0,
                alternatives=[],
                triggered_by_context=True,
                context_snapshot={}
            )
            return

        # Get the full poem phrase at this size and replace
        source_phrase = ' '.join(self.original_poem_words[:phrase_size])

        phrase_translation_data = self.get_or_fetch_phrase_translation(source_phrase)

        previous_state = self.current_transformation_state
        self.replace_phrase_in_transformation_state(
            0,
            phrase_size,
            phrase_translation_data['translation']
        )

        self.emit_event(
            unit_level="phrase",
            unit_path=f"0-{phrase_size}",
            previous_state=previous_state,
            new_state=self.current_transformation_state,
            reason="growing_phrase",
            confidence=0.75,
            alternatives=[phrase_translation_data.get('translation')],
            triggered_by_context=True,
            context_snapshot={"source_phrase": source_phrase}
        )

    # -------------------------- AI fetch + caching helpers --------------------------
    def get_or_fetch_word_translation_with_synonyms(self, word: str) -> Dict:
        """
        Get word translation from cache or fetch from AI
        """
        # Try to get from cache
        cached_translation = self.database_manager.retrieve_cached_word_translation(
            word,
            self.source_language_code,
            self.target_language_code
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
            self.target_language
        )

        if not self.ai_translator.validate_word_translation_response(ai_response):
            raise ValueError(f"Invalid AI response for word: {word}")

        # Store in cache
        self.database_manager.store_new_word_translation_with_synonyms(
            word,
            ai_response['primary_translation'],
            ai_response['synonyms'],
            self.source_language_code,
            self.target_language_code
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

        # Emit an event exposing the candidate synonyms (thinking-aloud)
        try:
            self.emit_event(
                unit_level="word",
                unit_path=None,
                previous_state=None,
                new_state=None,
                reason="fetched_from_ai",
                confidence=0.5,
                alternatives=ai_response.get('synonyms'),
                triggered_by_context=False,
                context_snapshot={"source_word": word}
            )
        except Exception:
            pass

        return {
            'source_word': word,
            'target_word': ai_response['primary_translation'],
            'synonyms': ai_response['synonyms']
        }

    def get_or_fetch_phrase_translation(self, phrase: str) -> Dict:
        """
        Get phrase translation from cache or fetch from AI
        """
        # Try to get from cache
        cached_translation = self.database_manager.retrieve_cached_phrase_translation(
            phrase,
            self.source_language_code,
            self.target_language_code
        )

        if cached_translation:
            if config.VERBOSE_LOGGING:
                print(f"  ✓ Found cached translation for: {phrase}")
            return cached_translation

        # Fetch from AI
        if config.VERBOSE_LOGGING:
            print(f"  → Requesting translation from AI for: {phrase}")

        ai_response = self.ai_translator.request_phrase_translation(
            phrase,
            self.source_language,
            self.target_language
        )

        if not self.ai_translator.validate_phrase_translation_response(ai_response):
            raise ValueError(f"Invalid AI response for phrase: {phrase}")

        # Store in cache
        self.database_manager.store_new_phrase_translation(
            phrase,
            ai_response['translation'],
            self.source_language_code,
            self.target_language_code
        )

        # Record in history
        self.database_manager.record_translation_history_entry(
            'phrase',
            phrase,
            ai_response['translation'],
            self.source_language_code,
            self.target_language_code,
            ai_response.get('tokens_used')
        )

        # Emit an event exposing the phrase translation (thinking-aloud)
        try:
            self.emit_event(
                unit_level="phrase",
                unit_path=None,
                previous_state=None,
                new_state=ai_response.get('translation'),
                reason="fetched_from_ai",
                confidence=0.6,
                alternatives=[ai_response.get('translation')],
                triggered_by_context=False,
                context_snapshot={"source_phrase": phrase}
            )
        except Exception:
            pass

        return {
            'source_phrase': phrase,
            'translation': ai_response['translation']
        }

    # -------------------------- Utility calculations --------------------------
    def calculate_which_word_to_transform_in_phase_1(self) -> int:
        """
        Calculate which word index to transform next in Phase 1
        """
        # Each trigger transforms one word
        return self.trigger_count - 1

    def calculate_which_pair_to_transform_in_phase_2(self) -> int:
        """
        Calculate which word pair to transform next in Phase 2
        """
        # Adjust for Phase 2 start
        phase_2_triggers = self.trigger_count - len(self.original_poem_words)
        return phase_2_triggers - 1

    def calculate_growing_phrase_size_in_phase_3(self) -> int:
        """
        Calculate the phrase size for current Phase 3 trigger
        """
        # Start with 3 words and grow
        phase_3_triggers = self.trigger_count - len(self.original_poem_words) - (len(self.original_poem_words) // 2)
        base_size = 3
        return base_size + phase_3_triggers

    def replace_word_in_transformation_state(self, word_index: int, replacement_word: str) -> None:
        """
        Replace a single word in the current transformation state
        """
        current_words = self.current_transformation_state.split()
        # Guard index
        if word_index < 0 or word_index >= len(current_words):
            return
        current_words[word_index] = replacement_word
        self.current_transformation_state = ' '.join(current_words)

    def replace_phrase_in_transformation_state(
        self,
        start_index: int,
        end_index: int,
        replacement_phrase: str
    ) -> None:
        """
        Replace a phrase (multiple words) in the current transformation state
        """
        current_words = self.current_transformation_state.split()
        replacement_words = replacement_phrase.split()
        current_words[start_index:end_index] = replacement_words
        self.current_transformation_state = ' '.join(current_words)

    def transition_to_phase_2_pairs(self) -> None:
        """Transition from Phase 1 to Phase 2"""
        self.current_phase = TransformationPhase.PHASE_2_PAIRS
        if config.DEBUG_MODE:
            print("✓ Transitioned to Phase 2: Pairs")
        self.emit_event(
            unit_level="phase_transition",
            unit_path=None,
            previous_state=None,
            new_state="PHASE_2_PAIRS",
            reason="phase_transition",
            confidence=1.0,
            alternatives=[],
            triggered_by_context=True,
            context_snapshot={}
        )

    def transition_to_phase_3_growing_phrases(self) -> None:
        """Transition from Phase 2 to Phase 3"""
        self.current_phase = TransformationPhase.PHASE_3_GROWING_PHRASES
        if config.DEBUG_MODE:
            print("✓ Transitioned to Phase 3: Growing Phrases")
        self.emit_event(
            unit_level="phase_transition",
            unit_path=None,
            previous_state=None,
            new_state="PHASE_3_GROWING_PHRASES",
            reason="phase_transition",
            confidence=1.0,
            alternatives=[],
            triggered_by_context=True,
            context_snapshot={}
        )

    def get_current_transformation_state(self) -> str:
        """
        Get the current state of the transforming poem
        """
        return self.current_transformation_state

    def get_current_phase(self) -> TransformationPhase:
        """
        Get the current transformation phase
        """
        return self.current_phase

    def get_transformation_progress_percentage(self) -> float:
        """
        Calculate progress percentage through full transformation
        """
        if self.current_phase == TransformationPhase.COMPLETE:
            return 100.0

        total_operations = len(self.original_poem_words) * 2  # Phase 1 + Phase 2 estimate
        progress = (self.trigger_count / total_operations) * 100
        return min(progress, 99.9)  # Cap at 99.9% until complete

    def get_transformation_statistics(self) -> Dict:
        """
        Get statistics about the transformation
        """
        return {
            "trigger_count": self.trigger_count,
            "current_phase": self.current_phase.name,
            "total_words": len(self.original_poem_words),
            "progress_percentage": self.get_transformation_progress_percentage(),
            "cached_words": self.database_manager.count_cached_word_translations(),
            "cached_phrases": self.database_manager.count_cached_phrase_translations(),
            "api_requests": self.database_manager.count_total_api_requests_made(),
            "total_tokens_used": self.database_manager.calculate_total_tokens_used()
        }
