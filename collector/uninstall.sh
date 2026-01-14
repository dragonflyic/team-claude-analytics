#!/bin/bash
set -e

# Claude Log Collector Uninstaller
# Usage: curl -sSL https://raw.githubusercontent.com/dragonflyic/team-claude-analytics/main/collector/uninstall.sh | bash

CONTAINER_NAME="claude-log-collector"

echo "=== Claude Log Collector Uninstaller ==="
echo ""

# Stop and remove collector
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Stopping and removing collector..."
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
else
    echo "Collector container not found."
fi

# Stop and remove watchtower
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}-watchtower$"; then
    echo "Stopping and removing watchtower..."
    docker stop "${CONTAINER_NAME}-watchtower" 2>/dev/null || true
    docker rm "${CONTAINER_NAME}-watchtower" 2>/dev/null || true
else
    echo "Watchtower container not found."
fi

# Ask about removing state
echo ""
echo "Do you want to remove the collector state directory?"
echo "This contains the record of which logs have been uploaded."
echo "If you reinstall later, logs will be re-uploaded from the beginning."
echo ""
echo "Remove ~/.claude-collector? [y/N]"
read -r REMOVE_STATE < /dev/tty

if [[ "$REMOVE_STATE" =~ ^[Yy]$ ]]; then
    rm -rf "$HOME/.claude-collector"
    echo "State directory removed."
else
    echo "State directory kept."
fi

# Ask about removing images
echo ""
echo "Do you want to remove the Docker images? [y/N]"
read -r REMOVE_IMAGES < /dev/tty

if [[ "$REMOVE_IMAGES" =~ ^[Yy]$ ]]; then
    docker rmi public.ecr.aws/z7t5p0k6/claude-log-collector:latest 2>/dev/null || true
    docker rmi containrrr/watchtower 2>/dev/null || true
    echo "Images removed."
else
    echo "Images kept."
fi

echo ""
echo "=== Uninstall complete ==="
