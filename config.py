"""
Configuration settings for Poetry Transformer
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent

# Load .env here rather than in a launcher script so every entry point behaves
# the same. Real environment variables win over the file, letting systemd or CI
# override it.
load_dotenv(BASE_DIR / ".env")

# ============================================================================
# API CONFIGURATION
# ============================================================================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")  # or "gpt-3.5-turbo" for cost efficiency


def validate_required_settings() -> None:
    """
    Check that required configuration is present

    Called at process start so a missing key fails immediately with a clear
    message, rather than surfacing later as an opaque 401 from OpenAI on the
    first translation.

    Raises:
        RuntimeError: If a required setting is missing
    """
    if not OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and add your key."
        )

# ============================================================================
# LANGUAGE CONFIGURATION
# ============================================================================

SOURCE_LANGUAGE = "Spanish"
SOURCE_LANGUAGE_CODE = "es"

TARGET_LANGUAGE = "English"
TARGET_LANGUAGE_CODE = "en"

# Languages offered when adding a poem. The name is what goes into the OpenAI
# prompt and the code is what keys the translation cache, so a name and code
# must always travel together as a pair.
SUPPORTED_SOURCE_LANGUAGES = [
    {"name": "Spanish", "code": "es"},
    {"name": "French", "code": "fr"},
    {"name": "Italian", "code": "it"},
    {"name": "Portuguese", "code": "pt"},
    {"name": "Catalan", "code": "ca"},
    {"name": "German", "code": "de"},
    {"name": "Dutch", "code": "nl"},
    {"name": "Latin", "code": "la"},
    {"name": "Ancient Greek", "code": "grc"},
    {"name": "Russian", "code": "ru"},
    {"name": "Arabic", "code": "ar"},
    {"name": "Japanese", "code": "ja"},
    {"name": "Chinese", "code": "zh"},
    {"name": "English", "code": "en"},
]

# Only one target today, but kept as a list so additional targets can be added
# without reshaping the API, the poems table, or the UI.
SUPPORTED_TARGET_LANGUAGES = [
    {"name": "English", "code": "en"},
]

# ============================================================================
# POEM CONFIGURATION
# ============================================================================

# Fallback used only when no poem has been saved through the web UI
POEM_FILE_PATH = BASE_DIR / "poem.txt"

# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================

DATABASE_FILE_PATH = BASE_DIR / "poetry_transformer.db"
DATABASE_ENABLE_LOGGING = False  # Set to True for debugging

# Output database for detailed translation events (same DB used by manager)
# ============================================================================

# ============================================================================
# SENSOR CONFIGURATION
# ============================================================================

# GPIO pin for motion sensor (BCM numbering)
MOTION_SENSOR_GPIO_PIN = 17

# Debounce time in seconds to prevent multiple triggers
MOTION_SENSOR_DEBOUNCE_SECONDS = 0.5

# ============================================================================
# TRANSLATION CACHING CONFIGURATION
# ============================================================================

# Maximum number of synonyms to retrieve per word
MAX_SYNONYMS_PER_WORD = 7

# ============================================================================
# DISPLAY/OUTPUT CONFIGURATION
# ============================================================================

# Output modes: "console", "file", "custom"
DISPLAY_OUTPUT_MODE = "console"

# File path for file output mode
DISPLAY_OUTPUT_FILE_PATH = BASE_DIR / "output" / "transformed_poem.txt"

# Streaming JSONL output for animation / installation
STREAM_OUTPUT_JSONL_PATH = BASE_DIR / "output" / "translation_stream.jsonl"

# ============================================================================
# TRANSFORMATION PHASE CONFIGURATION
# ============================================================================

# Short blocks of this many words, staying inside a line. A trigger after
# Phase 1 picks among these, whole lines, and stanzas; nothing is booked in
# advance, so the target is not a countdown.
BLOCK_GROWTH_WORD_SIZES = [2, 3]

# Stage 3 asks for several complete readings of the poem in one call and
# shows them worst first. Five attempts written to settle on one right
# answer come back nearly identical, so this stage runs warmer than the
# others, where a single accurate reading is what is wanted.
VARIATION_TEMPERATURE = 0.95

# Every pass over a block is asked to improve how the poem currently reads,
# not to translate the source afresh, so its answer depends on the state of the
# poem at that moment. A cached answer would be an answer to a different
# question, which is why the phrase cache is off. Turning it on trades honesty
# for a lower bill.
CACHE_BLOCK_TRANSLATIONS = False

# Word lookups are just as state-sensitive: a cached "it's" for "es" will keep
# coming back. Fresh calls keep the page from repeating a bad saved rendering.
CACHE_WORD_TRANSLATIONS = False

# Set to an integer to replay the same random order every run, which is useful
# when comparing two prompt versions on the same poem. Unset means a fresh
# order each time the poem is loaded.
_transformation_random_seed = os.getenv("TRANSFORMATION_RANDOM_SEED")
TRANSFORMATION_RANDOM_SEED = (
    int(_transformation_random_seed) if _transformation_random_seed else None
)

# ============================================================================
# DEBUG CONFIGURATION
# ============================================================================

DEBUG_MODE = True
VERBOSE_LOGGING = True
