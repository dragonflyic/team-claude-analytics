FROM python:3.12-slim

WORKDIR /app

# Install poetry
RUN pip install --no-cache-dir poetry

# Copy dependency files
COPY pyproject.toml poetry.lock* ./

# Install dependencies (no dev deps, no virtualenv)
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi

# Copy application code
COPY dashboard ./dashboard

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"

# Run the application
CMD ["uvicorn", "dashboard.main:app", "--host", "0.0.0.0", "--port", "8000"]
