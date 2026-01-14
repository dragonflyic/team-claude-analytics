"""PostgreSQL database client for the dashboard."""

import logging
from datetime import datetime, timedelta
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from .config import Config

logger = logging.getLogger(__name__)


class DatabaseClient:
    """Client for dashboard database operations."""

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

    def init_schema(self) -> None:
        """Initialize the PR table schema if it doesn't exist."""
        self.ensure_connected()

        schema_sql = """
        CREATE TABLE IF NOT EXISTS github_pull_requests (
            id SERIAL PRIMARY KEY,
            repo_full_name VARCHAR(255) NOT NULL,
            pr_number INTEGER NOT NULL,
            title TEXT,
            author_login VARCHAR(255) NOT NULL,
            state VARCHAR(50),
            draft BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL,
            first_review_at TIMESTAMPTZ,
            approved_at TIMESTAMPTZ,
            merged_at TIMESTAMPTZ,
            closed_at TIMESTAMPTZ,
            additions INTEGER,
            deletions INTEGER,
            changed_files INTEGER,
            head_branch VARCHAR(255),
            base_branch VARCHAR(255),
            raw_data JSONB,
            synced_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(repo_full_name, pr_number)
        );

        CREATE INDEX IF NOT EXISTS idx_pr_author ON github_pull_requests(author_login);
        CREATE INDEX IF NOT EXISTS idx_pr_repo ON github_pull_requests(repo_full_name);
        CREATE INDEX IF NOT EXISTS idx_pr_created ON github_pull_requests(created_at);
        CREATE INDEX IF NOT EXISTS idx_pr_merged ON github_pull_requests(merged_at);
        CREATE INDEX IF NOT EXISTS idx_pr_head_branch ON github_pull_requests(head_branch);
        """

        try:
            with self._conn.cursor() as cur:
                cur.execute(schema_sql)
            logger.info("Database schema initialized")
        except psycopg2.Error as e:
            logger.error(f"Failed to initialize schema: {e}")
            raise

    def upsert_pr(self, pr_data: dict) -> bool:
        """Insert or update a pull request record."""
        self.ensure_connected()

        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO github_pull_requests (
                        repo_full_name, pr_number, title, author_login, state,
                        draft, created_at, first_review_at, approved_at, merged_at,
                        closed_at, additions, deletions, changed_files, head_branch,
                        base_branch, raw_data, synced_at
                    ) VALUES (
                        %(repo_full_name)s, %(pr_number)s, %(title)s, %(author_login)s,
                        %(state)s, %(draft)s, %(created_at)s, %(first_review_at)s,
                        %(approved_at)s, %(merged_at)s, %(closed_at)s, %(additions)s,
                        %(deletions)s, %(changed_files)s, %(head_branch)s, %(base_branch)s,
                        %(raw_data)s, NOW()
                    )
                    ON CONFLICT (repo_full_name, pr_number) DO UPDATE SET
                        title = EXCLUDED.title,
                        state = EXCLUDED.state,
                        draft = EXCLUDED.draft,
                        first_review_at = EXCLUDED.first_review_at,
                        approved_at = EXCLUDED.approved_at,
                        merged_at = EXCLUDED.merged_at,
                        closed_at = EXCLUDED.closed_at,
                        additions = EXCLUDED.additions,
                        deletions = EXCLUDED.deletions,
                        changed_files = EXCLUDED.changed_files,
                        raw_data = EXCLUDED.raw_data,
                        synced_at = NOW()
                    """,
                    {
                        **pr_data,
                        "raw_data": Json(pr_data.get("raw_data")),
                    },
                )
                return True
        except psycopg2.Error as e:
            logger.error(f"Failed to upsert PR: {e}")
            self._conn = None
            return False

    def get_prs(
        self,
        repo: str | None = None,
        author: str | None = None,
        days: int = 30,
        merged_only: bool = False,
    ) -> list[dict]:
        """Fetch pull requests with optional filters."""
        self.ensure_connected()

        query = """
            SELECT * FROM github_pull_requests
            WHERE created_at > NOW() - INTERVAL '%s days'
        """
        params: list[Any] = [days]

        if repo:
            query += " AND repo_full_name = %s"
            params.append(repo)

        if author:
            query += " AND author_login = %s"
            params.append(author)

        if merged_only:
            query += " AND merged_at IS NOT NULL"

        query += " ORDER BY created_at DESC"

        try:
            with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]
        except psycopg2.Error as e:
            logger.error(f"Failed to fetch PRs: {e}")
            return []

    def get_repos(self) -> list[str]:
        """Get list of unique repos in the database."""
        self.ensure_connected()

        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT repo_full_name FROM github_pull_requests ORDER BY repo_full_name"
                )
                return [row[0] for row in cur.fetchall()]
        except psycopg2.Error as e:
            logger.error(f"Failed to fetch repos: {e}")
            return []

    def get_authors(self) -> list[str]:
        """Get list of unique authors in the database."""
        self.ensure_connected()

        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT author_login FROM github_pull_requests ORDER BY author_login"
                )
                return [row[0] for row in cur.fetchall()]
        except psycopg2.Error as e:
            logger.error(f"Failed to fetch authors: {e}")
            return []
