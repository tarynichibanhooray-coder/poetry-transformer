"""
Database Manager for Poetry Transformer
Handles all SQLite operations for caching translations and synonyms
"""

import sqlite3
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from datetime import datetime
import json

import config


class DatabaseManager:
    """Manages SQLite database operations for translation caching"""

    def __init__(self, database_path: Path = None):
        """
        Initialize database connection and create tables if needed
        
        Args:
            database_path: Path to SQLite database file
        """
        self.database_path = database_path or config.DATABASE_FILE_PATH
        self.connection = None
        self.cursor = None
        self.initialize_database_connection()
        self.create_all_required_tables()

    def initialize_database_connection(self) -> None:
        """Establish connection to SQLite database and configure pragmas"""
        try:
            # Use a connection that is safe for use across threads in this process
            # and enable reasonable pragmas for concurrency (WAL) and durability.
            # We set a timeout so transient locks retry for a short time.
            self.connection = sqlite3.connect(
                str(self.database_path),
                detect_types=sqlite3.PARSE_DECLTYPES,
                check_same_thread=False,
                timeout=30.0,
            )
            self.connection.row_factory = sqlite3.Row
            self.cursor = self.connection.cursor()

            # Enable WAL and other pragmatic settings to reduce reader/writer contention.
            try:
                self.cursor.execute("PRAGMA journal_mode=WAL;")
                self.cursor.execute("PRAGMA synchronous=NORMAL;")
                # Set an automatic checkpoint interval (in pages). Tune if needed.
                self.cursor.execute("PRAGMA wal_autocheckpoint=100;")
                # SQLite ignores foreign keys unless they are switched on for
                # each connection. Without this the ON DELETE CASCADE on a
                # poem's readings is only a comment, and deleting a poem would
                # leave its readings behind with nothing to reach them by.
                self.cursor.execute("PRAGMA foreign_keys=ON;")
                if config.DEBUG_MODE:
                    print("✓ Enabled WAL journal_mode and pragmas for SQLite")
            except Exception as e:
                # Non-fatal: if the platform doesn't support WAL (network FS) we'll continue
                print(f"✗ Warning: failed to set WAL pragmas: {e}")

            if config.DEBUG_MODE:
                print(f"✓ Database connection established: {self.database_path}")
        except sqlite3.Error as error:
            print(f"✗ Database connection failed: {error}")
            raise

    def create_all_required_tables(self) -> None:
        """Create all necessary tables for the application"""
        self.create_word_cache_table()
        self.create_phrase_cache_table()
        self.create_translation_history_table()
        # Create poems table for persisted poem management (added here to ensure schema exists)
        self.create_poems_table()
        self.create_poem_iterations_table()
        self.commit_database_changes()

    def create_word_cache_table(self) -> None:
        """
        Create table for storing individual word translations and synonyms
        
        Columns:
            id: Unique identifier
            source_word: Original word in source language
            target_word: Primary translation in target language
            synonyms_json: JSON array of up to 7 synonyms
            context_line: Line of poetry the translation was chosen for
            arriving_at: Finished translation the poem was heading for, if any
            source_language: Language code of source
            target_language: Language code of target
            created_at: Timestamp of creation
            last_accessed_at: Timestamp of last usage
        """
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS word_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_word TEXT NOT NULL,
            target_word TEXT NOT NULL,
            synonyms_json TEXT NOT NULL,
            context_line TEXT NOT NULL DEFAULT '',
            arriving_at TEXT NOT NULL DEFAULT '',
            source_language TEXT NOT NULL,
            target_language TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_word, source_language, target_language, context_line, arriving_at)
        );
        """
        self.cursor.execute(create_table_sql)
        self.migrate_word_cache_to_context_keys()

    def migrate_word_cache_to_context_keys(self) -> None:
        """
        Rebuild a word cache that was keyed on too little

        Which word a poem should keep depends on the line it sits in and on the
        ending the poem is heading for, so both belong in the key: otherwise the
        first choice ever made answers for every later poem, and editing a
        poem's chosen ending leaves the old choices in place. SQLite cannot
        alter a constraint after the fact, and the rows under the old key are
        the ones this change exists to stop trusting, so the table is rebuilt
        empty.
        """
        self.cursor.execute("PRAGMA table_info(word_cache)")
        columns = {row['name'] for row in self.cursor.fetchall()}

        if {'context_line', 'arriving_at'} <= columns:
            return

        if config.DEBUG_MODE:
            print("✓ Rebuilding word_cache to key choices by poem and context")

        self.cursor.execute("DROP TABLE word_cache")
        self.create_word_cache_table()

    def create_phrase_cache_table(self) -> None:
        """
        Create table for storing multi-word phrase translations
        
        Columns:
            id: Unique identifier
            source_phrase: Original phrase in source language
            target_phrase: Translation in target language
            phrase_word_count: Number of words in phrase
            translation_mode: How much licence the translation took
            source_language: Language code of source
            target_language: Language code of target
            created_at: Timestamp of creation
            last_accessed_at: Timestamp of last usage
        """
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS phrase_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_phrase TEXT NOT NULL,
            target_phrase TEXT NOT NULL,
            phrase_word_count INTEGER NOT NULL,
            translation_mode TEXT NOT NULL DEFAULT 'literal',
            source_language TEXT NOT NULL,
            target_language TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_phrase, source_language, target_language, translation_mode)
        );
        """
        self.cursor.execute(create_table_sql)
        self.migrate_phrase_cache_to_translation_modes()

    def migrate_phrase_cache_to_translation_modes(self) -> None:
        """
        Rebuild a phrase cache created before translations had modes

        The same text is now translated differently depending on the pass
        asking for it, so the mode belongs in the unique key. SQLite cannot
        alter a constraint in place, and rows from the older single-mode prompt
        would answer for every mode, so the table is rebuilt empty. The cache
        is only a cost saver; discarded rows are fetched again on demand.
        """
        self.cursor.execute("PRAGMA table_info(phrase_cache)")
        columns = [row['name'] for row in self.cursor.fetchall()]

        if 'translation_mode' in columns:
            return

        if config.DEBUG_MODE:
            print("✓ Rebuilding phrase_cache to key translations by mode")

        self.cursor.execute("DROP TABLE phrase_cache")
        self.create_phrase_cache_table()

    def create_translation_history_table(self) -> None:
        """
        Create table for tracking all translation requests made to AI
        
        Columns:
            id: Unique identifier
            request_type: 'word' or 'phrase'
            source_text: Text that was translated
            target_text: Resulting translation
            tokens_used: Total tokens consumed from API
            source_language: Language code of source
            target_language: Language code of target
            timestamp: When the request was made
        """
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS translation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_type TEXT NOT NULL,
            source_text TEXT NOT NULL,
            target_text TEXT NOT NULL,
            tokens_used INTEGER,
            source_language TEXT NOT NULL,
            target_language TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        self.cursor.execute(create_table_sql)

    def create_poems_table(self) -> None:
        """Create table for storing uploaded poems and metadata"""
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS poems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            source_language TEXT,
            source_language_code TEXT,
            target_language TEXT,
            target_language_code TEXT,
            raw_text TEXT NOT NULL,
            lines_json TEXT,
            stanza_delimiter TEXT,
            final_translation TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        self.cursor.execute(create_table_sql)
        self.migrate_poems_table_to_final_translation()
        self.migrate_poems_table_to_active_flag()

    def migrate_poems_table_to_final_translation(self) -> None:
        """
        Add the chosen final translation to a poems table created without it

        Adding a nullable column keeps every existing poem, which simply has no
        destination text and falls back to a translation written on the night.
        """
        self.cursor.execute("PRAGMA table_info(poems)")
        columns = [row['name'] for row in self.cursor.fetchall()]

        if 'final_translation' in columns:
            return

        if config.DEBUG_MODE:
            print("✓ Adding final_translation to the poems table")

        self.cursor.execute("ALTER TABLE poems ADD COLUMN final_translation TEXT")

    def migrate_poems_table_to_active_flag(self) -> None:
        """
        Add the active flag to a poems table created without it

        Every poem that already exists was in the rotation before the flag
        was invented, so the column defaults to active and nothing quietly
        disappears from the wall the first time the server restarts.
        """
        self.cursor.execute("PRAGMA table_info(poems)")
        columns = [row['name'] for row in self.cursor.fetchall()]

        if 'active' in columns:
            return

        if config.DEBUG_MODE:
            print("✓ Adding active to the poems table")

        self.cursor.execute(
            "ALTER TABLE poems ADD COLUMN active INTEGER NOT NULL DEFAULT 1"
        )

    def create_poem_iterations_table(self) -> None:
        """
        Create the table that keeps every reading a poem has been given

        The stream in output/ is a log of a performance and is thrown away
        between runs. This table is the poem's own record: one row for every
        reading the model returned for it, and every reading typed by hand
        afterwards, so a poem can be read back and corrected later.

        Columns:
            poem_id: The poem the reading belongs to
            stage: 'words', 'phrases' or 'lines'
            journey: 'out' on the way to the target, 'home' coming back
            position: Order within the stage, in the order they arrived
            source_text: What was sent to be translated
            content: The reading that came back
            note: What the stage said it was doing, or what a variation holds
            alternatives_json: The other senses offered alongside the reading
            origin: 'api' for a model answer, 'hand' for one typed in
            edited: Whether a model answer has since been changed by hand
        """
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS poem_iterations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            poem_id INTEGER NOT NULL,
            stage TEXT NOT NULL,
            journey TEXT NOT NULL DEFAULT 'out',
            position INTEGER NOT NULL DEFAULT 0,
            source_text TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            alternatives_json TEXT NOT NULL DEFAULT '[]',
            origin TEXT NOT NULL DEFAULT 'api',
            edited INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (poem_id) REFERENCES poems(id) ON DELETE CASCADE
        );
        """
        self.cursor.execute(create_table_sql)
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS poem_iterations_by_poem "
            "ON poem_iterations (poem_id, stage, position)"
        )

    def record_poem_iteration(
        self,
        poem_id: int,
        stage: str,
        content: str,
        source_text: str = '',
        note: str = '',
        alternatives: List[str] = None,
        journey: str = 'out',
        origin: str = 'api'
    ) -> Optional[int]:
        """
        Add one reading to a poem's record

        A poem the engine was handed directly, with no library row behind it,
        has nothing to attach readings to. That is a normal way to run the
        engine in a test, so it is not an error; the reading is dropped.

        Returns:
            ID of the stored reading, or None if there was no poem to file it under
        """
        if not poem_id:
            return None

        content = (content or '').strip()
        if not content:
            return None

        insert_sql = """
        INSERT INTO poem_iterations
        (poem_id, stage, journey, position, source_text, content, note,
         alternatives_json, origin)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.cursor.execute(
            insert_sql,
            (
                poem_id,
                stage,
                journey,
                self.next_iteration_position(poem_id, stage),
                source_text or '',
                content,
                note or '',
                json.dumps(alternatives or [], ensure_ascii=False),
                origin,
            )
        )
        self.commit_database_changes()
        return self.cursor.lastrowid

    def next_iteration_position(self, poem_id: int, stage: str) -> int:
        """The next slot at the end of a stage's list."""
        self.cursor.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 AS next "
            "FROM poem_iterations WHERE poem_id = ? AND stage = ?",
            (poem_id, stage)
        )
        return self.cursor.fetchone()['next']

    def retrieve_poem_iterations(self, poem_id: int) -> List[Dict]:
        """Every reading recorded for a poem, in the order it arrived."""
        query = """
        SELECT id, poem_id, stage, journey, position, source_text, content,
               note, alternatives_json, origin, edited, created_at, updated_at
        FROM poem_iterations
        WHERE poem_id = ?
        ORDER BY stage, position, id
        """
        self.cursor.execute(query, (poem_id,))
        return [self._iteration_from_row(row) for row in self.cursor.fetchall()]

    def retrieve_poem_iteration_by_id(self, iteration_id: int) -> Optional[Dict]:
        query = """
        SELECT id, poem_id, stage, journey, position, source_text, content,
               note, alternatives_json, origin, edited, created_at, updated_at
        FROM poem_iterations
        WHERE id = ?
        """
        self.cursor.execute(query, (iteration_id,))
        row = self.cursor.fetchone()
        return self._iteration_from_row(row) if row else None

    def update_poem_iteration(
        self,
        iteration_id: int,
        content: str = None,
        note: str = None,
        source_text: str = None
    ) -> Optional[Dict]:
        """
        Change a recorded reading

        A model answer that has been corrected is marked as edited rather
        than relabelled as handwritten, so the record still shows that the
        model answered here and that the answer was not left standing.
        """
        existing = self.retrieve_poem_iteration_by_id(iteration_id)
        if not existing:
            return None

        content = existing['content'] if content is None else content.strip()
        if not content:
            return None

        was_edited = existing['edited'] or content != existing['content']

        self.cursor.execute(
            """
            UPDATE poem_iterations
            SET content = ?, note = ?, source_text = ?, edited = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                content,
                existing['note'] if note is None else note,
                existing['source_text'] if source_text is None else source_text,
                1 if was_edited and existing['origin'] == 'api' else existing['edited'],
                iteration_id,
            )
        )
        self.commit_database_changes()
        return self.retrieve_poem_iteration_by_id(iteration_id)

    def delete_poem_iteration(self, iteration_id: int) -> bool:
        self.cursor.execute(
            "DELETE FROM poem_iterations WHERE id = ?", (iteration_id,)
        )
        self.commit_database_changes()
        return self.cursor.rowcount > 0

    def count_poem_iterations_by_stage(self, poem_id: int) -> Dict[str, int]:
        """How many readings each stage has, for the library listing."""
        self.cursor.execute(
            "SELECT stage, COUNT(*) AS count FROM poem_iterations "
            "WHERE poem_id = ? GROUP BY stage",
            (poem_id,)
        )
        return {row['stage']: row['count'] for row in self.cursor.fetchall()}

    def _iteration_from_row(self, row) -> Dict:
        iteration = dict(row)
        try:
            iteration['alternatives'] = json.loads(
                iteration.pop('alternatives_json') or '[]'
            )
        except (ValueError, TypeError):
            iteration.pop('alternatives_json', None)
            iteration['alternatives'] = []
        iteration['edited'] = bool(iteration['edited'])
        return iteration

    def store_or_update_poem_entry(
        self,
        raw_text: str,
        source_language: str,
        source_language_code: str,
        target_language: str,
        target_language_code: str,
        title: str = None,
        stanza_delimiter: str = None,
        final_translation: str = None
    ) -> int:
        """
        Store a poem and the language pair it was entered with

        Re-saving the same text under the same language pair updates the
        existing row instead of adding a duplicate, so the poem list stays a
        library rather than a log of every load.

        Args:
            raw_text: Poem text with real line breaks
            source_language: Name of source language
            source_language_code: ISO code of source language
            target_language: Name of target language
            target_language_code: ISO code of target language
            title: Optional poem title
            stanza_delimiter: Delimiter the poem was entered with, if any
            final_translation: The translation the poem should end on, if the
                poem has a chosen one

        Returns:
            ID of the stored record
        """
        existing_query = """
        SELECT id FROM poems
        WHERE raw_text = ? AND source_language_code = ? AND target_language_code = ?
        """
        self.cursor.execute(
            existing_query, (raw_text, source_language_code, target_language_code)
        )
        existing_row = self.cursor.fetchone()

        if existing_row:
            update_sql = """
            UPDATE poems
            SET title = COALESCE(?, title),
                final_translation = COALESCE(?, final_translation),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """
            self.cursor.execute(
                update_sql, (title, final_translation, existing_row['id'])
            )
            self.commit_database_changes()
            return existing_row['id']

        lines_json = json.dumps(raw_text.split('\n'), ensure_ascii=False)

        insert_sql = """
        INSERT INTO poems
        (title, source_language, source_language_code, target_language,
         target_language_code, raw_text, lines_json, stanza_delimiter,
         final_translation)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.cursor.execute(
            insert_sql,
            (
                title,
                source_language,
                source_language_code,
                target_language,
                target_language_code,
                raw_text,
                lines_json,
                stanza_delimiter,
                final_translation
            )
        )
        self.commit_database_changes()
        return self.cursor.lastrowid

    def retrieve_all_poem_entries(self) -> List[Dict]:
        """
        Retrieve every stored poem, newest first

        Returns:
            List of poem dictionaries
        """
        query = """
        SELECT id, title, source_language, source_language_code, target_language,
               target_language_code, raw_text, final_translation, active, created_at
        FROM poems
        ORDER BY id DESC
        """
        self.cursor.execute(query)
        return [self._poem_from_row(row) for row in self.cursor.fetchall()]

    def retrieve_active_poem_entries(self) -> List[Dict]:
        """
        The poems the installation is allowed to put on the wall

        A poem is taken out of the rotation by turning it off rather than by
        deleting it, so the record of how it was translated survives being
        retired from the wall.
        """
        query = """
        SELECT id, title, source_language, source_language_code, target_language,
               target_language_code, raw_text, final_translation, active, created_at
        FROM poems
        WHERE active = 1
        ORDER BY id DESC
        """
        self.cursor.execute(query)
        return [self._poem_from_row(row) for row in self.cursor.fetchall()]

    def retrieve_poem_entry_by_id(self, poem_id: int) -> Optional[Dict]:
        """
        Retrieve a single stored poem

        Args:
            poem_id: ID of the poem to look up

        Returns:
            Poem dictionary, or None if no poem has that ID
        """
        query = """
        SELECT id, title, source_language, source_language_code, target_language,
               target_language_code, raw_text, final_translation, active, created_at
        FROM poems
        WHERE id = ?
        """
        self.cursor.execute(query, (poem_id,))
        row = self.cursor.fetchone()
        return self._poem_from_row(row) if row else None

    def set_poem_active(self, poem_id: int, active: bool) -> Optional[Dict]:
        """
        Put a poem into the rotation or take it out

        Returns:
            The poem as it now stands, or None if no poem has that ID
        """
        self.cursor.execute(
            "UPDATE poems SET active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (1 if active else 0, poem_id)
        )
        self.commit_database_changes()
        return self.retrieve_poem_entry_by_id(poem_id)

    def delete_poem_entry(self, poem_id: int) -> bool:
        """
        Remove a poem and everything recorded about it

        The readings go with it, by way of the cascade declared on
        poem_iterations. This is the destructive option; turning a poem off
        is the one that keeps its record.

        Returns:
            True if a poem was removed
        """
        self.cursor.execute("DELETE FROM poems WHERE id = ?", (poem_id,))
        removed = self.cursor.rowcount > 0
        self.commit_database_changes()
        return removed

    def _poem_from_row(self, row) -> Dict:
        poem = dict(row)
        if 'active' in poem:
            poem['active'] = bool(poem['active'])
        return poem

    def commit_database_changes(self) -> None:
        """Commit all pending database changes"""
        try:
            self.connection.commit()
            if config.VERBOSE_LOGGING:
                print("✓ Database changes committed")
        except sqlite3.Error as error:
            print(f"✗ Commit failed: {error}")
            raise

    def close_database_connection(self) -> None:
        """Close the database connection gracefully"""
        if self.connection:
            self.connection.close()
            if config.DEBUG_MODE:
                print("✓ Database connection closed")

    def retrieve_cached_word_translation(
        self,
        source_word: str,
        source_language: str,
        target_language: str,
        context_line: str = '',
        arriving_at: str = ''
    ) -> Optional[Dict]:
        """
        Retrieve a cached word translation from database
        
        Args:
            source_word: Original word to look up
            source_language: Language code of source
            target_language: Language code of target
            context_line: Line the word appears in. The same word in another
                line is another translation, so it is part of the key.
            arriving_at: Finished translation the poem is heading for, which
                the choice was made in the light of
            
        Returns:
            Dictionary with word data or None if not found
        """
        query = """
        SELECT id, source_word, target_word, synonyms_json, context_line, created_at
        FROM word_cache
        WHERE source_word = ? AND source_language = ? AND target_language = ?
              AND context_line = ? AND arriving_at = ?
        """
        self.cursor.execute(
            query,
            (
                source_word,
                source_language,
                target_language,
                context_line or '',
                arriving_at or ''
            )
        )
        row = self.cursor.fetchone()
        
        if row:
            self.update_word_cache_last_accessed_timestamp(row['id'])
            return {
                'id': row['id'],
                'source_word': row['source_word'],
                'target_word': row['target_word'],
                'synonyms': json.loads(row['synonyms_json']),
                'context_line': row['context_line'],
                'created_at': row['created_at']
            }
        return None

    def store_new_word_translation_with_synonyms(
        self,
        source_word: str,
        target_word: str,
        synonyms: List[str],
        source_language: str,
        target_language: str,
        context_line: str = '',
        arriving_at: str = ''
    ) -> int:
        """
        Store a new word translation with synonyms in database
        
        Args:
            source_word: Original word
            target_word: Primary translation
            synonyms: List of up to 7 synonyms
            source_language: Language code of source
            target_language: Language code of target
            context_line: Line the translation was chosen for
            arriving_at: Finished translation the poem is heading for
            
        Returns:
            ID of inserted record
        """
        # Ensure we don't exceed 7 synonyms
        limited_synonyms = synonyms[:config.MAX_SYNONYMS_PER_WORD]
        synonyms_json = json.dumps(limited_synonyms)
        
        insert_sql = """
        INSERT OR IGNORE INTO word_cache
        (source_word, target_word, synonyms_json, context_line, arriving_at,
         source_language, target_language)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        self.cursor.execute(
            insert_sql,
            (
                source_word,
                target_word,
                synonyms_json,
                context_line or '',
                arriving_at or '',
                source_language,
                target_language
            )
        )
        self.commit_database_changes()
        return self.cursor.lastrowid

    def retrieve_cached_phrase_translation(
        self,
        source_phrase: str,
        source_language: str,
        target_language: str,
        translation_mode: str = 'literal'
    ) -> Optional[Dict]:
        """
        Retrieve a cached phrase translation from database
        
        Args:
            source_phrase: Original phrase to look up
            source_language: Language code of source
            target_language: Language code of target
            translation_mode: The pass that asked for it. A line translated
                literally and the same line translated as poetry are different
                translations and must not answer for each other.
            
        Returns:
            Dictionary with phrase data or None if not found
        """
        query = """
        SELECT id, source_phrase, target_phrase, phrase_word_count, translation_mode, created_at
        FROM phrase_cache
        WHERE source_phrase = ? AND source_language = ? AND target_language = ?
              AND translation_mode = ?
        """
        self.cursor.execute(
            query,
            (source_phrase, source_language, target_language, translation_mode)
        )
        row = self.cursor.fetchone()
        
        if row:
            self.update_phrase_cache_last_accessed_timestamp(row['id'])
            return {
                'id': row['id'],
                'source_phrase': row['source_phrase'],
                'target_phrase': row['target_phrase'],
                'phrase_word_count': row['phrase_word_count'],
                'translation_mode': row['translation_mode'],
                'created_at': row['created_at']
            }
        return None

    def store_new_phrase_translation(
        self,
        source_phrase: str,
        target_phrase: str,
        source_language: str,
        target_language: str,
        translation_mode: str = 'literal'
    ) -> int:
        """
        Store a new phrase translation in database
        
        Args:
            source_phrase: Original phrase
            target_phrase: Translated phrase
            source_language: Language code of source
            target_language: Language code of target
            translation_mode: The pass that produced it
            
        Returns:
            ID of inserted record
        """
        word_count = len(source_phrase.split())
        
        insert_sql = """
        INSERT OR IGNORE INTO phrase_cache
        (source_phrase, target_phrase, phrase_word_count, translation_mode,
         source_language, target_language)
        VALUES (?, ?, ?, ?, ?, ?)
        """
        self.cursor.execute(
            insert_sql,
            (
                source_phrase,
                target_phrase,
                word_count,
                translation_mode,
                source_language,
                target_language
            )
        )
        self.commit_database_changes()
        return self.cursor.lastrowid

    def record_translation_history_entry(
        self,
        request_type: str,
        source_text: str,
        target_text: str,
        source_language: str,
        target_language: str,
        tokens_used: int = None
    ) -> int:
        """
        Record a translation history entry for analytics
        
        Args:
            request_type: 'word' or 'phrase'
            source_text: Original text
            target_text: Translation result
            source_language: Language code of source
            target_language: Language code of target
            tokens_used: API tokens consumed (optional)
            
        Returns:
            ID of inserted record
        """
        insert_sql = """
        INSERT INTO translation_history
        (request_type, source_text, target_text, tokens_used, source_language, target_language)
        VALUES (?, ?, ?, ?, ?, ?)
        """
        self.cursor.execute(
            insert_sql,
            (request_type, source_text, target_text, tokens_used, source_language, target_language)
        )
        self.commit_database_changes()
        return self.cursor.lastrowid

    def update_word_cache_last_accessed_timestamp(self, word_cache_id: int) -> None:
        """
        Update the last accessed timestamp for a word cache entry
        
        Args:
            word_cache_id: ID of word cache record
        """
        update_sql = """
        UPDATE word_cache
        SET last_accessed_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """
        self.cursor.execute(update_sql, (word_cache_id,))
        self.commit_database_changes()

    def update_phrase_cache_last_accessed_timestamp(self, phrase_cache_id: int) -> None:
        """
        Update the last accessed timestamp for a phrase cache entry
        
        Args:
            phrase_cache_id: ID of phrase cache record
        """
        update_sql = """
        UPDATE phrase_cache
        SET last_accessed_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """
        self.cursor.execute(update_sql, (phrase_cache_id,))
        self.commit_database_changes()

    def get_all_translation_history(self) -> List[Dict]:
        """
        Retrieve all translation history entries for analytics
        
        Returns:
            List of all translation history records
        """
        query = "SELECT * FROM translation_history ORDER BY timestamp DESC"
        self.cursor.execute(query)
        rows = self.cursor.fetchall()
        return [dict(row) for row in rows]

    def count_cached_word_translations(self) -> int:
        """
        Count total cached word translations
        
        Returns:
            Number of words in cache
        """
        query = "SELECT COUNT(*) as count FROM word_cache"
        self.cursor.execute(query)
        return self.cursor.fetchone()['count']

    def count_cached_phrase_translations(self) -> int:
        """
        Count total cached phrase translations
        
        Returns:
            Number of phrases in cache
        """
        query = "SELECT COUNT(*) as count FROM phrase_cache"
        self.cursor.execute(query)
        return self.cursor.fetchone()['count']

    def count_total_api_requests_made(self) -> int:
        """
        Count total API requests recorded in history
        
        Returns:
            Number of API requests made
        """
        query = "SELECT COUNT(*) as count FROM translation_history"
        self.cursor.execute(query)
        return self.cursor.fetchone()['count']

    def calculate_total_tokens_used(self) -> int:
        """
        Calculate total tokens used across all API requests
        
        Returns:
            Sum of all tokens used
        """
        query = "SELECT COALESCE(SUM(tokens_used), 0) as total FROM translation_history"
        self.cursor.execute(query)
        return self.cursor.fetchone()['total']
