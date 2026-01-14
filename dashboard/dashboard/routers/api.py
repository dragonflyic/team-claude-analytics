"""JSON API endpoints for metrics."""

from fastapi import APIRouter, Depends, HTTPException, Query

from ..db import DatabaseClient
from ..services import metrics

router = APIRouter(prefix="/api", tags=["api"])


def get_db() -> DatabaseClient:
    """Get database client from app state."""
    from ..main import app
    if app.state.db is None:
        raise HTTPException(
            status_code=503,
            detail=f"Database not connected: {app.state.db_error or 'Not configured'}",
        )
    return app.state.db


@router.get("/metrics/summary")
async def get_summary(
    days: int = Query(30, ge=1, le=365),
    db: DatabaseClient = Depends(get_db),
):
    """Get summary metrics for dashboard overview."""
    return metrics.get_summary_metrics(db, days=days)


@router.get("/metrics/cycle-time")
async def get_cycle_time(
    repo: str | None = None,
    author: str | None = None,
    days: int = Query(30, ge=1, le=365),
    db: DatabaseClient = Depends(get_db),
):
    """Get PR cycle time breakdown metrics."""
    return metrics.get_cycle_time_metrics(db, repo=repo, author=author, days=days)


@router.get("/metrics/velocity")
async def get_velocity(
    repo: str | None = None,
    granularity: str = Query("week", regex="^(week|month)$"),
    days: int = Query(90, ge=1, le=365),
    db: DatabaseClient = Depends(get_db),
):
    """Get shipping velocity metrics (PRs merged per time period)."""
    return metrics.get_velocity_metrics(db, repo=repo, granularity=granularity, days=days)


@router.get("/repos")
async def list_repos(db: DatabaseClient = Depends(get_db)):
    """Get list of repositories with PR data."""
    return {"repos": db.get_repos()}


@router.get("/authors")
async def list_authors(db: DatabaseClient = Depends(get_db)):
    """Get list of PR authors."""
    return {"authors": db.get_authors()}


@router.get("/prs")
async def list_prs(
    repo: str | None = None,
    author: str | None = None,
    days: int = Query(30, ge=1, le=365),
    merged_only: bool = False,
    db: DatabaseClient = Depends(get_db),
):
    """List pull requests with optional filters."""
    prs = db.get_prs(repo=repo, author=author, days=days, merged_only=merged_only)
    return {"prs": prs, "count": len(prs)}
