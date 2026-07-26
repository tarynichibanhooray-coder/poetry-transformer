"""
OpenAI Translator helpers for Poetry Transformer
Provides request wrappers, response validation, and token-logging helpers.
Note: actual API call implementations are intentionally left as placeholders
so the module is testable without credentials. Replace _call_api with
real OpenAI SDK usage when available.
"""

from typing import Dict, List, Optional
import json
import time

import config


class OpenAITranslator:
    """Wrapper around AI translation calls with validation and logging."""

    def __init__(self):
        self._last_request_tokens = 0
        self._last_response_tokens = 0

    # ----- Public request methods used by engine -----
    def request_word_translation_with_synonyms(self, word: str, source_language: str, target_language: str) -> Dict:
        """
        Request a word translation with synonyms from the AI.

        Returns a dict containing at minimum:
          - primary_translation (str)
          - synonyms (List[str])
          - tokens_used (int) optional
        """
        prompt = self._build_word_prompt(word, source_language, target_language)
        response = self._call_api(prompt)
        # Expected response shape (example):
        # {"primary_translation": "...", "synonyms": ["...", ...], "tokens_used": 25}
        # Log tokens if present
        tokens = response.get("tokens_used")
        if tokens is not None:
            self._last_request_tokens = response.get("request_tokens", 0)
            self._last_response_tokens = response.get("response_tokens", 0)
        return response

    def request_phrase_translation(self, phrase: str, source_language: str, target_language: str) -> Dict:
        """
        Request a phrase translation from the AI.

        Returns a dict containing at minimum:
          - translation (str)
          - tokens_used (int) optional
        """
        prompt = self._build_phrase_prompt(phrase, source_language, target_language)
        response = self._call_api(prompt)
        return response

    # ----- Validation helpers -----
    def validate_word_translation_response(self, response: Dict) -> bool:
        """
        Verify the AI response contains required keys and types for word translations.
        """
        if not isinstance(response, dict):
            return False
        if 'primary_translation' not in response or 'synonyms' not in response:
            return False
        if not isinstance(response['primary_translation'], str):
            return False
        if not isinstance(response['synonyms'], list):
            return False
        return True

    def validate_phrase_translation_response(self, response: Dict) -> bool:
        """
        Verify the AI response contains required keys and types for phrase translations.
        """
        if not isinstance(response, dict):
            return False
        if 'translation' not in response:
            return False
        if not isinstance(response['translation'], str):
            return False
        return True

    # ----- Utility helpers -----
    def make_cache_key_for_word(self, word: str, source_code: str, target_code: str) -> str:
        """Create a stable cache key for a word translation."""
        return f"word:{source_code}:{target_code}:{word.lower()}"

    def make_cache_key_for_phrase(self, phrase: str, source_code: str, target_code: str) -> str:
        """Create a stable cache key for a phrase translation."""
        normalized = phrase.strip().lower()
        return f"phrase:{source_code}:{target_code}:{normalized}"

    def _build_word_prompt(self, word: str, source_language: str, target_language: str) -> str:
        return (
            f"Translate the single word '{word}' from {source_language} to {target_language}. "
            "Return a JSON object with keys: primary_translation (string) and synonyms (array of up to 7 alternatives)."
        )

    def _build_phrase_prompt(self, phrase: str, source_language: str, target_language: str) -> str:
        return (
            f"Translate the phrase '{phrase}' from {source_language} to {target_language}. "
            "Return a JSON object with key: translation (string)."
        )

    def _call_api(self, prompt: str) -> Dict:
        """
        Placeholder API call. Replace this method with real OpenAI API invocation.

        For now this returns a deterministic stub to keep the rest of the system
        runnable without network access.
        """
        # Simulate latency
        time.sleep(0.05)

        # Very small heuristic: if prompt asks for a single word, return stub synonyms
        if 'single word' in prompt or "Translate the single word" in prompt:
            # Extract word heuristically
            try:
                start = prompt.index("'") + 1
                end = prompt.index("'", start)
                word = prompt[start:end]
            except Exception:
                word = "word"
            primary = f"{word}_tgt"
            synonyms = [f"{word}_alt{i}" for i in range(1, 4)]
            return {"primary_translation": primary, "synonyms": synonyms, "tokens_used": 5}

        # Phrase stub
        try:
            start = prompt.index("'") + 1
            end = prompt.index("'", start)
            phrase = prompt[start:end]
        except Exception:
            phrase = "phrase"
        translation = f"{phrase}_tgt"
        return {"translation": translation, "tokens_used": 12}
