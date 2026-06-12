# Poetry Transformer

A Raspberry Pi installation that transforms poems word-by-word into target languages using AI, with intelligent caching and multi-phase translation visualization.

## Overview

Poetry Transformer is an interactive art installation that gradually transforms a poem from its original language to a target language through sensor triggers. Each trigger advances the transformation:

1. **Phase 1 (Word-by-Word)**: Words are replaced one at a time with synonyms cycling through up to 7 options
2. **Phase 2 (Pairs)**: Two-word phrases begin to transform together
3. **Phase 3 (Phrases Growing)**: Larger phrases transform until the entire poem reaches the target language

All translations are cached in SQLite to avoid redundant API calls, making the installation efficient and responsive.

## Features

- ✅ Motion sensor support (flexible for any trigger type)
- ✅ OpenAI GPT-4 integration for high-quality translations
- ✅ SQLite caching database for all translations
- ✅ Maximum 7 synonyms per word with cycling
- ✅ Multi-phase transformation logic
- ✅ Flexible output rendering (console, file, screen-ready)
- ✅ Clear, descriptive function naming throughout
- ✅ Raspberry Pi optimized

## Architecture

```
poetry_transformer/
├── config.py                      # Configuration and settings
├── database_manager.py            # SQLite cache operations
├── openai_translator.py           # OpenAI integration
├── motion_sensor_handler.py       # Sensor trigger logic
├── poem_transformer_engine.py     # Core transformation logic
├── display_renderer.py            # Output rendering
├── main.py                        # Application entry point
├── requirements.txt               # Dependencies
└── poems/
    └── sample_poem.txt            # Example poem
```

## Requirements

- Python 3.8+
- Raspberry Pi (or any Linux system with GPIO support)
- SQLite3
- OpenAI API key

## Installation

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Configure your settings in `config.py`
4. Connect motion sensor to GPIO pins
5. Run: `python main.py`

## Configuration

Edit `config.py` to set:
- OpenAI API key
- Source and target languages
- GPIO pin for motion sensor
- Debounce timing
- Poem file path

## Usage

Place a poem file in the `poems/` directory and update the config. The installation will:
1. Load the poem on startup
2. Listen for motion sensor triggers
3. Advance the transformation with each trigger
4. Display the gradually transforming poem

## Database Schema

The SQLite database stores:
- **word_cache**: Individual words with their synonyms
- **phrase_cache**: Multi-word phrases and their translations
- **translation_history**: Metadata about all translations performed

## Output

The display can be rendered to:
- Console (for testing)
- Text file (for processing)
- Custom format (for screen projection)

## License

MIT License

## Author

Created by tarynichibanhooray-coder
