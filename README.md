# Team Claude Analytics

Shared team analytics for Claude usage. Collects Claude chat logs from developer machines and streams them to a shared PostgreSQL database.

## Components

- **Collector**: Python service that watches `~/.claude/projects` for log changes and streams entries to PostgreSQL
- **Dashboard**: FastAPI webapp showing PR cycle time and Claude usage analytics

## Prerequisites

- Python 3.12+
- Poetry
- Docker (for containerized deployment)
- A PostgreSQL database the collector and dashboard can reach

## Quick Start (for developers)

Run this one-liner to install the collector on your machine:

```bash
curl -sSL https://raw.githubusercontent.com/dragonflyic/team-claude-analytics/main/collector/install.sh | bash
```

It will prompt for the database password (ask your team lead).

---

## Running the Collector

### Option A: Run Locally with Poetry

```bash
cd collector
poetry install

# Set environment variables
export DB_HOST=your-postgres-host
export DB_PORT=5432
export DB_NAME=claude_logs
export DB_USER=claude_admin
export DB_PASSWORD=your-password

# Run
poetry run collector
```

### Option B: Run with Docker Compose (local build)

```bash
# Copy and edit environment file
cp .env.example .env
# Edit .env with your DB credentials

# Build and run
docker-compose up -d

# View logs
docker-compose logs -f
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DB_HOST` | PostgreSQL host | `localhost` |
| `DB_PORT` | PostgreSQL port | `5432` |
| `DB_NAME` | Database name | `claude_logs` |
| `DB_USER` | Database username | `claude_admin` |
| `DB_PASSWORD` | Database password | (required) |
| `COLLECTOR_HOST` | Identifier for this machine | hostname |
| `CLAUDE_PROJECTS_PATH` | Path to Claude projects | `~/.claude/projects` |

## Database Schema

The collector creates a `claude_logs` table with the following key fields:

- `session_id`: Claude session identifier
- `message_uuid`: Unique message ID
- `message_type`: Type of log entry (user, assistant, etc.)
- `content`: Full message content as JSONB
- `model`: Claude model used
- `input_tokens`, `output_tokens`: Token usage
- `timestamp`: When the message occurred
- `collector_host`: Which machine sent this entry

## Development

```bash
cd collector
poetry install

# Run locally (requires a PostgreSQL database)
poetry run collector
```

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Dev Machine 1  │     │  Dev Machine 2  │     │  Dev Machine N  │
│  ┌───────────┐  │     │  ┌───────────┐  │     │  ┌───────────┐  │
│  │ Collector │  │     │  │ Collector │  │     │  │ Collector │  │
│  └─────┬─────┘  │     │  └─────┬─────┘  │     │  └─────┬─────┘  │
└────────┼────────┘     └────────┼────────┘     └────────┼────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │   PostgreSQL Database  │
                    │   (Shared Database)    │
                    └────────────────────────┘
```
