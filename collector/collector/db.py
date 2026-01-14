"""PostgreSQL database client for storing Claude logs."""

import json
import logging
from typing import Any

import psycopg2
from psycopg2.extras import Json

from .config import Config
from .parser import LogEntry

logger = logging.getLogger(__name__)


class DatabaseClient:
    """Client for storing log entries in PostgreSQL."""

    def __init__(self, config: Config):
        self.config = config
        self._conn = None

    def connect(self) -> None:
        """Establish database connection."""
        try:
            self._conn = psycopg2.connect(
                host=self.config.db_host,
                port=self.config.db_port,
                dbname=self.config.db_name,
                user=self.config.db_user,
                password=self.config.db_password,
            )
            self._conn.autocommit = True
            logger.info(f"Connected to database at {self.config.db_host}")
        except psycopg2.Error as e:
            logger.error(f"Failed to connect to database: {e}")
            raise

    def disconnect(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.info("Disconnected from database")

    def ensure_connected(self) -> None:
        """Ensure connection is active, reconnect if needed."""
        if self._conn is None or self._conn.closed:
            self.connect()

    def insert_entry(self, entry: LogEntry, collector_host: str) -> bool:
        """Insert a log entry into the database.

        Returns True if inserted, False if already exists (duplicate).
        """
        self.ensure_connected()

        # Convert content to JSON
        content_json = None
        if entry.content is not None:
            content_json = Json(entry.content)

        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO claude_logs (
                        session_id, message_uuid, parent_uuid, message_type,
                        role, content, model, cwd, git_branch, slug, version,
                        input_tokens, output_tokens, cache_read_tokens,
                        cache_creation_tokens, timestamp, collector_host
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (message_uuid) DO NOTHING
                    """,
                    (
                        entry.session_id,
                        entry.message_uuid,
                        entry.parent_uuid,
                        entry.message_type,
                        entry.role,
                        content_json,
                        entry.model,
                        entry.cwd,
                        entry.git_branch,
                        entry.slug,
                        entry.version,
                        entry.input_tokens,
                        entry.output_tokens,
                        entry.cache_read_tokens,
                        entry.cache_creation_tokens,
                        entry.timestamp,
                        collector_host,
                    ),
                )
                return cur.rowcount > 0
        except psycopg2.Error as e:
            logger.error(f"Failed to insert entry {entry.message_uuid}: {e}")
            # Try to reconnect on next operation
            self._conn = None
            return False

    def init_schema(self) -> None:
        """Initialize the database schema if it doesn't exist."""
        self.ensure_connected()

        schema_sql = """
        CREATE TABLE IF NOT EXISTS claude_logs (
            id SERIAL PRIMARY KEY,
            session_id VARCHAR(255) NOT NULL,
            message_uuid VARCHAR(255) UNIQUE NOT NULL,
            parent_uuid VARCHAR(255),
            message_type VARCHAR(50),
            role VARCHAR(50),
            content JSONB,
            model VARCHAR(100),
            cwd TEXT,
            git_branch VARCHAR(255),
            slug VARCHAR(255),
            version VARCHAR(50),
            input_tokens INTEGER,
            output_tokens INTEGER,
            cache_read_tokens INTEGER,
            cache_creation_tokens INTEGER,
            timestamp TIMESTAMPTZ NOT NULL,
            collector_host VARCHAR(255),
            created_at TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_session_id ON claude_logs(session_id);
        CREATE INDEX IF NOT EXISTS idx_timestamp ON claude_logs(timestamp);
        CREATE INDEX IF NOT EXISTS idx_collector_host ON claude_logs(collector_host);
        CREATE INDEX IF NOT EXISTS idx_message_type ON claude_logs(message_type);
        CREATE INDEX IF NOT EXISTS idx_model ON claude_logs(model);
        """

        try:
            with self._conn.cursor() as cur:
                cur.execute(schema_sql)
            logger.info("Database schema initialized")
        except psycopg2.Error as e:
            logger.error(f"Failed to initialize schema: {e}")
            raise
