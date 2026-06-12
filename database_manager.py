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
        """Establish connection to SQLite database"""
        try:
            self.connection = sqlite3.connect(str(self.database_path))
            self.connection.row_factory = sqlite3.Row
            self.cursor = self.connection.cursor()
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
