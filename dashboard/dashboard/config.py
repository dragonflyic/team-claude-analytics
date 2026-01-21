"""Configuration management for the dashboard."""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


@dataclass
class Config:
    """Dashboard configuration."""

    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    db_sslmode: str
    github_token: str
    github_repos: list[str]
    sync_interval_minutes: int

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        load_dotenv()

        repos_str = os.getenv("GITHUB_REPOS", "")
        repos = [r.strip() for r in repos_str.split(",") if r.strip()]

        return cls(
            db_host=os.getenv("DB_HOST", "localhost"),
            db_port=int(os.getenv("DB_PORT", "5432")),
            db_name=os.getenv("DB_NAME", "claude_logs"),
            db_user=os.getenv("DB_USER", "claude_admin"),
            db_password=os.getenv("DB_PASSWORD", ""),
            db_sslmode=os.getenv("DB_SSLMODE", "require"),
            github_token=os.getenv("GITHUB_TOKEN", ""),
            github_repos=repos,
            sync_interval_minutes=int(os.getenv("SYNC_INTERVAL_MINUTES", "15")),
        )

    @property
    def db_connection_string(self) -> str:
        """Build PostgreSQL connection string."""
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
