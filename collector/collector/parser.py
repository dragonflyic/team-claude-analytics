"""JSONL log file parser for Claude logs."""

import json
from typing import Any
from dataclasses import dataclass


@dataclass
class LogEntry:
    """Parsed log entry from Claude JSONL files."""

    session_id: str
    message_uuid: str
    parent_uuid: str | None
    message_type: str
    role: str | None
    content: dict | None
    model: str | None
    cwd: str | None
    git_branch: str | None
    slug: str | None
    version: str | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_creation_tokens: int | None
    timestamp: str


def parse_line(line: str) -> LogEntry | None:
    """Parse a single JSONL line into a LogEntry.

    Returns None if the line cannot be parsed or is not a message we want to store.
    """
    try:
        data = json.loads(line.strip())
    except json.JSONDecodeError:
        return None

    # Skip empty or non-message entries
    if not data:
        return None

    message_type = data.get("type")
    if not message_type:
        return None

    # Extract message UUID
    message_uuid = data.get("uuid")
    if not message_uuid:
        # For file-history-snapshot, use messageId
        message_uuid = data.get("messageId")

    if not message_uuid:
        return None

    # Extract timestamp
    timestamp = data.get("timestamp")
    if not timestamp:
        # Try to get from snapshot
        snapshot = data.get("snapshot", {})
        timestamp = snapshot.get("timestamp")

    if not timestamp:
        return None

    # Extract message content and metadata
    message = data.get("message", {})
    usage = message.get("usage", {})

    # Handle cache tokens - can be in different structures
    cache_read = usage.get("cache_read_input_tokens")
    cache_creation = usage.get("cache_creation_input_tokens")
    if cache_creation is None:
        cache_creation_obj = usage.get("cache_creation", {})
        cache_creation = cache_creation_obj.get("ephemeral_5m_input_tokens", 0)
        if cache_creation_obj.get("ephemeral_1h_input_tokens"):
            cache_creation += cache_creation_obj.get("ephemeral_1h_input_tokens", 0)

    return LogEntry(
        session_id=data.get("sessionId", ""),
        message_uuid=message_uuid,
        parent_uuid=data.get("parentUuid"),
        message_type=message_type,
        role=message.get("role"),
        content=message.get("content") if message else None,
        model=message.get("model"),
        cwd=data.get("cwd"),
        git_branch=data.get("gitBranch"),
        slug=data.get("slug"),
        version=data.get("version"),
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_creation,
        timestamp=timestamp,
    )
