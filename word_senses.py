"""Lookalike guard for stage 1, and the anchor that brings a word home.

A word shown alone is meant to be ambiguous, so every real sense of it is
welcome: rosa is rose and also pink. What is never welcome is a word that
merely resembles the spelling. sol is the sun; sole and soil are accidents
of orthography and belong to no reading of the poem.

So this file rejects lookalikes and nothing else. It does not decide which
senses a word is allowed to have.

The one exception is a word on the return journey. Going out, rosa becoming
rose is a discovery. Coming back, rose is not ambiguous at all: it reached
the page by way of rosa, and reading it as the past tense of rise would be
the poem forgetting its own passage. So a word with a known origin is
anchored to that origin here rather than left to the model.
"""

import re
from typing import Dict, Iterable, List, Tuple

WORD_CHARS = re.compile(r"[^\w]+", re.UNICODE)

# English the model offers because it looks or sounds like the source word.
REJECTED_GLOSSES = {
    "sol": {"sole", "soil", "sold", "soul", "solo"},
    "fuego": {"glow"},
    "o": {"oh", "o"},
    "su": {"on", "so", "sue"},
    "es": {"it's", "this"},
    "está": {"exists", "it's"},
    "dime": {"dime", "dim"},
    "ese": {"ese", "easy"},
    "rosa": {"rosy"},
}

# Used only when the model's own answer was empty or was a lookalike.
FALLBACK_PRIMARY = {
    "o": "or",
    "su": "its",
    "sus": "their",
    "es": "is",
    "está": "is",
    "el": "the",
    "la": "the",
    "los": "the",
    "las": "the",
    "de": "of",
    "y": "and",
    "un": "a",
    "una": "a",
    "tiene": "has",
    "ayer": "yesterday",
    "sol": "sun",
    "fuego": "fire",
    "dime": "tell me",
    "ese": "that",
    "rosa": "rose",
}


def source_stem(word: str) -> str:
    return WORD_CHARS.sub("", word or "").casefold()


def gloss_stem(word: str) -> str:
    return source_stem(word)


def tether_isolated_word(
    source_word: str,
    primary: str,
    synonyms: Iterable[str] = None,
) -> Tuple[str, List[str]]:
    """Drop lookalikes. Leave every genuine sense alone."""
    stem = source_stem(source_word)
    rejected = REJECTED_GLOSSES.get(stem, set())
    fallback = FALLBACK_PRIMARY.get(stem)

    primary = (primary or "").strip()
    if not primary or gloss_stem(primary) in rejected:
        primary = fallback or primary or source_word

    kept: List[str] = []
    seen = {gloss_stem(primary)}
    for synonym in synonyms or []:
        text = (synonym or "").strip()
        key = gloss_stem(text)
        if not key or key in seen or key in rejected:
            continue
        seen.add(key)
        kept.append(text)

    return primary, kept


def anchor_word_to_origin(response: Dict, origin_word: str) -> Dict:
    """Settle a returning word on the word it was translated from.

    The model still supplies the alternatives that flicker before the word
    settles, because senses of the flower are still worth passing through.
    What it does not get to decide is the reading left standing, which is
    the origin itself. Deciding that here rather than asking for it is what
    keeps subió off the page under a rose.
    """
    origin = (origin_word or '').strip()
    if not origin:
        return response

    kept: List[str] = []
    seen = {gloss_stem(origin)}
    for synonym in response.get("synonyms") or []:
        text = (synonym or "").strip()
        key = gloss_stem(text)
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(text)

    response["primary_translation"] = origin
    response["target_word"] = origin
    response["synonyms"] = kept
    return response


def tether_word_response(response: Dict, source_word: str) -> Dict:
    primary, synonyms = tether_isolated_word(
        source_word,
        response.get("primary_translation") or response.get("target_word") or "",
        response.get("synonyms") or [],
    )
    response["primary_translation"] = primary
    response["target_word"] = primary
    response["synonyms"] = synonyms
    return response
