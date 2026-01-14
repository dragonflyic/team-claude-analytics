-- Database schema for Claude analytics logs
-- Run this after provisioning RDS

CREATE TABLE IF NOT EXISTS claude_logs (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    message_uuid VARCHAR(255) UNIQUE NOT NULL,
    parent_uuid VARCHAR(255),
    message_type VARCHAR(50),  -- 'user', 'assistant', 'file-history-snapshot'
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
    collector_host VARCHAR(255),  -- which dev machine sent this
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_session_id ON claude_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_timestamp ON claude_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_collector_host ON claude_logs(collector_host);
CREATE INDEX IF NOT EXISTS idx_message_type ON claude_logs(message_type);
CREATE INDEX IF NOT EXISTS idx_model ON claude_logs(model);
