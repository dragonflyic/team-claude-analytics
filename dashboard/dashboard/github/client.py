"""GitHub API client for fetching PR data."""

import logging
from datetime import datetime
from typing import Any, AsyncIterator

import httpx

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class GitHubClient:
    """Async client for GitHub REST API."""

    def __init__(self, token: str):
        self.token = token
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "GitHubClient":
        self._client = httpx.AsyncClient(
            base_url=GITHUB_API_BASE,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()

    async def _paginate(self, url: str, params: dict | None = None) -> AsyncIterator[dict]:
        """Paginate through GitHub API results."""
        params = params or {}
        params.setdefault("per_page", 100)

        while url:
            response = await self._client.get(url, params=params)
            response.raise_for_status()

            for item in response.json():
                yield item

            # Get next page from Link header
            link_header = response.headers.get("Link", "")
            url = None
            params = {}  # Clear params for subsequent requests (they're in the URL)

            for link in link_header.split(","):
                if 'rel="next"' in link:
                    url = link.split(";")[0].strip().strip("<>")
                    break

    async def get_pulls(
        self,
        owner: str,
        repo: str,
        state: str = "all",
        since: datetime | None = None,
    ) -> AsyncIterator[dict]:
        """Fetch pull requests for a repository."""
        url = f"/repos/{owner}/{repo}/pulls"
        params = {"state": state, "sort": "updated", "direction": "desc"}

        async for pr in self._paginate(url, params):
            # Stop if we've gone past our time window
            if since:
                updated_at = datetime.fromisoformat(pr["updated_at"].replace("Z", "+00:00"))
                if updated_at < since:
                    return

            yield pr

    async def get_pull_reviews(self, owner: str, repo: str, pr_number: int) -> list[dict]:
        """Fetch reviews for a specific pull request."""
        url = f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews"

        reviews = []
        async for review in self._paginate(url):
            reviews.append(review)

        return reviews

    async def get_pull_detail(self, owner: str, repo: str, pr_number: int) -> dict:
        """Fetch detailed info for a single PR (includes additions/deletions)."""
        url = f"/repos/{owner}/{repo}/pulls/{pr_number}"
        response = await self._client.get(url)
        response.raise_for_status()
        return response.json()

    async def get_pull_commits(self, owner: str, repo: str, pr_number: int) -> list[dict]:
        """Fetch commits for a specific pull request."""
        url = f"/repos/{owner}/{repo}/pulls/{pr_number}/commits"
        commits = []
        async for commit in self._paginate(url):
            commits.append(commit)
        return commits
