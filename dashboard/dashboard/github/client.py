"""GitHub API client for fetching PR data."""

import logging
from datetime import datetime
from typing import Any, AsyncIterator

import httpx

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"


class GitHubClient:
    """Async client for GitHub REST and GraphQL APIs."""

    def __init__(self, token: str):
        self.token = token
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "GitHubClient":
        self._client = httpx.AsyncClient(
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

    async def _graphql(self, query: str, variables: dict | None = None) -> dict:
        """Execute a GraphQL query."""
        response = await self._client.post(
            GITHUB_GRAPHQL_URL,
            json={"query": query, "variables": variables or {}},
        )
        response.raise_for_status()
        result = response.json()

        if "errors" in result:
            raise Exception(f"GraphQL errors: {result['errors']}")

        return result["data"]

    async def get_pulls_graphql(
        self,
        owner: str,
        repo: str,
        since: datetime | None = None,
        batch_size: int = 50,
    ) -> AsyncIterator[dict]:
        """Fetch pull requests with reviews and commits using GraphQL.

        This is much more efficient than REST - fetches PRs with all their
        reviews and commits in batched queries instead of N+1 calls.
        """
        query = """
        query($owner: String!, $repo: String!, $cursor: String, $batchSize: Int!) {
          repository(owner: $owner, name: $repo) {
            pullRequests(
              first: $batchSize,
              after: $cursor,
              orderBy: {field: UPDATED_AT, direction: DESC}
            ) {
              pageInfo {
                hasNextPage
                endCursor
              }
              nodes {
                number
                title
                state
                isDraft
                createdAt
                updatedAt
                mergedAt
                closedAt
                additions
                deletions
                changedFiles
                headRefName
                baseRefName
                author {
                  login
                }
                reviews(first: 50) {
                  nodes {
                    state
                    submittedAt
                    author {
                      login
                    }
                  }
                }
                commits(first: 100) {
                  nodes {
                    commit {
                      committedDate
                      authoredDate
                    }
                  }
                }
              }
            }
          }
        }
        """

        cursor = None
        while True:
            data = await self._graphql(query, {
                "owner": owner,
                "repo": repo,
                "cursor": cursor,
                "batchSize": batch_size,
            })

            pr_data = data["repository"]["pullRequests"]

            for pr in pr_data["nodes"]:
                # Stop if we've gone past our time window
                if since and pr["updatedAt"]:
                    updated_at = datetime.fromisoformat(pr["updatedAt"].replace("Z", "+00:00"))
                    if updated_at < since:
                        return

                yield pr

            # Check for more pages
            if not pr_data["pageInfo"]["hasNextPage"]:
                break
            cursor = pr_data["pageInfo"]["endCursor"]

    # Keep REST methods for backwards compatibility and specific use cases
    async def _paginate(self, url: str, params: dict | None = None) -> AsyncIterator[dict]:
        """Paginate through GitHub API results."""
        params = params or {}
        params.setdefault("per_page", 100)

        while url:
            response = await self._client.get(GITHUB_API_BASE + url if not url.startswith("http") else url, params=params)
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
        """Fetch pull requests for a repository (REST API)."""
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
        """Fetch reviews for a specific pull request (REST API)."""
        url = f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews"

        reviews = []
        async for review in self._paginate(url):
            reviews.append(review)

        return reviews

    async def get_pull_detail(self, owner: str, repo: str, pr_number: int) -> dict:
        """Fetch detailed info for a single PR (REST API)."""
        url = f"/repos/{owner}/{repo}/pulls/{pr_number}"
        response = await self._client.get(GITHUB_API_BASE + url)
        response.raise_for_status()
        return response.json()

    async def get_pull_commits(self, owner: str, repo: str, pr_number: int) -> list[dict]:
        """Fetch commits for a specific pull request (REST API)."""
        url = f"/repos/{owner}/{repo}/pulls/{pr_number}/commits"
        commits = []
        async for commit in self._paginate(url):
            commits.append(commit)
        return commits
