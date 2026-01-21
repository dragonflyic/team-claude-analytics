"""FastAPI dashboard application."""

import asyncio
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import Config
from .db import DatabaseClient
from .github.sync import sync_all_repos
from .routers import api, dashboard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def run_sync(config: Config, db: DatabaseClient):
    """Run GitHub sync (called by scheduler in background thread)."""
    logger.info("Starting scheduled GitHub sync...")
    try:
        # Run the async sync in a new event loop since we're in a background thread
        stats = asyncio.run(sync_all_repos(config, db))
        logger.info(f"Sync complete: {stats['total_synced']} PRs synced")
    except Exception as e:
        logger.error(f"Sync failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Load config
    config = Config.from_env()
    app.state.config = config
    app.state.db = None
    app.state.db_error = None
    scheduler = None

    # Initialize database (gracefully handle missing config)
    db = DatabaseClient(config)
    try:
        db.connect()
        db.init_schema()
        app.state.db = db

        # Start background scheduler (runs jobs in separate threads to avoid blocking)
        scheduler = BackgroundScheduler()

        # Schedule initial sync to run shortly after startup (non-blocking)
        if config.github_token and config.github_repos:
            from datetime import datetime, timedelta
            scheduler.add_job(
                run_sync,
                "date",
                run_date=datetime.now() + timedelta(seconds=5),
                args=[config, db],
                id="github_sync_initial",
            )
            logger.info("Initial GitHub sync scheduled to run in 5 seconds")
        else:
            logger.warning("GitHub not configured, skipping sync")

        # Schedule recurring sync
        scheduler.add_job(
            run_sync,
            "interval",
            minutes=config.sync_interval_minutes,
            args=[config, db],
            id="github_sync",
        )
        scheduler.start()
        logger.info(f"Scheduler started, syncing every {config.sync_interval_minutes} minutes")

    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        app.state.db_error = str(e)

    yield

    # Cleanup
    if scheduler:
        scheduler.shutdown()
    if app.state.db:
        app.state.db.disconnect()
    logger.info("Application shutdown complete")


app = FastAPI(
    title="Developer Productivity Dashboard",
    description="Track PR cycle times and shipping velocity",
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory="dashboard/static"), name="static")

# Include routers
app.include_router(api.router)
app.include_router(dashboard.router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


def main():
    """Entry point for running the dashboard."""
    import uvicorn
    uvicorn.run(
        "dashboard.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
