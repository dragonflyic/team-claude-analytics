FROM python:3.12-slim

# Install Poetry
ENV POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1
RUN pip install poetry

WORKDIR /app

# Copy dependency files first for better layer caching
COPY pyproject.toml ./
RUN poetry install --no-root --only main

# Copy application code
COPY collector/ ./collector/

# Install the package
RUN poetry install --only main

# Create non-root user
RUN useradd -m -u 1000 collector
USER collector

# Create state directory
RUN mkdir -p /home/collector/.claude-collector

# Default environment variables
ENV CLAUDE_PROJECTS_PATH=/claude-projects \
    STATE_PATH=/home/collector/.claude-collector/state.json

ENTRYPOINT ["python", "-m", "collector.main"]
