"""HTML dashboard views."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..db import DatabaseClient
from ..services import metrics

router = APIRouter(tags=["dashboard"])

templates = Jinja2Templates(directory="dashboard/templates")


def get_db() -> DatabaseClient | None:
    """Get database client from app state (may be None)."""
    from ..main import app
    return app.state.db


def get_db_error() -> str | None:
    """Get database error message if any."""
    from ..main import app
    return app.state.db_error


def format_hours(hours: float | None) -> str:
    """Format hours as human-readable string."""
    if hours is None:
        return "N/A"
    if hours < 1:
        return f"{int(hours * 60)}m"
    if hours < 24:
        return f"{hours:.1f}h"
    days = hours / 24
    return f"{days:.1f}d"


@router.get("/", response_class=HTMLResponse)
async def dashboard_home(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    db: DatabaseClient | None = Depends(get_db),
    db_error: str | None = Depends(get_db_error),
):
    """Main dashboard view with summary metrics."""
    if db is None:
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "summary": None,
                "repos": [],
                "days": days,
                "format_hours": format_hours,
                "db_error": db_error,
            },
        )

    summary = metrics.get_summary_metrics(db, days=days)
    repos = db.get_repos()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "summary": summary,
            "repos": repos,
            "days": days,
            "format_hours": format_hours,
            "db_error": None,
        },
    )


@router.get("/velocity", response_class=HTMLResponse)
async def velocity_view(
    request: Request,
    repo: str | None = None,
    granularity: str = Query("week", regex="^(week|month)$"),
    days: int = Query(90, ge=1, le=365),
    db: DatabaseClient | None = Depends(get_db),
    db_error: str | None = Depends(get_db_error),
):
    """Shipping velocity charts."""
    if db is None:
        return templates.TemplateResponse(
            "velocity.html",
            {
                "request": request,
                "velocity": {"periods": [], "by_author": [], "total_prs": 0},
                "repos": [],
                "selected_repo": repo,
                "granularity": granularity,
                "days": days,
                "db_error": db_error,
            },
        )

    velocity = metrics.get_velocity_metrics(db, repo=repo, granularity=granularity, days=days)
    repos = db.get_repos()

    return templates.TemplateResponse(
        "velocity.html",
        {
            "request": request,
            "velocity": velocity,
            "repos": repos,
            "selected_repo": repo,
            "granularity": granularity,
            "days": days,
            "db_error": None,
        },
    )


@router.get("/cycle-time", response_class=HTMLResponse)
async def cycle_time_view(
    request: Request,
    repo: str | None = None,
    author: str | None = None,
    days: int = Query(30, ge=1, le=365),
    db: DatabaseClient | None = Depends(get_db),
    db_error: str | None = Depends(get_db_error),
):
    """PR cycle time breakdown view."""
    if db is None:
        return templates.TemplateResponse(
            "cycle_time.html",
            {
                "request": request,
                "cycle_time": {"count": 0, "prs": []},
                "repos": [],
                "authors": [],
                "selected_repo": repo,
                "selected_author": author,
                "days": days,
                "format_hours": format_hours,
                "db_error": db_error,
            },
        )

    cycle_time = metrics.get_cycle_time_metrics(db, repo=repo, author=author, days=days)
    repos = db.get_repos()
    authors = db.get_authors()

    return templates.TemplateResponse(
        "cycle_time.html",
        {
            "request": request,
            "cycle_time": cycle_time,
            "repos": repos,
            "authors": authors,
            "selected_repo": repo,
            "selected_author": author,
            "days": days,
            "format_hours": format_hours,
            "db_error": None,
        },
    )


# HTMX partials for dynamic updates

@router.get("/partials/summary", response_class=HTMLResponse)
async def partial_summary(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    db: DatabaseClient = Depends(get_db),
):
    """Partial template for summary cards (HTMX)."""
    summary = metrics.get_summary_metrics(db, days=days)

    return templates.TemplateResponse(
        "partials/summary_cards.html",
        {
            "request": request,
            "summary": summary,
            "format_hours": format_hours,
        },
    )
