"""Configuration management for the collector."""

import os
import socket
from pathlib import Path
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass
class Config:
    """Collector configuration."""

    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    collector_host: str
    claude_projects_path: Path
    state_path: Path

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        load_dotenv()

        return cls(
            db_host=os.getenv("DB_HOST", "localhost"),
            db_port=int(os.getenv("DB_PORT", "5432")),
            db_name=os.getenv("DB_NAME", "claude_logs"),
            db_user=os.getenv("DB_USER", "claude_admin"),
            db_password=os.getenv("DB_PASSWORD", ""),
            collector_host=os.getenv("COLLECTOR_HOST", socket.gethostname()),
            claude_projects_path=Path(
                os.getenv("CLAUDE_PROJECTS_PATH", Path.home() / ".claude" / "projects")
            ),
            # v2: Changed from state.json to state-v2.json so new collectors
            # automatically re-process all files into the new claude_raw_logs table
            state_path=Path(
                os.getenv("STATE_PATH", Path.home() / ".claude-collector" / "state-v2.json")
            ),
        )

    @property
    def db_connection_string(self) -> str:
        """Build PostgreSQL connection string."""
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
