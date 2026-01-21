"""PostgreSQL database client for the dashboard."""

import logging
from datetime import datetime, timedelta
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from .config import Config

logger = logging.getLogger(__name__)


# Patterns that indicate system-generated messages, not human input
SYSTEM_MESSAGE_PATTERNS = [
    "This session is being continued from a previous conversation",
    "```You (This Message)",
    "The summary below covers the earlier portion",
    "<system-reminder>",
    "Background bash ",
    "has new output:",
]


def is_human_intervention(msg: dict) -> bool:
    """Check if a message is a genuine human intervention.

    Filters out:
    - Non-user messages (unless message_type not present, assumes pre-filtered)
    - Agent messages (sub-agents)
    - Sidechain messages (agent prompts)
    - Meta/system messages
    - Tool results
    - XML-tagged content (system messages, tool output)
    - System-generated messages (compaction, reminders, etc.)
    - Empty messages

    Args:
        msg: Message dict with keys like 'message_type', 'agent_id',
             'is_sidechain', 'is_meta', 'content_type', 'content'

    Returns:
        True if this is a genuine human-typed message
    """
    # Must be a user message (if message_type present)
    msg_type = msg.get("message_type")
    if msg_type is not None and msg_type != "user":
        return False
    # Skip agent messages
    if msg.get("agent_id"):
        return False
    # Skip sidechain messages (agent prompts)
    if msg.get("is_sidechain") == "true" or msg.get("is_sidechain") is True:
        return False
    # Skip meta/system messages
    if msg.get("is_meta") == "true" or msg.get("is_meta") is True:
        return False
    # Skip tool results
    if msg.get("content_type") == "tool_result":
        return False

    content = msg.get("content", "") or ""
    # Skip XML-tagged content (system messages, tool output)
    if content.startswith("<"):
        return False
    # Skip system-generated messages
    if any(pattern in content for pattern in SYSTEM_MESSAGE_PATTERNS):
        return False
    # Skip empty messages
    if not content.strip():
        return False

    return True


# SQL fragment for filtering human interventions in aggregate queries
# Note: This is a simplified version - some pattern matching is done in Python
HUMAN_INTERVENTION_SQL_FILTER = """
    raw_json->>'type' = 'user'
    AND raw_json->>'agentId' IS NULL
    AND COALESCE(raw_json->>'isSidechain', 'false') != 'true'
    AND COALESCE(raw_json->>'isMeta', 'false') != 'true'
    AND COALESCE(raw_json->'message'->'content'->0->>'type', '') != 'tool_result'
    AND LEFT(COALESCE(raw_json->'message'->'content'#>>'{}', raw_json->>'content', ''), 1) != '<'
"""


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
                sslmode=self.config.db_sslmode,
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
            first_commit_at TIMESTAMPTZ,
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

        ALTER TABLE github_pull_requests ADD COLUMN IF NOT EXISTS first_commit_at TIMESTAMPTZ;
        ALTER TABLE github_pull_requests ADD COLUMN IF NOT EXISTS first_claude_chat_at TIMESTAMPTZ;

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
                        draft, created_at, first_commit_at, first_claude_chat_at,
                        first_review_at, approved_at, merged_at, closed_at,
                        additions, deletions, changed_files,
                        head_branch, base_branch, raw_data, synced_at
                    ) VALUES (
                        %(repo_full_name)s, %(pr_number)s, %(title)s, %(author_login)s,
                        %(state)s, %(draft)s, %(created_at)s, %(first_commit_at)s,
                        %(first_claude_chat_at)s, %(first_review_at)s, %(approved_at)s,
                        %(merged_at)s, %(closed_at)s, %(additions)s, %(deletions)s,
                        %(changed_files)s, %(head_branch)s, %(base_branch)s,
                        %(raw_data)s, NOW()
                    )
                    ON CONFLICT (repo_full_name, pr_number) DO UPDATE SET
                        title = EXCLUDED.title,
                        state = EXCLUDED.state,
                        draft = EXCLUDED.draft,
                        first_commit_at = EXCLUDED.first_commit_at,
                        first_claude_chat_at = EXCLUDED.first_claude_chat_at,
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

    def get_first_claude_chat_for_branches(
        self, branches: list[str]
    ) -> dict[str, datetime | None]:
        """Get first Claude chat timestamps for multiple branches.

        For each branch, finds all sessions that ever touched that branch,
        then returns the earliest timestamp from any message in those sessions.
        This captures work that started on main before switching to the feature branch.

        Returns a dict mapping branch name to earliest chat timestamp.
        """
        self.ensure_connected()

        if not branches:
            return {}

        try:
            with self._conn.cursor() as cur:
                # For each branch, find sessions that touched it, then get min timestamp
                # from ALL messages in those sessions
                # Query from claude_raw_logs using JSON operators
                cur.execute(
                    """
                    WITH branch_sessions AS (
                        SELECT DISTINCT
                            raw_json->>'gitBranch' as target_branch,
                            raw_json->>'sessionId' as session_id
                        FROM claude_raw_logs
                        WHERE raw_json->>'gitBranch' = ANY(%s)
                    )
                    SELECT bs.target_branch, MIN((cl.raw_json->>'timestamp')::timestamptz) as first_chat
                    FROM branch_sessions bs
                    JOIN claude_raw_logs cl ON cl.raw_json->>'sessionId' = bs.session_id
                    GROUP BY bs.target_branch
                    """,
                    (branches,),
                )
                return {row[0]: row[1] for row in cur.fetchall()}
        except psycopg2.Error as e:
            logger.error(f"Failed to get first Claude chats for branches: {e}")
            return {}

    def get_pr_by_repo_and_number(
        self, repo_full_name: str, pr_number: int
    ) -> dict | None:
        """Fetch a single PR by repo and number."""
        self.ensure_connected()

        try:
            with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT * FROM github_pull_requests
                    WHERE repo_full_name = %s AND pr_number = %s
                    """,
                    (repo_full_name, pr_number),
                )
                row = cur.fetchone()
                return dict(row) if row else None
        except psycopg2.Error as e:
            logger.error(f"Failed to fetch PR {repo_full_name}#{pr_number}: {e}")
            return None

    def get_existing_prs_for_repo(self, repo_full_name: str) -> dict[int, dict]:
        """Get existing PRs for a repo, keyed by PR number.

        Returns dict mapping pr_number to {state, synced_at, merged_at, closed_at}.
        Used for incremental sync to skip PRs that don't need updating.
        """
        self.ensure_connected()

        try:
            with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT pr_number, state, synced_at, merged_at, closed_at
                    FROM github_pull_requests
                    WHERE repo_full_name = %s
                    """,
                    (repo_full_name,),
                )
                return {row["pr_number"]: dict(row) for row in cur.fetchall()}
        except psycopg2.Error as e:
            logger.error(f"Failed to fetch existing PRs for {repo_full_name}: {e}")
            return {}

    def get_claude_sessions_for_branch(self, branch: str) -> list[dict]:
        """Fetch all Claude chat messages for sessions that ever used this branch.

        If a session ever has a message on the given branch, we include ALL
        messages from that session (even ones from other branches like main).
        This captures the full context of work that led to the feature branch.

        Returns list of sessions, each containing:
        - session_id: str
        - first_message_at: datetime
        - last_message_at: datetime
        - message_count: int
        - messages: list[dict] - ordered by timestamp
        """
        self.ensure_connected()

        if not branch:
            return []

        try:
            with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Step 1: Find all session IDs that ever touched this branch (fast, uses index)
                cur.execute(
                    """
                    SELECT DISTINCT raw_json->>'sessionId' as session_id
                    FROM claude_raw_logs
                    WHERE raw_json->>'gitBranch' = %s
                    """,
                    (branch,),
                )
                session_ids = [row["session_id"] for row in cur.fetchall()]

                if not session_ids:
                    return []

                # Step 2: Get ALL messages from those sessions using ANY (much faster than IN subquery)
                cur.execute(
                    """
                    SELECT
                        raw_json->>'sessionId' as session_id,
                        raw_json->>'uuid' as message_uuid,
                        raw_json->>'type' as message_type,
                        COALESCE(raw_json->'message'->>'role', raw_json->>'type') as role,
                        COALESCE(raw_json->'message'->'content', raw_json->'content') as content,
                        raw_json->'message'->>'model' as model,
                        (raw_json->>'timestamp')::timestamptz as timestamp,
                        (raw_json->'message'->'usage'->>'input_tokens')::int as input_tokens,
                        (raw_json->'message'->'usage'->>'output_tokens')::int as output_tokens,
                        raw_json->>'gitBranch' as git_branch,
                        raw_json->>'agentId' as agent_id,
                        (raw_json->>'isSidechain')::boolean as is_sidechain,
                        (raw_json->>'isMeta')::boolean as is_meta,
                        raw_json->'message'->'content'->0->>'type' as content_type
                    FROM claude_raw_logs
                    WHERE raw_json->>'sessionId' = ANY(%s)
                    ORDER BY raw_json->>'sessionId', (raw_json->>'timestamp')::timestamptz
                    """,
                    (session_ids,),
                )
                rows = cur.fetchall()

            # Group by session_id
            sessions_map: dict[str, list[dict]] = {}
            for row in rows:
                sid = row["session_id"]
                if sid not in sessions_map:
                    sessions_map[sid] = []
                sessions_map[sid].append(dict(row))

            # Build session objects
            sessions = []
            for session_id, messages in sessions_map.items():
                if messages:
                    sessions.append({
                        "session_id": session_id,
                        "first_message_at": messages[0]["timestamp"],
                        "last_message_at": messages[-1]["timestamp"],
                        "message_count": len(messages),
                        "messages": messages,
                    })

            # Sort by first message time
            sessions.sort(key=lambda s: s["first_message_at"])
            return sessions

        except psycopg2.Error as e:
            logger.error(f"Failed to fetch Claude sessions for branch {branch}: {e}")
            return []

    def get_human_interventions(
        self,
        days: int = 30,
        author: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Fetch all human input messages from Claude sessions.

        Returns messages where a human actually typed something (not tool results,
        system messages, agent prompts, or slash commands).

        Each message includes surrounding context (messages before/after in same session).
        """
        self.ensure_connected()

        try:
            with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Fast query using indexed columns only
                # Filter by type (indexed) and collected_at (indexed)
                # Do additional filtering in Python

                if author:
                    query = f"""
                        SELECT
                            cl.raw_json->>'sessionId' as session_id,
                            cl.raw_json->>'uuid' as message_uuid,
                            cl.raw_json->>'agentId' as agent_id,
                            cl.raw_json->>'isSidechain' as is_sidechain,
                            cl.raw_json->>'isMeta' as is_meta,
                            COALESCE(cl.raw_json->'message'->'content'#>>'{{}}', cl.raw_json->>'content', '') as content,
                            cl.raw_json->'message'->'content'->0->>'type' as content_type,
                            cl.collected_at as timestamp,
                            cl.raw_json->>'gitBranch' as git_branch,
                            cl.collector_host as author,
                            COALESCE(
                                pr.repo_full_name,
                                -- Extract last 2 path components from cwd as fallback repo name
                                (regexp_match(cl.raw_json->>'cwd', '.*/([^/]+/[^/]+)/?$'))[1]
                            ) as repo_full_name
                        FROM claude_raw_logs cl
                        LEFT JOIN github_pull_requests pr ON pr.head_branch = cl.raw_json->>'gitBranch'
                        WHERE cl.raw_json->>'type' = 'user'
                          AND cl.collected_at > NOW() - INTERVAL '{days} days'
                          AND cl.collector_host = %s
                        ORDER BY cl.collected_at DESC
                        LIMIT {limit * 5}
                    """
                    params = (author,)
                else:
                    query = f"""
                        SELECT
                            cl.raw_json->>'sessionId' as session_id,
                            cl.raw_json->>'uuid' as message_uuid,
                            cl.raw_json->>'agentId' as agent_id,
                            cl.raw_json->>'isSidechain' as is_sidechain,
                            cl.raw_json->>'isMeta' as is_meta,
                            COALESCE(cl.raw_json->'message'->'content'#>>'{{}}', cl.raw_json->>'content', '') as content,
                            cl.raw_json->'message'->'content'->0->>'type' as content_type,
                            cl.collected_at as timestamp,
                            cl.raw_json->>'gitBranch' as git_branch,
                            cl.collector_host as author,
                            COALESCE(
                                pr.repo_full_name,
                                -- Extract last 2 path components from cwd as fallback repo name
                                (regexp_match(cl.raw_json->>'cwd', '.*/([^/]+/[^/]+)/?$'))[1]
                            ) as repo_full_name
                        FROM claude_raw_logs cl
                        LEFT JOIN github_pull_requests pr ON pr.head_branch = cl.raw_json->>'gitBranch'
                        WHERE cl.raw_json->>'type' = 'user'
                          AND cl.collected_at > NOW() - INTERVAL '{days} days'
                        ORDER BY cl.collected_at DESC
                        LIMIT {limit * 5}
                    """
                    params = ()

                cur.execute(query, params)
                candidates = [dict(row) for row in cur.fetchall()]

                # Python-side filtering using shared function
                messages = []
                for msg in candidates:
                    if is_human_intervention(msg):
                        messages.append(msg)
                        if len(messages) >= limit:
                            break

                # Context will be loaded on-demand via separate endpoint
                for msg in messages:
                    msg["context_before"] = []
                    msg["context_after"] = []

                return messages

        except psycopg2.Error as e:
            logger.error(f"Failed to fetch human interventions: {e}")
            return []

    def get_message_context(self, session_id: str, message_uuid: str) -> dict:
        """Fetch context (surrounding messages) for a specific message.

        Returns dict with context_before and context_after lists.
        """
        self.ensure_connected()

        try:
            with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get all messages from this session ordered by timestamp
                cur.execute(
                    """
                    SELECT
                        raw_json->>'uuid' as message_uuid,
                        raw_json->>'type' as message_type,
                        COALESCE(raw_json->'message'->>'role', raw_json->>'type') as role,
                        COALESCE(raw_json->'message'->'content', raw_json->'content') as content,
                        (raw_json->>'timestamp')::timestamptz as timestamp,
                        raw_json->>'gitBranch' as git_branch,
                        raw_json->>'agentId' as agent_id,
                        (raw_json->>'isSidechain')::boolean as is_sidechain,
                        (raw_json->>'isMeta')::boolean as is_meta,
                        raw_json->'message'->'content'->0->>'type' as content_type
                    FROM claude_raw_logs
                    WHERE raw_json->>'sessionId' = %s
                    ORDER BY (raw_json->>'timestamp')::timestamptz
                    """,
                    (session_id,),
                )
                messages = [dict(row) for row in cur.fetchall()]

                # Find the target message index
                idx = None
                for i, m in enumerate(messages):
                    if m["message_uuid"] == message_uuid:
                        idx = i
                        break

                if idx is None:
                    return {"context_before": [], "context_after": []}

                # Get 2 messages before and 2 after
                start = max(0, idx - 2)
                end = min(len(messages), idx + 3)

                return {
                    "context_before": messages[start:idx],
                    "context_after": messages[idx + 1:end],
                }

        except psycopg2.Error as e:
            logger.error(f"Failed to fetch message context: {e}")
            return {"context_before": [], "context_after": []}

    def get_interventions_by_pr(
        self,
        days: int = 30,
        repo: str | None = None,
        author: str | None = None,
    ) -> list[dict]:
        """Get human intervention counts and timing aggregated by PR.

        Returns list of PRs with:
        - pr info (repo, number, title, author)
        - intervention_count: number of human interventions
        - claude_hours: total Claude session time
        - interventions_per_hour: intervention_count / claude_hours
        """
        self.ensure_connected()

        try:
            with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Step 1: Get PRs (fast, small table)
                query = f"""
                    SELECT repo_full_name, pr_number, title, author_login, head_branch,
                           created_at, merged_at
                    FROM github_pull_requests
                    WHERE created_at > NOW() - INTERVAL '{days} days'
                      AND head_branch IS NOT NULL
                """
                params: list[Any] = []

                if repo:
                    query += " AND repo_full_name = %s"
                    params.append(repo)
                if author:
                    query += " AND author_login = %s"
                    params.append(author)

                query += " ORDER BY created_at DESC LIMIT 50"
                cur.execute(query, params if params else None)
                prs = [dict(row) for row in cur.fetchall()]

                if not prs:
                    return []

                branches = list(set(pr["head_branch"] for pr in prs if pr["head_branch"]))
                if not branches:
                    return []

                # Step 2: Get both timing stats and intervention counts in one query
                cur.execute(
                    f"""
                    SELECT
                        raw_json->>'gitBranch' as branch,
                        COUNT(DISTINCT raw_json->>'sessionId') as session_count,
                        MIN((raw_json->>'timestamp')::timestamptz) as first_ts,
                        MAX((raw_json->>'timestamp')::timestamptz) as last_ts,
                        COUNT(*) FILTER (WHERE {HUMAN_INTERVENTION_SQL_FILTER}) as intervention_count
                    FROM claude_raw_logs
                    WHERE raw_json->>'gitBranch' = ANY(%s)
                    GROUP BY raw_json->>'gitBranch'
                    """,
                    (branches,),
                )
                branch_stats = {row["branch"]: row for row in cur.fetchall()}

                # Calculate hours per branch (simplified: total span, not sum of sessions)
                branch_hours: dict[str, float] = {}
                branch_counts: dict[str, int] = {}
                for branch, stats in branch_stats.items():
                    if stats["first_ts"] and stats["last_ts"]:
                        hours = (stats["last_ts"] - stats["first_ts"]).total_seconds() / 3600.0
                        branch_hours[branch] = hours
                    branch_counts[branch] = stats["intervention_count"]

            # Build results
            results = []
            for pr in prs:
                branch = pr["head_branch"]
                intervention_count = branch_counts.get(branch, 0)
                claude_hours = round(branch_hours.get(branch, 0), 2)

                # Calculate average minutes between interventions
                # If N interventions over T hours, avg time between = T*60 / N minutes
                avg_minutes_between = (
                    round((claude_hours * 60) / intervention_count, 1)
                    if intervention_count > 0 and claude_hours > 0
                    else None
                )

                results.append({
                    "repo_full_name": pr["repo_full_name"],
                    "pr_number": pr["pr_number"],
                    "title": pr["title"],
                    "author_login": pr["author_login"],
                    "head_branch": pr["head_branch"],
                    "created_at": pr["created_at"],
                    "merged_at": pr["merged_at"],
                    "intervention_count": intervention_count,
                    "claude_hours": claude_hours,
                    "avg_minutes_between": avg_minutes_between,
                })

            return results

        except psycopg2.Error as e:
            logger.error(f"Failed to fetch interventions by PR: {e}")
            return []

    def get_interventions_for_branch(self, branch: str) -> list[dict]:
        """Get human intervention messages for a specific branch.

        Used for on-demand loading when expanding a PR row.
        """
        self.ensure_connected()

        try:
            with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get session IDs for this branch
                cur.execute(
                    """
                    SELECT DISTINCT raw_json->>'sessionId' as session_id
                    FROM claude_raw_logs
                    WHERE raw_json->>'gitBranch' = %s
                    """,
                    (branch,),
                )
                session_ids = [row["session_id"] for row in cur.fetchall()]

                if not session_ids:
                    return []

                # Get user messages from those sessions
                cur.execute(
                    """
                    SELECT
                        raw_json->>'sessionId' as session_id,
                        raw_json->>'uuid' as message_uuid,
                        raw_json->>'agentId' as agent_id,
                        raw_json->>'isSidechain' as is_sidechain,
                        raw_json->>'isMeta' as is_meta,
                        COALESCE(raw_json->'message'->'content'#>>'{}', raw_json->>'content', '') as content,
                        raw_json->'message'->'content'->0->>'type' as content_type,
                        (raw_json->>'timestamp')::timestamptz as timestamp,
                        raw_json->>'gitBranch' as git_branch,
                        collector_host as author
                    FROM claude_raw_logs
                    WHERE raw_json->>'sessionId' = ANY(%s)
                      AND raw_json->>'type' = 'user'
                    ORDER BY (raw_json->>'timestamp')::timestamptz
                    """,
                    (session_ids,),
                )
                candidates = [dict(row) for row in cur.fetchall()]

            # Filter using shared function
            interventions = [msg for msg in candidates if is_human_intervention(msg)]

            return interventions

        except psycopg2.Error as e:
            logger.error(f"Failed to fetch interventions for branch {branch}: {e}")
            return []

    def get_collectors(self) -> list[str]:
        """Get list of unique collector hosts (authors/machines)."""
        self.ensure_connected()

        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT collector_host FROM claude_raw_logs ORDER BY collector_host"
                )
                return [row[0] for row in cur.fetchall()]
        except psycopg2.Error as e:
            logger.error(f"Failed to fetch collectors: {e}")
            return []
