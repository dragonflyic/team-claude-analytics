"""Metrics calculation service."""

from datetime import datetime, timedelta
from typing import Any

from ..db import DatabaseClient

# Bot patterns to filter out from review metrics
BOT_PATTERNS = [
    "[bot]",
    "github-actions",
    "dependabot",
    "renovate",
    "claude",
    "copilot",
]


def is_bot_user(username: str) -> bool:
    """Check if a username appears to be a bot."""
    if not username:
        return False
    username_lower = username.lower()
    return any(pattern in username_lower for pattern in BOT_PATTERNS)


def hours_between(start: datetime | None, end: datetime | None) -> float | None:
    """Calculate hours between two timestamps."""
    if not start or not end:
        return None
    delta = end - start
    return delta.total_seconds() / 3600


def parse_review_timestamp(ts: str | None) -> datetime | None:
    """Parse GitHub timestamp string to datetime."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def get_human_review_times(pr: dict) -> tuple[datetime | None, datetime | None]:
    """Extract first human review and approval times from raw_data.

    Filters out bot reviewers to get accurate human review metrics.
    """
    raw_data = pr.get("raw_data") or {}
    reviews = raw_data.get("reviews") or []

    first_review_at = None
    approved_at = None

    # Sort reviews by timestamp
    sorted_reviews = sorted(reviews, key=lambda r: r.get("submitted_at") or "")

    for review in sorted_reviews:
        reviewer = review.get("user", {}).get("login", "")
        if is_bot_user(reviewer):
            continue

        submitted = parse_review_timestamp(review.get("submitted_at"))
        if not submitted:
            continue

        if first_review_at is None:
            first_review_at = submitted

        if review.get("state") == "APPROVED" and approved_at is None:
            approved_at = submitted

    return first_review_at, approved_at


def calculate_pr_cycle_time(pr: dict, filter_bots: bool = True) -> dict:
    """Calculate cycle time breakdown for a single PR.

    If filter_bots is True, uses human-only review times from raw_data.
    Otherwise uses the stored first_review_at/approved_at timestamps.
    """
    first_commit = pr.get("first_commit_at")
    created = pr.get("created_at")
    merged = pr.get("merged_at")

    if filter_bots:
        first_review, approved = get_human_review_times(pr)
    else:
        first_review = pr.get("first_review_at")
        approved = pr.get("approved_at")

    # Calculate hours before PR (first commit to PR creation)
    # If first commit is after PR creation (rebases/force-pushes), show None
    hours_before_pr = hours_between(first_commit, created)
    if hours_before_pr is not None and hours_before_pr < 0:
        hours_before_pr = None

    # For total time, use the earlier of first_commit or created as start
    if first_commit and created:
        start_time = min(first_commit, created)
    else:
        start_time = created or first_commit

    return {
        "pr_number": pr["pr_number"],
        "title": pr["title"],
        "author": pr["author_login"],
        "first_commit_at": first_commit,
        "created_at": created,
        "merged_at": merged,
        "hours_before_pr": hours_before_pr,
        "hours_to_first_review": hours_between(created, first_review),
        "hours_to_approval": hours_between(created, approved),  # Total time from creation to approval
        "hours_to_merge": hours_between(approved, merged),
        "total_hours": hours_between(start_time, merged),
    }


def get_cycle_time_metrics(
    db: DatabaseClient,
    repo: str | None = None,
    author: str | None = None,
    days: int = 30,
) -> dict:
    """Get aggregated cycle time metrics."""
    prs = db.get_prs(repo=repo, author=author, days=days, merged_only=True)

    if not prs:
        return {
            "count": 0,
            "avg_hours_before_pr": None,
            "avg_hours_to_first_review": None,
            "avg_hours_to_approval": None,
            "avg_hours_to_merge": None,
            "avg_total_hours": None,
            "prs_without_review_count": 0,
            "prs_without_review_pct": 0,
            "prs": [],
        }

    cycle_times = [calculate_pr_cycle_time(pr) for pr in prs]

    # Calculate averages, ignoring None values
    def avg(values: list[float | None]) -> float | None:
        valid = [v for v in values if v is not None]
        return sum(valid) / len(valid) if valid else None

    # Calculate percentage of PRs merged without any review
    prs_without_review = [ct for ct in cycle_times if ct["hours_to_first_review"] is None]
    prs_without_review_count = len(prs_without_review)
    prs_without_review_pct = (prs_without_review_count / len(prs) * 100) if prs else 0

    return {
        "count": len(prs),
        "avg_hours_before_pr": avg([ct["hours_before_pr"] for ct in cycle_times]),
        "avg_hours_to_first_review": avg([ct["hours_to_first_review"] for ct in cycle_times]),
        "avg_hours_to_approval": avg([ct["hours_to_approval"] for ct in cycle_times]),
        "avg_hours_to_merge": avg([ct["hours_to_merge"] for ct in cycle_times]),
        "avg_total_hours": avg([ct["total_hours"] for ct in cycle_times]),
        "prs_without_review_count": prs_without_review_count,
        "prs_without_review_pct": prs_without_review_pct,
        "prs": cycle_times,
    }


def get_velocity_metrics(
    db: DatabaseClient,
    repo: str | None = None,
    granularity: str = "week",
    days: int = 90,
) -> dict:
    """Get shipping velocity metrics (PRs merged per time period)."""
    prs = db.get_prs(repo=repo, days=days, merged_only=True)

    # Group by author and time period
    velocity_by_author: dict[str, dict[str, int]] = {}
    velocity_totals: dict[str, int] = {}

    for pr in prs:
        merged_at = pr.get("merged_at")
        if not merged_at:
            continue

        author = pr["author_login"]

        # Determine period key
        if granularity == "week":
            # ISO week start (Monday)
            week_start = merged_at - timedelta(days=merged_at.weekday())
            period_key = week_start.strftime("%Y-%m-%d")
        else:  # month
            period_key = merged_at.strftime("%Y-%m")

        # Update author velocity
        if author not in velocity_by_author:
            velocity_by_author[author] = {}
        velocity_by_author[author][period_key] = velocity_by_author[author].get(period_key, 0) + 1

        # Update totals
        velocity_totals[period_key] = velocity_totals.get(period_key, 0) + 1

    # Get sorted list of periods
    all_periods = sorted(set(velocity_totals.keys()))

    # Build per-author series
    author_series = []
    for author, periods in velocity_by_author.items():
        data = [periods.get(p, 0) for p in all_periods]
        total = sum(data)
        author_series.append({
            "author": author,
            "data": data,
            "total": total,
        })

    # Sort by total (most productive first)
    author_series.sort(key=lambda x: x["total"], reverse=True)

    return {
        "granularity": granularity,
        "periods": all_periods,
        "totals": [velocity_totals.get(p, 0) for p in all_periods],
        "by_author": author_series,
        "total_prs": len(prs),
    }


def get_summary_metrics(db: DatabaseClient, days: int = 30) -> dict:
    """Get summary metrics for the dashboard overview."""
    prs = db.get_prs(days=days)
    merged_prs = [pr for pr in prs if pr.get("merged_at")]

    # Calculate averages
    total_hours = []
    for pr in merged_prs:
        hrs = hours_between(pr.get("created_at"), pr.get("merged_at"))
        if hrs is not None:
            total_hours.append(hrs)

    avg_cycle_time = sum(total_hours) / len(total_hours) if total_hours else None

    # Count unique authors
    authors = set(pr["author_login"] for pr in prs)

    return {
        "total_prs": len(prs),
        "merged_prs": len(merged_prs),
        "open_prs": len([pr for pr in prs if pr["state"] == "open"]),
        "avg_cycle_time_hours": avg_cycle_time,
        "unique_authors": len(authors),
        "days": days,
    }
