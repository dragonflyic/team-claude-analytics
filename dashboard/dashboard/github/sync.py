"""Sync logic for pulling GitHub PR data into the database."""

import logging
from datetime import datetime, timedelta, timezone

from ..config import Config
from ..db import DatabaseClient
from .client import GitHubClient

logger = logging.getLogger(__name__)

# How long to keep re-fetching closed/merged PRs (in case of late reviews/comments)
STALE_THRESHOLD_HOURS = 24


def parse_timestamp(ts: str | None) -> datetime | None:
    """Parse GitHub timestamp to datetime."""
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def should_skip_pr(
    pr_number: int,
    github_state: str,
    github_updated_at: datetime,
    existing_prs: dict[int, dict],
) -> bool:
    """Determine if we should skip fetching this PR.

    Skip if:
    - PR exists in our DB
    - PR is in a terminal state (merged or closed)
    - PR hasn't been updated in the last 24 hours
    """
    if pr_number not in existing_prs:
        return False  # New PR, must fetch

    existing = existing_prs[pr_number]

    # If PR is open, always fetch (could have new activity)
    if github_state == "OPEN":
        return False

    # PR is merged or closed - check if it's been updated recently
    stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_THRESHOLD_HOURS)
    if github_updated_at > stale_cutoff:
        return False  # Recently updated, fetch it

    # Terminal state and not recently updated - skip
    return True


def transform_graphql_pr(pr: dict, repo_full_name: str, first_claude_chat: datetime | None) -> dict:
    """Transform GraphQL PR response to our database schema."""
    # Extract reviews
    reviews = pr.get("reviews", {}).get("nodes", [])

    # Find first review and approval timestamps
    first_review_at = None
    approved_at = None
    for review in sorted(reviews, key=lambda r: r.get("submittedAt") or ""):
        submitted = parse_timestamp(review.get("submittedAt"))
        if not submitted:
            continue

        if first_review_at is None:
            first_review_at = submitted

        if review.get("state") == "APPROVED" and approved_at is None:
            approved_at = submitted

    # Extract first commit timestamp
    commits = pr.get("commits", {}).get("nodes", [])
    first_commit_at = None
    if commits:
        commit_dates = [
            parse_timestamp(c.get("commit", {}).get("committedDate"))
            for c in commits
            if c.get("commit", {}).get("committedDate")
        ]
        if commit_dates:
            first_commit_at = min(commit_dates)

    # Map GraphQL state to our state
    state = pr.get("state", "").lower()
    if pr.get("mergedAt"):
        state = "merged"

    return {
        "repo_full_name": repo_full_name,
        "pr_number": pr["number"],
        "title": pr.get("title"),
        "author_login": pr.get("author", {}).get("login", "unknown"),
        "state": state,
        "draft": pr.get("isDraft", False),
        "created_at": parse_timestamp(pr.get("createdAt")),
        "first_commit_at": first_commit_at,
        "first_claude_chat_at": first_claude_chat,
        "first_review_at": first_review_at,
        "approved_at": approved_at,
        "merged_at": parse_timestamp(pr.get("mergedAt")),
        "closed_at": parse_timestamp(pr.get("closedAt")),
        "additions": pr.get("additions"),
        "deletions": pr.get("deletions"),
        "changed_files": pr.get("changedFiles"),
        "head_branch": pr.get("headRefName"),
        "base_branch": pr.get("baseRefName"),
        "raw_data": {"reviews": reviews},
    }


async def sync_repo(
    github_client: GitHubClient,
    db_client: DatabaseClient,
    repo_full_name: str,
    days_back: int = 90,
) -> dict:
    """Sync all PRs from a repository using GraphQL.

    Uses incremental sync - skips merged/closed PRs that haven't been
    updated in the last 24 hours.

    Returns stats about the sync.
    """
    owner, repo = repo_full_name.split("/")
    since = datetime.now(timezone.utc) - timedelta(days=days_back)

    stats = {"synced": 0, "skipped": 0, "errors": 0, "api_calls": 0}

    logger.info(f"Syncing PRs from {repo_full_name} since {since.date()}")

    # Get existing PRs for incremental sync
    existing_prs = db_client.get_existing_prs_for_repo(repo_full_name)
    logger.info(f"Found {len(existing_prs)} existing PRs in database")

    # Collect PRs that need syncing
    prs_to_sync = []
    total_prs_fetched = 0
    async for pr in github_client.get_pulls_graphql(owner, repo, since=since):
        total_prs_fetched += 1
        github_state = pr.get("state", "")
        github_updated_at = parse_timestamp(pr.get("updatedAt")) or datetime.now(timezone.utc)

        if should_skip_pr(pr["number"], github_state, github_updated_at, existing_prs):
            stats["skipped"] += 1
            continue

        prs_to_sync.append(pr)

    # GraphQL fetches 50 PRs per request
    stats["api_calls"] = (total_prs_fetched + 49) // 50  # Ceiling division

    logger.info(f"Will sync {len(prs_to_sync)} PRs, skipped {stats['skipped']} unchanged ({stats['api_calls']} API calls)")

    # Batch lookup Claude chat timestamps for branches we're syncing
    branches = [pr.get("headRefName") for pr in prs_to_sync if pr.get("headRefName")]
    first_claude_chats = db_client.get_first_claude_chat_for_branches(branches)

    # Process PRs
    for pr in prs_to_sync:
        try:
            pr_data = transform_graphql_pr(
                pr,
                repo_full_name,
                first_claude_chats.get(pr.get("headRefName")),
            )

            if db_client.upsert_pr(pr_data):
                stats["synced"] += 1
            else:
                stats["errors"] += 1

        except Exception as e:
            logger.error(f"Error syncing PR #{pr.get('number')}: {e}")
            stats["errors"] += 1

    logger.info(f"Sync complete for {repo_full_name}: {stats}")
    return stats


async def sync_all_repos(config: Config, db_client: DatabaseClient) -> dict:
    """Sync all configured repositories."""
    all_stats = {"total_synced": 0, "total_skipped": 0, "total_errors": 0, "total_api_calls": 0, "repos": {}}

    if not config.github_token:
        logger.warning("No GitHub token configured, skipping sync")
        return all_stats

    if not config.github_repos:
        logger.warning("No GitHub repos configured, skipping sync")
        return all_stats

    async with GitHubClient(config.github_token) as github:
        for repo in config.github_repos:
            try:
                stats = await sync_repo(github, db_client, repo)
                all_stats["repos"][repo] = stats
                all_stats["total_synced"] += stats["synced"]
                all_stats["total_skipped"] += stats["skipped"]
                all_stats["total_errors"] += stats["errors"]
                all_stats["total_api_calls"] += stats["api_calls"]
            except Exception as e:
                logger.error(f"Failed to sync repo {repo}: {e}")
                all_stats["repos"][repo] = {"error": str(e)}
                all_stats["total_errors"] += 1

    return all_stats
