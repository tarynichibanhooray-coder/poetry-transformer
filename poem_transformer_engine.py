"""
Poem Transformer Engine for Poetry Transformer
Core logic for multi-phase word-to-phrase transformation
"""

from typing import List, Dict, Tuple, Optional
from enum import Enum
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


def join_words_with_separators(words: List[str], separators: List[str]) -> str:
    """
    Rebuild text from words and their separators, keeping line breaks intact

    Args:
        words: Words in order
        separators: Whitespace runs, where separators[i] follows words[i]

    Returns:
        The reassembled text
    """
    pieces = []
    for index, word in enumerate(words):
        pieces.append(word)
        if index < len(words) - 1:
            pieces.append(separators[index] if index < len(separators) else ' ')
    return ''.join(pieces)


class TransformationPhase(Enum):
    """Enum for transformation phases"""
    PHASE_1_WORD_BY_WORD = 1
    PHASE_2_PAIRS = 2
    PHASE_3_GROWING_PHRASES = 3
    COMPLETE = 4


class PoemTransformerEngine:
    """Core engine for transforming poems through multiple translation phases"""

    def __init__(
        self,
        source_language: str = config.SOURCE_LANGUAGE,
        target_language: str = config.TARGET_LANGUAGE,
        source_language_code: str = config.SOURCE_LANGUAGE_CODE,
        target_language_code: str = config.TARGET_LANGUAGE_CODE
    ):
        """
        Initialize the poem transformer engine
        
        Args:
            source_language: Name of source language
            target_language: Name of target language
            source_language_code: ISO code for source language
            target_language_code: ISO code for target language
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
        target_language_code: str = None
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

        self.original_poem = poem_text
        self.original_poem_words = self.extract_words_from_poem_text(poem_text)
        self.current_transformation_state = poem_text
        self.trigger_count = 0
        self.current_phase = TransformationPhase.PHASE_1_WORD_BY_WORD
        self.word_synonym_cycle_index = {}
        
        if config.DEBUG_MODE:
            print(f"✓ Poem initialized with {len(self.original_poem_words)} words")
            print(f"  {self.source_language} → {self.target_language}")

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

    def process_next_sensor_trigger(self) -> str:
        """
        Process the next sensor trigger and advance transformation
        
        Returns:
            The transformed poem after this trigger
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
        
        synonyms_list = word_translation_data['synonyms']
        current_synonym_index = self.word_synonym_cycle_index[word_index]
        synonym_to_use = synonyms_list[current_synonym_index % len(synonyms_list)]
        
        # Update cycle index for next trigger on this word
        self.word_synonym_cycle_index[word_index] = (current_synonym_index + 1) % len(synonyms_list)
        
        # Replace word in transformation state
        self.replace_word_in_transformation_state(
            word_index,
            synonym_to_use
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
        
        self.replace_phrase_in_transformation_state(
            start_word_index,
            end_word_index,
            pair_translation_data['translation']
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
            return
        
        # Get the full poem phrase at this size and replace
        source_phrase = ' '.join(self.original_poem_words[:phrase_size])
        
        phrase_translation_data = self.get_or_fetch_phrase_translation(source_phrase)
        
        self.replace_phrase_in_transformation_state(
            0,
            phrase_size,
            phrase_translation_data['translation']
        )

    def get_or_fetch_word_translation_with_synonyms(self, word: str) -> Dict:
        """
        Get word translation from cache or fetch from AI
        
        Args:
            word: Word to translate
            
        Returns:
            Dictionary with translation and synonyms
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
        
        return {
            'source_word': word,
            'target_word': ai_response['primary_translation'],
            'synonyms': ai_response['synonyms']
        }

    def get_or_fetch_phrase_translation(self, phrase: str) -> Dict:
        """
        Get phrase translation from cache or fetch from AI
        
        Args:
            phrase: Phrase to translate
            
        Returns:
            Dictionary with translation
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
        
        return {
            'source_phrase': phrase,
            'translation': ai_response['translation']
        }

    def calculate_which_word_to_transform_in_phase_1(self) -> int:
        """
        Calculate which word index to transform next in Phase 1
        
        Returns:
            Word index to transform
        """
        # Each trigger transforms one word
        return self.trigger_count - 1

    def calculate_which_pair_to_transform_in_phase_2(self) -> int:
        """
        Calculate which word pair to transform next in Phase 2
        
        Returns:
            Pair index to transform
        """
        # Adjust for Phase 2 start
        phase_2_triggers = self.trigger_count - len(self.original_poem_words)
        return phase_2_triggers - 1

    def calculate_growing_phrase_size_in_phase_3(self) -> int:
        """
        Calculate the phrase size for current Phase 3 trigger
        
        Returns:
            Number of words in phrase to transform
        """
        # Start with 3 words and grow
        phase_3_triggers = self.trigger_count - len(self.original_poem_words) - (len(self.original_poem_words) // 2)
        base_size = 3
        return base_size + phase_3_triggers

    def replace_word_in_transformation_state(self, word_index: int, replacement_word: str) -> None:
        """
        Replace a single word in the current transformation state
        
        Args:
            word_index: Index of word to replace
            replacement_word: New word to use
        """
        current_words, separators = split_words_and_separators(
            self.current_transformation_state
        )
        current_words[word_index] = replacement_word
        self.current_transformation_state = join_words_with_separators(
            current_words, separators
        )

    def replace_phrase_in_transformation_state(
        self,
        start_index: int,
        end_index: int,
        replacement_phrase: str
    ) -> None:
        """
        Replace a phrase (multiple words) in the current transformation state
        
        Args:
            start_index: Starting word index (inclusive)
            end_index: Ending word index (exclusive)
            replacement_phrase: New phrase to use
        """
        current_words, separators = split_words_and_separators(
            self.current_transformation_state
        )
        replacement_words = replacement_phrase.split()

        # Keep whatever whitespace trailed the replaced span so the line break
        # after the phrase survives, even when the word count changes.
        trailing_separator = (
            separators[end_index - 1] if end_index - 1 < len(separators) else ' '
        )
        separators[start_index:end_index] = (
            [' '] * (len(replacement_words) - 1) + [trailing_separator]
        )
        current_words[start_index:end_index] = replacement_words

        self.current_transformation_state = join_words_with_separators(
            current_words, separators
        )

    def transition_to_phase_2_pairs(self) -> None:
        """Transition from Phase 1 to Phase 2"""
        self.current_phase = TransformationPhase.PHASE_2_PAIRS
        if config.DEBUG_MODE:
            print("✓ Transitioned to Phase 2: Pairs")

    def transition_to_phase_3_growing_phrases(self) -> None:
        """Transition from Phase 2 to Phase 3"""
        self.current_phase = TransformationPhase.PHASE_3_GROWING_PHRASES
        if config.DEBUG_MODE:
            print("✓ Transitioned to Phase 3: Growing Phrases")

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
        Calculate progress percentage through full transformation
        
        Returns:
            Progress as percentage (0-100)
        """
        if self.current_phase == TransformationPhase.COMPLETE:
            return 100.0
        
        total_operations = len(self.original_poem_words) * 2  # Phase 1 + Phase 2 estimate
        if total_operations == 0:  # No poem loaded yet
            return 0.0

        progress = (self.trigger_count / total_operations) * 100
        return min(progress, 99.9)  # Cap at 99.9% until complete

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
            "progress_percentage": self.get_transformation_progress_percentage(),
            "cached_words": self.database_manager.count_cached_word_translations(),
            "cached_phrases": self.database_manager.count_cached_phrase_translations(),
            "api_requests": self.database_manager.count_total_api_requests_made(),
            "total_tokens_used": self.database_manager.calculate_total_tokens_used()
        }
