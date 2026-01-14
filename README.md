# Team Claude Analytics

Shared team analytics for Claude usage. Collects Claude chat logs from developer machines and streams them to a shared PostgreSQL database.

## Components

- **Collector**: Python service that watches `~/.claude/projects` for log changes and streams entries to PostgreSQL
- **Terraform**: Infrastructure as code for provisioning RDS PostgreSQL on AWS

## Prerequisites

- Python 3.12+
- Poetry
- Docker (for containerized deployment)
- Terraform 1.0+ (for infrastructure)
- AWS CLI configured with credentials

## Quick Start (for developers)

Run this one-liner to install the collector on your machine:

```bash
curl -sSL https://raw.githubusercontent.com/dragonflyic/team-claude-analytics/main/install.sh | bash
```

It will prompt for the database password (ask your team lead).

---

## Infrastructure Setup (for admins)

### 1. Provision Infrastructure

```bash
cd terraform

# Copy and edit variables
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your settings

# Deploy
terraform init
terraform plan
terraform apply
```

After deployment, note the RDS endpoint from the outputs.

### 2. Run the Collector

#### Option A: Run Locally with Poetry

```bash
cd collector
poetry install

# Set environment variables
export DB_HOST=your-rds-endpoint.region.rds.amazonaws.com
export DB_PORT=5432
export DB_NAME=claude_logs
export DB_USER=claude_admin
export DB_PASSWORD=your-password

# Run
poetry run collector
```

#### Option B: Run with Docker (from public ECR)

```bash
docker run -d \
  --name claude-collector \
  --restart unless-stopped \
  -e DB_HOST=your-rds-endpoint.region.rds.amazonaws.com \
  -e DB_PASSWORD=your-password \
  -v ~/.claude/projects:/claude-projects:ro \
  -v ~/.claude-collector:/state \
  public.ecr.aws/z7t5p0k6/claude-log-collector:latest
```

#### Option C: Run with Docker Compose (local build)

```bash
# Copy and edit environment file
cp .env.example .env
# Edit .env with your RDS credentials

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

### Terraform Variables

See `terraform/terraform.tfvars.example` for available configuration options.

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
                    │   AWS RDS PostgreSQL   │
                    │   (Shared Database)    │
                    └────────────────────────┘
```
