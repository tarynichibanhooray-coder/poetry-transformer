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
        self.commit_database_changes()

    def create_word_cache_table(self) -> None:
        """
        Create table for storing individual word translations and synonyms
        
        Columns:
            id: Unique identifier
            source_word: Original word in source language
            target_word: Primary translation in target language
            synonyms_json: JSON array of up to 7 synonyms
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
            source_language TEXT NOT NULL,
            target_language TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_word, source_language, target_language)
        );
        """
        self.cursor.execute(create_table_sql)

    def create_phrase_cache_table(self) -> None:
        """
        Create table for storing multi-word phrase translations
        
        Columns:
            id: Unique identifier
            source_phrase: Original phrase in source language
            target_phrase: Translation in target language
            phrase_word_count: Number of words in phrase
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
            source_language TEXT NOT NULL,
            target_language TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_phrase, source_language, target_language)
        );
        """
        self.cursor.execute(create_table_sql)

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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        self.cursor.execute(create_table_sql)

    def store_or_update_poem_entry(
        self,
        raw_text: str,
        source_language: str,
        source_language_code: str,
        target_language: str,
        target_language_code: str,
        title: str = None,
        stanza_delimiter: str = None
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
            SET title = COALESCE(?, title), updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """
            self.cursor.execute(update_sql, (title, existing_row['id']))
            self.commit_database_changes()
            return existing_row['id']

        lines_json = json.dumps(raw_text.split('\n'), ensure_ascii=False)

        insert_sql = """
        INSERT INTO poems
        (title, source_language, source_language_code, target_language,
         target_language_code, raw_text, lines_json, stanza_delimiter)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                stanza_delimiter
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
               target_language_code, raw_text, created_at
        FROM poems
        ORDER BY id DESC
        """
        self.cursor.execute(query)
        return [dict(row) for row in self.cursor.fetchall()]

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
               target_language_code, raw_text, created_at
        FROM poems
        WHERE id = ?
        """
        self.cursor.execute(query, (poem_id,))
        row = self.cursor.fetchone()
        return dict(row) if row else None

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
        target_language: str
    ) -> Optional[Dict]:
        """
        Retrieve a cached word translation from database
        
        Args:
            source_word: Original word to look up
            source_language: Language code of source
            target_language: Language code of target
            
        Returns:
            Dictionary with word data or None if not found
        """
        query = """
        SELECT id, source_word, target_word, synonyms_json, created_at
        FROM word_cache
        WHERE source_word = ? AND source_language = ? AND target_language = ?
        """
        self.cursor.execute(query, (source_word, source_language, target_language))
        row = self.cursor.fetchone()
        
        if row:
            self.update_word_cache_last_accessed_timestamp(row['id'])
            return {
                'id': row['id'],
                'source_word': row['source_word'],
                'target_word': row['target_word'],
                'synonyms': json.loads(row['synonyms_json']),
                'created_at': row['created_at']
            }
        return None

    def store_new_word_translation_with_synonyms(
        self,
        source_word: str,
        target_word: str,
        synonyms: List[str],
        source_language: str,
        target_language: str
    ) -> int:
        """
        Store a new word translation with synonyms in database
        
        Args:
            source_word: Original word
            target_word: Primary translation
            synonyms: List of up to 7 synonyms
            source_language: Language code of source
            target_language: Language code of target
            
        Returns:
            ID of inserted record
        """
        # Ensure we don't exceed 7 synonyms
        limited_synonyms = synonyms[:config.MAX_SYNONYMS_PER_WORD]
        synonyms_json = json.dumps(limited_synonyms)
        
        insert_sql = """
        INSERT OR IGNORE INTO word_cache
        (source_word, target_word, synonyms_json, source_language, target_language)
        VALUES (?, ?, ?, ?, ?)
        """
        self.cursor.execute(
            insert_sql,
            (source_word, target_word, synonyms_json, source_language, target_language)
        )
        self.commit_database_changes()
        return self.cursor.lastrowid

    def retrieve_cached_phrase_translation(
        self,
        source_phrase: str,
        source_language: str,
        target_language: str
    ) -> Optional[Dict]:
        """
        Retrieve a cached phrase translation from database
        
        Args:
            source_phrase: Original phrase to look up
            source_language: Language code of source
            target_language: Language code of target
            
        Returns:
            Dictionary with phrase data or None if not found
        """
        query = """
        SELECT id, source_phrase, target_phrase, phrase_word_count, created_at
        FROM phrase_cache
        WHERE source_phrase = ? AND source_language = ? AND target_language = ?
        """
        self.cursor.execute(query, (source_phrase, source_language, target_language))
        row = self.cursor.fetchone()
        
        if row:
            self.update_phrase_cache_last_accessed_timestamp(row['id'])
            return {
                'id': row['id'],
                'source_phrase': row['source_phrase'],
                'target_phrase': row['target_phrase'],
                'phrase_word_count': row['phrase_word_count'],
                'created_at': row['created_at']
            }
        return None

    def store_new_phrase_translation(
        self,
        source_phrase: str,
        target_phrase: str,
        source_language: str,
        target_language: str
    ) -> int:
        """
        Store a new phrase translation in database
        
        Args:
            source_phrase: Original phrase
            target_phrase: Translated phrase
            source_language: Language code of source
            target_language: Language code of target
            
        Returns:
            ID of inserted record
        """
        word_count = len(source_phrase.split())
        
        insert_sql = """
        INSERT OR IGNORE INTO phrase_cache
        (source_phrase, target_phrase, phrase_word_count, source_language, target_language)
        VALUES (?, ?, ?, ?, ?)
        """
        self.cursor.execute(
            insert_sql,
            (source_phrase, target_phrase, word_count, source_language, target_language)
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
