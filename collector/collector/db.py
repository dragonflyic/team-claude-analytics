"""PostgreSQL database client for storing raw Claude logs."""

import logging

import psycopg2
from psycopg2.extras import Json

from .config import Config

logger = logging.getLogger(__name__)


class DatabaseClient:
    """Client for storing raw log lines in PostgreSQL."""

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

    def insert_raw_line(
        self, collector_host: str, file_path: str, line_offset: int, raw_json: dict
    ) -> bool:
        """Insert a raw log line into the database.

        Returns True if inserted, False if already exists (duplicate).
        """
        self.ensure_connected()

        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO claude_raw_logs (collector_host, file_path, line_offset, raw_json)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (collector_host, file_path, line_offset) DO NOTHING
                    """,
                    (collector_host, file_path, line_offset, Json(raw_json)),
                )
                return cur.rowcount > 0
        except psycopg2.Error as e:
            logger.error(f"Failed to insert line at {file_path}:{line_offset}: {e}")
            self._conn = None
            return False

    def init_schema(self) -> None:
        """Initialize the database schema if it doesn't exist."""
        self.ensure_connected()

        schema_sql = """
        CREATE TABLE IF NOT EXISTS claude_raw_logs (
            id SERIAL PRIMARY KEY,
            collector_host VARCHAR(255) NOT NULL,
            file_path TEXT NOT NULL,
            line_offset BIGINT NOT NULL,
            raw_json JSONB NOT NULL,
            collected_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(collector_host, file_path, line_offset)
        );

        CREATE INDEX IF NOT EXISTS idx_raw_logs_host ON claude_raw_logs(collector_host);
        CREATE INDEX IF NOT EXISTS idx_raw_logs_file ON claude_raw_logs(file_path);
        CREATE INDEX IF NOT EXISTS idx_raw_logs_collected ON claude_raw_logs(collected_at);

        -- JSON indexes for common query patterns
        CREATE INDEX IF NOT EXISTS idx_raw_logs_session
            ON claude_raw_logs((raw_json->>'sessionId'));
        CREATE INDEX IF NOT EXISTS idx_raw_logs_timestamp
            ON claude_raw_logs((raw_json->>'timestamp'));
        CREATE INDEX IF NOT EXISTS idx_raw_logs_git_branch
            ON claude_raw_logs((raw_json->>'gitBranch'));
        CREATE INDEX IF NOT EXISTS idx_raw_logs_type
            ON claude_raw_logs((raw_json->>'type'));
        """

        try:
            with self._conn.cursor() as cur:
                cur.execute(schema_sql)
            logger.info("Database schema initialized")
        except psycopg2.Error as e:
            logger.error(f"Failed to initialize schema: {e}")
            raise
