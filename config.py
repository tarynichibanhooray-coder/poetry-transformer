"""
Configuration settings for Poetry Transformer
"""

import os
from pathlib import Path

# ============================================================================
# API CONFIGURATION
# ============================================================================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your-api-key-here")
OPENAI_MODEL = "gpt-4o"  # or "gpt-3.5-turbo" for cost efficiency

# ============================================================================
# LANGUAGE CONFIGURATION
# ============================================================================

SOURCE_LANGUAGE = "Spanish"
SOURCE_LANGUAGE_CODE = "es"

TARGET_LANGUAGE = "English"
TARGET_LANGUAGE_CODE = "en"

# ============================================================================
# POEM CONFIGURATION
# ============================================================================

POEM_FILE_PATH = Path(__file__).parent / "poems" / "test_poem.txt"

# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================

DATABASE_FILE_PATH = Path(__file__).parent / "poetry_transformer.db"
DATABASE_ENABLE_LOGGING = False  # Set to True for debugging

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
DISPLAY_OUTPUT_FILE_PATH = Path(__file__).parent / "output" / "transformed_poem.txt"

# ============================================================================
# TRANSFORMATION PHASE CONFIGURATION
# ============================================================================

# Phase durations (number of sensor triggers per phase)
PHASE_1_WORD_BY_WORD_TRIGGERS = None  # None = all words
PHASE_2_PAIR_TRIGGERS = None  # None = all pairs
PHASE_3_PHRASE_TRIGGERS = None  # None = all phrases

# ============================================================================
# DEBUG CONFIGURATION
# ============================================================================

DEBUG_MODE = True
VERBOSE_LOGGING = True
