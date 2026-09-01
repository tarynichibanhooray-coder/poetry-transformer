"""
OpenAI Translator for Poetry Transformer

Each call is three layers: a stable system prompt, a stage instruction, and a
JSON payload containing only the text this stage is allowed to see. No chat
history. No later lines of the poem. No destination translation.
"""

import json
import re
from typing import Dict, List, Optional

from openai import OpenAI, OpenAIError

import config
from translation_prompts import (
    GLOBAL_TRANSLATION_INSTRUCTIONS,
    PHRASE_PROMPT,
    POEM_VARIATIONS_SCHEMA,
    TRANSLATION_STATE_SCHEMA,
    VARIATION_PROMPT,
    WORD_PROMPT,
)
from word_senses import anchor_word_to_origin, tether_word_response


FUNCTION_WORD_PARTS_OF_SPEECH = {
    'article',
    'determiner',
    'pronoun',
    'preposition',
    'conjunction',
    'auxiliary',
    'particle',
}

SOURCE_FUNCTION_WORDS = {
    'el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas',
    'de', 'del', 'al', 'y', 'o', 'a', 'en', 'que', 'se', 'su', 'sus',
    'the', 'a', 'an', 'of', 'and', 'or', 'to', 'in',
}

ANNOTATION = re.compile(r'\s*[\(\[\{][^\)\]\}]*[\)\]\}]?\s*$')
GLOSS_LABEL = re.compile(
    r'^\s*(?:noun|verb|adjective|adverb|pronoun|article|preposition|'
    r'conjunction|determiner|singular|plural|masculine|feminine)\s*[:\-–]\s*',
    re.IGNORECASE,
)


def clean_word_output(text: str) -> str:
    """Strip the grammar notes a word request sometimes comes back wearing.

    "that (singular)" is the model answering a question nobody asked. The
    page can only show the word.
    """
    cleaned = str(text or '').strip()
    cleaned = GLOSS_LABEL.sub('', cleaned)
    cleaned = ANNOTATION.sub('', cleaned)
    cleaned = cleaned.strip().strip('"“”')
    return ' '.join(cleaned.split())


class OpenAITranslator:
    """Manages communication with OpenAI API for translations"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.OPENAI_API_KEY
        self.client = OpenAI(api_key=self.api_key)
        self.model = config.OPENAI_MODEL
        self.last_exchange = None
        if config.DEBUG_MODE:
            print(f"✓ OpenAI Translator initialized with model: {self.model}")

    def request_word_translation_with_synonyms(
        self,
        source_word: str,
        source_language: str = None,
        target_language: str = None,
        origin_word: str = None,
        **_ignored
    ) -> Dict:
        """Stage 1. One source word, standing alone. No context is sent.

        The one thing that may travel with the word is origin_word, the word
        it was translated from on the way out. That is the word's own history,
        not a look at where the poem is going, and it is only ever set on the
        return journey.
        """
        state = self.request_translation_state(
            WORD_PROMPT,
            self.restricted_payload(
                "word",
                source_word,
                None,
                extras={"origin_word": origin_word} if origin_word else None,
            ),
        )
        response = self.word_response_from_state(state, source_word)
        response = tether_word_response(response, source_word)
        response = anchor_word_to_origin(response, origin_word)
        self.tag_last_exchange(kind="word")
        return self.strip_synonyms_from_function_words(response, source_word)

    def request_phrase_translation(
        self,
        scrap_source: str,
        source_line: str = None,
        current_reading: str = None,
        previous_state: Optional[Dict] = None,
        **_ignored
    ) -> Dict:
        """Stage 2. A short scrap, with its own line visible as sense context."""
        state = self.request_translation_state(
            PHRASE_PROMPT,
            self.restricted_payload(
                "phrase",
                scrap_source,
                previous_state,
                extras={
                    "current_reading": current_reading or "",
                    "source_line": source_line or scrap_source,
                },
            ),
        )
        response = self.block_response_from_state(state, [current_reading or scrap_source])
        self.tag_last_exchange(kind="phrase")
        return response

    def request_poem_variations(
        self,
        source_poem: str,
        current_reading: str,
        target_language: str = None,
        lines_expected: int = 0,
        **_ignored
    ) -> List[Dict]:
        """Stage 3. Several complete attempts at the whole poem, ranked.

        Nothing here is told where the poem is going. The attempts are asked
        for on the single measure of fidelity to the original, and the engine
        shows them worst first.
        """
        state = self.request_translation_state(
            VARIATION_PROMPT,
            self.restricted_payload(
                "variations",
                source_poem,
                None,
                extras={
                    "current_reading": current_reading or "",
                    "write_in_language": target_language or "",
                    "lines_expected": lines_expected or len(
                        [line for line in (source_poem or "").split("\n") if line.strip()]
                    ),
                },
            ),
            schema=POEM_VARIATIONS_SCHEMA,
            schema_name="poem_variations",
            # Five readings that genuinely disagree will not come out of a
            # temperature tuned for settling on one right answer.
            temperature=config.VARIATION_TEMPERATURE,
        )
        self.tag_last_exchange(kind="variations")
        return self.variations_from_state(state)

    def variations_from_state(self, state: Dict) -> List[Dict]:
        """Rank order, worst first, with blanks and duplicates removed."""
        seen = set()
        variations = []
        for item in (state.get("variations") or []):
            if not isinstance(item, dict):
                continue
            translation = str(item.get("translation") or "").strip()
            key = self._norm(translation)
            if not translation or key in seen:
                continue
            seen.add(key)
            variations.append({
                "rank": item.get("rank") if isinstance(item.get("rank"), int) else 0,
                "translation": translation,
                "captures": str(item.get("captures") or "").strip(),
            })
        variations.sort(key=lambda item: item["rank"])
        return variations

    def restricted_payload(
        self,
        stage: str,
        visible_text: str,
        previous_state,
        extras: Optional[Dict] = None
    ) -> Dict:
        """The only user payload the model is allowed to see."""
        payload = {
            "stage": stage,
            "visible_text": visible_text,
            "previous_state": self._as_previous_state(previous_state),
        }
        payload.update(extras or {})
        return payload

    def _as_previous_state(self, previous_state):
        if previous_state is None:
            return None
        if isinstance(previous_state, dict):
            return {
                "translation": previous_state.get("translation") or "",
                "units": previous_state.get("units") or [],
                "revisions": previous_state.get("revisions") or [],
                "ambiguities": previous_state.get("ambiguities") or [],
            }
        text = str(previous_state).strip()
        if not text:
            return None
        return {
            "translation": text,
            "units": [],
            "revisions": [],
            "ambiguities": [],
        }

    def request_translation_state(
        self,
        prompt: str,
        payload: Dict,
        schema: Dict = None,
        schema_name: str = "translation_state",
        temperature: float = 0.4
    ) -> Dict:
        """Send the three-layer request and return the structured state."""
        user_payload = json.dumps(payload, ensure_ascii=False)
        self.last_exchange = {
            "kind": payload.get("stage"),
            "returning": False,
            "system": GLOBAL_TRANSLATION_INSTRUCTIONS,
            "developer": prompt,
            "user": user_payload,
            "response": None,
            "error": None,
        }
        parsed = self.send_layered_request(
            prompt,
            user_payload,
            schema=schema,
            schema_name=schema_name,
            temperature=temperature,
        )
        return parsed

    def send_layered_request(
        self,
        stage_prompt: str,
        user_payload: str,
        schema: Dict = None,
        schema_name: str = "translation_state",
        temperature: float = 0.4
    ) -> Dict:
        messages = [
            {"role": "system", "content": GLOBAL_TRANSLATION_INSTRUCTIONS},
            {"role": "developer", "content": stage_prompt},
            {"role": "user", "content": user_payload},
        ]
        try:
            return self._complete_json(messages, schema, schema_name, temperature)
        except OpenAIError:
            messages[1] = {"role": "system", "content": stage_prompt}
            return self._complete_json(messages, schema, schema_name, temperature)

    def _complete_json(
        self,
        messages: List[Dict],
        schema: Dict = None,
        schema_name: str = "translation_state",
        temperature: float = 0.4
    ) -> Dict:
        response_text = None
        try:
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=2000,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": schema_name,
                            "strict": True,
                            "schema": schema or TRANSLATION_STATE_SCHEMA,
                        },
                    },
                )
            except OpenAIError:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=2000,
                    response_format={"type": "json_object"},
                )

            response_text = response.choices[0].message.content.strip()
            if self.last_exchange is not None:
                self.last_exchange["response"] = response_text
            parsed_json = json.loads(response_text)
            tokens_used = response.usage.total_tokens if response.usage else 0
            if config.VERBOSE_LOGGING:
                print(f"✓ OpenAI request successful - Tokens used: {tokens_used}")
            parsed_json["tokens_used"] = tokens_used
            return parsed_json

        except json.JSONDecodeError as error:
            print(f"✗ Failed to parse OpenAI response as JSON: {error}")
            if self.last_exchange is not None:
                self.last_exchange["error"] = str(error)
                self.last_exchange["response"] = response_text
            raise ValueError(f"Invalid JSON response from OpenAI: {error}")
        except OpenAIError as error:
            print(f"✗ OpenAI API error: {error}")
            if self.last_exchange is not None:
                self.last_exchange["error"] = str(error)
            raise
        except Exception as error:
            print(f"✗ Unexpected error in OpenAI request: {error}")
            if self.last_exchange is not None:
                self.last_exchange["error"] = str(error)
            raise

    def word_response_from_state(self, state: Dict, source_word: str) -> Dict:
        units = [unit for unit in (state.get("units") or []) if isinstance(unit, dict)]
        unit = units[0] if units else {}
        primary = (
            (unit.get("translation") or state.get("translation") or source_word)
        )
        synonyms = list(unit.get("alternatives") or [])
        for extra in state.get("ambiguities") or []:
            if isinstance(extra, dict):
                synonyms.extend(extra.get("possibilities") or [])
        primary = clean_word_output(primary) or source_word
        seen = {self._norm(primary)}
        unique = []
        for synonym in synonyms:
            cleaned = clean_word_output(synonym)
            key = self._norm(cleaned)
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(cleaned)
            if len(unique) >= config.MAX_SYNONYMS_PER_WORD:
                break
        return {
            "primary_translation": primary,
            "synonyms": unique,
            "part_of_speech": "other",
            "tokens_used": state.get("tokens_used"),
        }

    def block_response_from_state(
        self,
        state: Dict,
        fallback_lines: List[str]
    ) -> Dict:
        translation = str(state.get("translation") or "").strip()
        if not translation and fallback_lines:
            translation = "\n".join(fallback_lines)
        lines = translation.split("\n") if translation else list(fallback_lines or [])
        previous = "\n".join(fallback_lines or [])
        revisions = [
            revision for revision in (state.get("revisions") or [])
            if isinstance(revision, dict)
        ]
        same_reading = self._norm(translation) == self._norm(previous)
        reorder = (not same_reading) and self._same_tokens(translation, previous)
        caused_by = ""
        if revisions:
            caused_by = str(revisions[0].get("caused_by") or "").strip()
        defect = self.defect_from_caused_by(
            caused_by,
            unchanged=same_reading,
            reorder=reorder,
        )
        # A new wording with no linguistic cause is preference. Do not place it.
        unchanged = same_reading or defect == "none"
        if reorder and defect == "word_order":
            unchanged = False
        return {
            "lines": lines,
            "drafts": [],
            # The model's own segmentation of this span, which is what the
            # page places. Falling back to the whole reading keeps a span
            # readable when the model answered without segmenting.
            "segments": [
                str(unit.get("translation") or "").strip()
                for unit in (state.get("units") or [])
                if isinstance(unit, dict) and str(unit.get("translation") or "").strip()
            ] or ([translation] if translation else []),
            "unchanged": unchanged,
            "improvement": caused_by or (
                "word order" if reorder else ("already good" if unchanged else "context")
            ),
            "defect": defect,
            "units": [unit for unit in (state.get("units") or []) if isinstance(unit, dict)],
            "revisions": revisions,
            "ambiguities": [
                item for item in (state.get("ambiguities") or []) if isinstance(item, dict)
            ],
            "translation_state": {
                "translation": translation,
                "units": [unit for unit in (state.get("units") or []) if isinstance(unit, dict)],
                "revisions": revisions,
                "ambiguities": [
                    item for item in (state.get("ambiguities") or []) if isinstance(item, dict)
                ],
            },
            "tokens_used": state.get("tokens_used"),
        }

    def defect_from_caused_by(
        self,
        caused_by: str,
        unchanged: bool = False,
        reorder: bool = False
    ) -> str:
        if unchanged:
            return "none"
        lowered = (caused_by or "").strip().casefold()
        if not lowered:
            return "word_order" if reorder else "none"
        if any(token in lowered for token in ("more poetic", "smoother", "elegant", "prefer")):
            return "none"
        if "order" in lowered or "syntax" in lowered:
            return "word_order"
        if "grammar" in lowered:
            return "grammar"
        if "crib" in lowered:
            return "crib"
        if "image" in lowered or "drop" in lowered:
            return "dropped_image"
        if "sense" in lowered or "meaning" in lowered:
            return "wrong_sense"
        return "closer_to_original"

    def strip_synonyms_from_function_words(
        self,
        response: Dict,
        source_word: str = None
    ) -> Dict:
        part_of_speech = str(response.get("part_of_speech", "")).strip().lower()
        stem = (source_word or "").strip().strip("¿¡.,;:?!\"'").casefold()
        is_function = (
            part_of_speech in FUNCTION_WORD_PARTS_OF_SPEECH
            or stem in SOURCE_FUNCTION_WORDS
        )
        if is_function and response.get("synonyms"):
            if config.VERBOSE_LOGGING:
                print(
                    f"  · Dropped {len(response['synonyms'])} synonym(s) offered "
                    f"for a function word"
                )
            response["synonyms"] = []
        return response

    def tag_last_exchange(self, kind: str = None, returning: bool = False) -> None:
        if not self.last_exchange:
            self.last_exchange = {}
        self.last_exchange["kind"] = kind
        self.last_exchange["returning"] = returning

    def clear_last_exchange(self) -> None:
        self.last_exchange = None

    def _norm(self, text: str) -> str:
        return " ".join((text or "").casefold().split())

    def _same_tokens(self, left: str, right: str) -> bool:
        return sorted(self._norm(left).split()) == sorted(self._norm(right).split())

    def send_message_to_openai_and_parse_json(
        self,
        prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 500,
        system_prompt: str = None
    ) -> Dict:
        """Compatibility wrapper used by tests that stub the old single-prompt call."""
        return self.send_layered_request(
            system_prompt or GLOBAL_TRANSLATION_INSTRUCTIONS,
            prompt,
        )

    def validate_word_translation_response(self, response: Dict) -> bool:
        required_fields = ["primary_translation", "synonyms"]
        if not all(field in response for field in required_fields):
            print(f"✗ Response missing required fields: {required_fields}")
            return False
        if not isinstance(response["synonyms"], list):
            print("✗ Synonyms must be a list")
            return False
        if len(response["synonyms"]) > config.MAX_SYNONYMS_PER_WORD:
            print(
                f"✗ Too many synonyms: {len(response['synonyms'])} > "
                f"{config.MAX_SYNONYMS_PER_WORD}"
            )
            return False
        return True

    def validate_block_translation_response(self, response: Dict) -> bool:
        if "lines" not in response:
            print("✗ Response missing required field: lines")
            return False
        if not isinstance(response["lines"], list):
            print("✗ Lines must be a list")
            return False
        if not any(isinstance(line, str) and line.strip() for line in response["lines"]):
            print("✗ Lines contained no text")
            return False
        return True
