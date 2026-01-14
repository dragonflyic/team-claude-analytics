"""Sync logic for pulling GitHub PR data into the database."""

import logging
from datetime import datetime, timedelta, timezone

from ..config import Config
from ..db import DatabaseClient
from .client import GitHubClient

logger = logging.getLogger(__name__)

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
    username_lower = username.lower()
    return any(pattern in username_lower for pattern in BOT_PATTERNS)


def parse_timestamp(ts: str | None) -> datetime | None:
    """Parse GitHub timestamp to datetime."""
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


async def sync_repo(
    github_client: GitHubClient,
    db_client: DatabaseClient,
    repo_full_name: str,
    days_back: int = 90,
) -> dict:
    """Sync all PRs from a repository.

    Returns stats about the sync.
    """
    owner, repo = repo_full_name.split("/")
    since = datetime.now(timezone.utc) - timedelta(days=days_back)

    stats = {"synced": 0, "errors": 0}

    logger.info(f"Syncing PRs from {repo_full_name} since {since.date()}")

    # Collect all PRs first to enable batch Claude chat lookup
    prs = [pr async for pr in github_client.get_pulls(owner, repo, state="all", since=since)]

    # Batch lookup first Claude chat timestamps for all branches
    branches = [pr["head"]["ref"] for pr in prs]
    first_claude_chats = db_client.get_first_claude_chat_for_branches(branches)

    for pr in prs:
        try:
            # Get detailed PR info (includes additions/deletions)
            detail = await github_client.get_pull_detail(owner, repo, pr["number"])

            # Get reviews to find first review and approval timestamps
            reviews = await github_client.get_pull_reviews(owner, repo, pr["number"])

            # Get commits to find first commit timestamp
            commits = await github_client.get_pull_commits(owner, repo, pr["number"])
            first_commit_at = None
            if commits:
                # Sort by committer date and get the earliest
                sorted_commits = sorted(
                    commits,
                    key=lambda c: c.get("commit", {}).get("committer", {}).get("date") or "",
                )
                if sorted_commits:
                    first_commit_date = sorted_commits[0].get("commit", {}).get("committer", {}).get("date")
                    first_commit_at = parse_timestamp(first_commit_date)

            # Store all reviews - filtering happens at analysis time
            first_review_at = None
            approved_at = None

            for review in sorted(reviews, key=lambda r: r["submitted_at"] or ""):
                submitted = parse_timestamp(review.get("submitted_at"))
                if not submitted:
                    continue

                if first_review_at is None:
                    first_review_at = submitted

                if review["state"] == "APPROVED" and approved_at is None:
                    approved_at = submitted

            # Determine state (GitHub doesn't have explicit 'merged' state)
            state = pr["state"]
            if pr.get("merged_at"):
                state = "merged"

            pr_data = {
                "repo_full_name": repo_full_name,
                "pr_number": pr["number"],
                "title": pr["title"],
                "author_login": pr["user"]["login"],
                "state": state,
                "draft": pr.get("draft", False),
                "created_at": parse_timestamp(pr["created_at"]),
                "first_commit_at": first_commit_at,
                "first_claude_chat_at": first_claude_chats.get(pr["head"]["ref"]),
                "first_review_at": first_review_at,
                "approved_at": approved_at,
                "merged_at": parse_timestamp(pr.get("merged_at")),
                "closed_at": parse_timestamp(pr.get("closed_at")),
                "additions": detail.get("additions"),
                "deletions": detail.get("deletions"),
                "changed_files": detail.get("changed_files"),
                "head_branch": pr["head"]["ref"],
                "base_branch": pr["base"]["ref"],
                "raw_data": {**detail, "reviews": reviews},  # Include reviews for analysis-time filtering
            }

            if db_client.upsert_pr(pr_data):
                stats["synced"] += 1
            else:
                stats["errors"] += 1

        except Exception as e:
            logger.error(f"Error syncing PR #{pr['number']}: {e}")
            stats["errors"] += 1

    logger.info(f"Sync complete for {repo_full_name}: {stats}")
    return stats


async def sync_all_repos(config: Config, db_client: DatabaseClient) -> dict:
    """Sync all configured repositories."""
    all_stats = {"total_synced": 0, "total_errors": 0, "repos": {}}

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
                all_stats["total_errors"] += stats["errors"]
            except Exception as e:
                logger.error(f"Failed to sync repo {repo}: {e}")
                all_stats["repos"][repo] = {"error": str(e)}
                all_stats["total_errors"] += 1

    return all_stats
