#!/bin/bash
set -e

# Claude Log Collector Installer
# Usage: curl -sSL https://raw.githubusercontent.com/dragonflyic/team-claude-analytics/main/install.sh | bash

CONTAINER_NAME="claude-log-collector"
IMAGE="public.ecr.aws/z7t5p0k6/claude-log-collector:latest"
DB_HOST="claude-analytics-postgres.c4nwk0i2cvb0.us-east-1.rds.amazonaws.com"

echo "=== Claude Log Collector Installer ==="
echo ""

# Check for Docker
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed. Please install Docker first."
    echo "  macOS: brew install --cask docker"
    exit 1
fi

# Check if Docker is running
if ! docker info &> /dev/null; then
    echo "Error: Docker is not running. Please start Docker and try again."
    exit 1
fi

# Check if containers already exist
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Existing collector found. Stopping and removing..."
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
fi

if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}-watchtower$"; then
    echo "Existing watchtower found. Stopping and removing..."
    docker stop "${CONTAINER_NAME}-watchtower" 2>/dev/null || true
    docker rm "${CONTAINER_NAME}-watchtower" 2>/dev/null || true
fi

# Prompt for password (read from /dev/tty for curl|bash compatibility)
echo "Enter the database password (ask your team lead if you don't have it):"
read -s DB_PASSWORD < /dev/tty
echo ""

if [ -z "$DB_PASSWORD" ]; then
    echo "Error: Password cannot be empty."
    exit 1
fi

# Pull latest image
echo "Pulling latest collector image..."
docker pull "$IMAGE"

# Run collector container
echo "Starting collector..."
docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    -e DB_HOST="$DB_HOST" \
    -e DB_PASSWORD="$DB_PASSWORD" \
    -v "$HOME/.claude/projects:/claude-projects:ro" \
    -v "$HOME/.claude-collector:/home/collector/.claude-collector" \
    "$IMAGE"

# Run watchtower for auto-updates (checks hourly)
echo "Starting watchtower for auto-updates..."
docker run -d \
    --name "${CONTAINER_NAME}-watchtower" \
    --restart unless-stopped \
    -v /var/run/docker.sock:/var/run/docker.sock \
    containrrr/watchtower \
    --cleanup --interval 3600 \
    "$CONTAINER_NAME"

echo ""
echo "=== Installation complete! ==="
echo ""
echo "The collector is now running and will automatically:"
echo "  - Stream your Claude chat logs to the team database"
echo "  - Start on boot (unless you stop it)"
echo "  - Resume from where it left off if restarted"
echo "  - Auto-update hourly via Watchtower"
echo ""
echo "Useful commands:"
echo "  docker logs -f $CONTAINER_NAME                # View collector logs"
echo "  docker logs ${CONTAINER_NAME}-watchtower      # View update logs"
echo ""
echo "To manually update now, run this installer again."
