"""HTML dashboard views."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..db import DatabaseClient
from ..services import metrics

router = APIRouter(tags=["dashboard"])

templates = Jinja2Templates(directory="dashboard/templates")


def to_utc_iso(dt: datetime | None) -> str:
    """Convert datetime to UTC ISO format with Z suffix for JavaScript."""
    if dt is None:
        return ""
    # If timezone-aware, convert to UTC
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    # Return ISO format with Z suffix
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# Register the filter with Jinja2
templates.env.filters["utc_iso"] = to_utc_iso


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


@router.get("/pr/{repo_full_name:path}/{pr_number:int}", response_class=HTMLResponse)
async def pr_timeline_view(
    request: Request,
    repo_full_name: str,
    pr_number: int,
    db: DatabaseClient | None = Depends(get_db),
    db_error: str | None = Depends(get_db_error),
):
    """PR timeline detail view with Claude chats and review history."""
    if db is None:
        return templates.TemplateResponse(
            "pr_timeline.html",
            {
                "request": request,
                "pr": None,
                "timeline_events": [],
                "claude_sessions": [],
                "review_summary": "",
                "db_error": db_error,
                "not_found": False,
                "extract_content_text": metrics.extract_content_text,
                "get_display_role": metrics.get_display_role,
            },
        )

    # Fetch PR data
    pr = db.get_pr_by_repo_and_number(repo_full_name, pr_number)
    if not pr:
        return templates.TemplateResponse(
            "pr_timeline.html",
            {
                "request": request,
                "pr": None,
                "timeline_events": [],
                "claude_sessions": [],
                "review_summary": "",
                "db_error": None,
                "not_found": True,
                "extract_content_text": metrics.extract_content_text,
                "get_display_role": metrics.get_display_role,
            },
        )

    # Fetch Claude sessions - includes all messages from any session that ever touched the branch
    claude_sessions = []
    if pr.get("head_branch"):
        claude_sessions = db.get_claude_sessions_for_branch(pr["head_branch"])

    # Build timeline events
    timeline_events = metrics.build_pr_timeline(pr, claude_sessions)

    # Generate review summary
    review_summary = metrics.generate_review_summary(pr)

    return templates.TemplateResponse(
        "pr_timeline.html",
        {
            "request": request,
            "pr": pr,
            "timeline_events": timeline_events,
            "claude_sessions": claude_sessions,
            "review_summary": review_summary,
            "db_error": None,
            "not_found": False,
            "extract_content_text": metrics.extract_content_text,
            "get_display_role": metrics.get_display_role,
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
