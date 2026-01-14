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

-- GitHub Pull Requests for productivity metrics
CREATE TABLE IF NOT EXISTS github_pull_requests (
    id SERIAL PRIMARY KEY,
    repo_full_name VARCHAR(255) NOT NULL,
    pr_number INTEGER NOT NULL,
    title TEXT,
    author_login VARCHAR(255) NOT NULL,
    state VARCHAR(50),  -- 'open', 'closed', 'merged'
    draft BOOLEAN DEFAULT FALSE,

    -- Timestamps for cycle time calculation
    created_at TIMESTAMPTZ NOT NULL,
    first_review_at TIMESTAMPTZ,
    approved_at TIMESTAMPTZ,
    merged_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,

    -- PR metadata
    additions INTEGER,
    deletions INTEGER,
    changed_files INTEGER,
    head_branch VARCHAR(255),  -- Links to claude_logs.git_branch
    base_branch VARCHAR(255),

    -- Raw API response for flexibility
    raw_data JSONB,

    -- Sync tracking
    synced_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(repo_full_name, pr_number)
);

CREATE INDEX IF NOT EXISTS idx_pr_author ON github_pull_requests(author_login);
CREATE INDEX IF NOT EXISTS idx_pr_repo ON github_pull_requests(repo_full_name);
CREATE INDEX IF NOT EXISTS idx_pr_created ON github_pull_requests(created_at);
CREATE INDEX IF NOT EXISTS idx_pr_merged ON github_pull_requests(merged_at);
CREATE INDEX IF NOT EXISTS idx_pr_head_branch ON github_pull_requests(head_branch);
