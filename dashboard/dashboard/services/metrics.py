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
    first_claude_chat = pr.get("first_claude_chat_at")
    first_commit = pr.get("first_commit_at")
    created = pr.get("created_at")
    merged = pr.get("merged_at")

    if filter_bots:
        first_review, approved = get_human_review_times(pr)
    else:
        first_review = pr.get("first_review_at")
        approved = pr.get("approved_at")

    # Calculate hours from first Claude chat to first commit
    # If chat is after commit (started using Claude mid-project), show None
    hours_before_first_commit = hours_between(first_claude_chat, first_commit)
    if hours_before_first_commit is not None and hours_before_first_commit < 0:
        hours_before_first_commit = None

    # Calculate hours before PR (first commit to PR creation)
    # If first commit is after PR creation (rebases/force-pushes), show None
    hours_before_pr = hours_between(first_commit, created)
    if hours_before_pr is not None and hours_before_pr < 0:
        hours_before_pr = None

    # For total time, use the earliest available timestamp as start
    timestamps = [t for t in [first_claude_chat, first_commit, created] if t is not None]
    start_time = min(timestamps) if timestamps else None

    return {
        "pr_number": pr["pr_number"],
        "repo_full_name": pr.get("repo_full_name"),
        "title": pr["title"],
        "author": pr["author_login"],
        "first_claude_chat_at": first_claude_chat,
        "first_commit_at": first_commit,
        "created_at": created,
        "merged_at": merged,
        "hours_before_first_commit": hours_before_first_commit,
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
            "avg_hours_before_first_commit": None,
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
        "avg_hours_before_first_commit": avg([ct["hours_before_first_commit"] for ct in cycle_times]),
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


def get_display_role(msg: dict) -> str:
    """Determine the display role for a message.

    Returns a human-friendly label:
    - "You" for actual human input
    - "Claude" for assistant responses
    - "System" for meta/system messages
    - "Tool Output" for tool results and command output
    - "Command" for slash commands
    - "Agent" for sub-agent prompts (Task tool)
    """
    msg_type = msg.get("message_type") or msg.get("type")
    role = msg.get("role")
    content = msg.get("content", "")

    # Assistant messages
    if msg_type == "assistant" or role == "assistant":
        return "Claude"

    # For user-type messages, check various indicators
    if msg_type == "user" or role == "user":
        # Sub-agent prompts (Task tool sending prompt to explore/other agents)
        if msg.get("agent_id") or msg.get("is_sidechain"):
            return "Agent"

        # Meta/system messages
        if msg.get("is_meta"):
            return "System"

        # Tool results (from API tool_use responses)
        if msg.get("content_type") == "tool_result":
            return "Tool Output"

        # Check string content for XML tags
        content_str = str(content) if content else ""

        if content_str.startswith("<local-command-caveat>"):
            return "System"
        if content_str.startswith("<local-command-stdout>"):
            return "Tool Output"
        if content_str.startswith("<command-name>"):
            return "Command"
        if content_str.startswith("<"):
            return "System"  # Other XML-tagged content

        # Plain text = actual human input
        return "You"

    # System messages
    if msg_type == "system":
        return "System"

    return msg_type or role or "Unknown"


def extract_content_text(content: Any) -> str:
    """Extract readable text from Claude message content.

    Content can be:
    - A string (simple case)
    - A list of content blocks: [{"type": "text", "text": "..."}, ...]
    - A dict with various structures
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    texts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    texts.append(f"[Tool: {block.get('name', 'unknown')}]")
                elif block.get("type") == "tool_result":
                    texts.append("[Tool result]")
        return "\n".join(texts) if texts else str(content)
    if isinstance(content, dict):
        if "text" in content:
            return content["text"]
        return str(content)
    return str(content)


def extract_review_events(pr: dict) -> list[dict]:
    """Extract review events from raw_data.reviews.

    Returns sorted list of review events with:
    - reviewer: str
    - state: str (COMMENTED, APPROVED, CHANGES_REQUESTED, DISMISSED)
    - body: str
    - submitted_at: datetime
    - is_bot: bool
    """
    raw_data = pr.get("raw_data") or {}
    reviews = raw_data.get("reviews") or []

    events = []
    for review in reviews:
        reviewer = review.get("user", {}).get("login", "unknown")
        submitted = parse_review_timestamp(review.get("submitted_at"))
        if not submitted:
            continue

        events.append({
            "reviewer": reviewer,
            "state": review.get("state", "COMMENTED"),
            "body": review.get("body") or "",
            "submitted_at": submitted,
            "is_bot": is_bot_user(reviewer),
        })

    # Sort by timestamp
    events.sort(key=lambda e: e["submitted_at"])
    return events


def format_time_delta(seconds: float) -> str:
    """Format a time delta in seconds to human-readable form."""
    if seconds < 60:
        secs = int(seconds)
        return f"{secs} sec later" if secs == 1 else f"{secs} secs later"
    elif seconds < 3600:
        mins = int(seconds / 60)
        return f"{mins} min later" if mins == 1 else f"{mins} mins later"
    elif seconds < 86400:
        hours = seconds / 3600
        if hours < 1.5:
            return "1 hour later"
        return f"{hours:.1f} hours later".replace(".0 ", " ")
    else:
        days = seconds / 86400
        if days < 1.5:
            return "1 day later"
        return f"{days:.1f} days later".replace(".0 ", " ")


def build_pr_timeline(pr: dict, claude_sessions: list[dict]) -> list[dict]:
    """Build a unified timeline of all PR events.

    Event types:
    - 'claude_session': Claude chat session started
    - 'first_commit': First commit on branch
    - 'pr_opened': PR created
    - 'review': Review submitted
    - 'merged': PR merged

    Each event has:
    - type: str
    - timestamp: datetime
    - title: str (display text)
    - detail: dict (type-specific data)
    - expandable: bool
    - time_delta: str (relative time from previous event)
    """
    events = []

    # Add Claude session events
    for session in claude_sessions:
        events.append({
            "type": "claude_session",
            "timestamp": session["first_message_at"],
            "title": f"Claude session ({session['message_count']} messages)",
            "detail": session,
            "expandable": True,
        })

    # Add first commit
    if pr.get("first_commit_at"):
        events.append({
            "type": "first_commit",
            "timestamp": pr["first_commit_at"],
            "title": "First commit",
            "detail": {},
            "expandable": False,
        })

    # Add PR opened
    if pr.get("created_at"):
        events.append({
            "type": "pr_opened",
            "timestamp": pr["created_at"],
            "title": "PR opened",
            "detail": {"draft": pr.get("draft", False)},
            "expandable": False,
        })

    # Add review events
    review_events = extract_review_events(pr)
    for review in review_events:
        state_label = {
            "APPROVED": "Approved",
            "CHANGES_REQUESTED": "Changes requested",
            "COMMENTED": "Commented",
            "DISMISSED": "Review dismissed",
        }.get(review["state"], review["state"])

        events.append({
            "type": "review",
            "timestamp": review["submitted_at"],
            "title": f"{review['reviewer']} - {state_label}",
            "detail": review,
            "expandable": bool(review["body"]),
        })

    # Add merged event
    if pr.get("merged_at"):
        events.append({
            "type": "merged",
            "timestamp": pr["merged_at"],
            "title": "PR merged",
            "detail": {},
            "expandable": False,
        })

    # Sort all events by timestamp
    events.sort(key=lambda e: e["timestamp"])

    # Add time deltas relative to previous event
    for i, event in enumerate(events):
        if i == 0:
            event["time_delta"] = "Start"
        else:
            prev_ts = events[i - 1]["timestamp"]
            curr_ts = event["timestamp"]
            delta_seconds = (curr_ts - prev_ts).total_seconds()
            event["time_delta"] = format_time_delta(delta_seconds)

    return events


def generate_review_summary(pr: dict) -> str:
    """Generate a summary of PR commentary.

    Returns markdown-formatted summary with:
    - Count of approvals, comments, change requests
    - List of reviewers
    - Key feedback themes
    """
    review_events = extract_review_events(pr)
    human_reviews = [r for r in review_events if not r["is_bot"]]

    if not human_reviews:
        return "No human reviews on this PR."

    # Count by state
    approvals = [r for r in human_reviews if r["state"] == "APPROVED"]
    changes_requested = [r for r in human_reviews if r["state"] == "CHANGES_REQUESTED"]
    comments = [r for r in human_reviews if r["state"] == "COMMENTED"]

    # Unique reviewers
    reviewers = sorted(set(r["reviewer"] for r in human_reviews))

    # Build summary
    parts = []

    # Reviewer list
    parts.append(f"**Reviewers:** {', '.join(reviewers)}")

    # Counts
    counts = []
    if approvals:
        counts.append(f"{len(approvals)} approval{'s' if len(approvals) > 1 else ''}")
    if changes_requested:
        counts.append(f"{len(changes_requested)} change request{'s' if len(changes_requested) > 1 else ''}")
    if comments:
        counts.append(f"{len(comments)} comment{'s' if len(comments) > 1 else ''}")

    if counts:
        parts.append(f"**Activity:** {', '.join(counts)}")

    # Look for common keywords in bodies
    all_bodies = " ".join(r["body"].lower() for r in human_reviews if r["body"])
    keywords_found = []
    keyword_map = {
        "lgtm": "LGTM",
        "ship it": "Ship it",
        "nit": "Minor nits",
        "typo": "Typo fixes",
        "test": "Testing feedback",
        "security": "Security concerns",
        "performance": "Performance considerations",
    }
    for keyword, label in keyword_map.items():
        if keyword in all_bodies:
            keywords_found.append(label)

    if keywords_found:
        parts.append(f"**Themes:** {', '.join(keywords_found)}")

    return "\n\n".join(parts)
