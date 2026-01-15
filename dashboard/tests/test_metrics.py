"""Tests for metrics service."""

import pytest
from datetime import datetime, timezone

from dashboard.services.metrics import extract_review_events, get_human_review_times


class TestExtractReviewEvents:
    """Tests for extract_review_events function."""

    def test_graphql_format_reviews(self):
        """Test that GraphQL format reviews are correctly extracted.

        GraphQL returns reviews with:
        - 'author' instead of 'user'
        - 'submittedAt' (camelCase) instead of 'submitted_at' (snake_case)

        This was the bug: the code expected REST format but received GraphQL format.
        """
        pr = {
            "raw_data": {
                "reviews": [
                    {
                        "state": "COMMENTED",
                        "author": {"login": "reviewer1"},
                        "submittedAt": "2026-01-15T10:00:00Z",
                    },
                    {
                        "state": "APPROVED",
                        "author": {"login": "reviewer2"},
                        "submittedAt": "2026-01-15T12:00:00Z",
                    },
                ]
            }
        }

        events = extract_review_events(pr)

        assert len(events) == 2

        # First review
        assert events[0]["reviewer"] == "reviewer1"
        assert events[0]["state"] == "COMMENTED"
        assert events[0]["submitted_at"] == datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        assert events[0]["is_bot"] is False

        # Second review (approved)
        assert events[1]["reviewer"] == "reviewer2"
        assert events[1]["state"] == "APPROVED"
        assert events[1]["submitted_at"] == datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    def test_rest_format_reviews(self):
        """Test that REST API format reviews still work (backward compatibility).

        REST API returns reviews with:
        - 'user' object with 'login'
        - 'submitted_at' (snake_case)
        """
        pr = {
            "raw_data": {
                "reviews": [
                    {
                        "state": "APPROVED",
                        "user": {"login": "reviewer1"},
                        "submitted_at": "2026-01-15T10:00:00Z",
                        "body": "LGTM!",
                    },
                ]
            }
        }

        events = extract_review_events(pr)

        assert len(events) == 1
        assert events[0]["reviewer"] == "reviewer1"
        assert events[0]["state"] == "APPROVED"
        assert events[0]["body"] == "LGTM!"

    def test_empty_reviews(self):
        """Test handling of PR with no reviews."""
        pr = {"raw_data": {"reviews": []}}
        events = extract_review_events(pr)
        assert events == []

    def test_no_raw_data(self):
        """Test handling of PR with no raw_data."""
        pr = {}
        events = extract_review_events(pr)
        assert events == []

    def test_null_raw_data(self):
        """Test handling of PR with null raw_data."""
        pr = {"raw_data": None}
        events = extract_review_events(pr)
        assert events == []

    def test_bot_reviewer_detection(self):
        """Test that bot reviewers are correctly identified."""
        pr = {
            "raw_data": {
                "reviews": [
                    {
                        "state": "APPROVED",
                        "author": {"login": "dependabot[bot]"},
                        "submittedAt": "2026-01-15T10:00:00Z",
                    },
                    {
                        "state": "APPROVED",
                        "author": {"login": "human-reviewer"},
                        "submittedAt": "2026-01-15T11:00:00Z",
                    },
                ]
            }
        }

        events = extract_review_events(pr)

        assert len(events) == 2
        assert events[0]["reviewer"] == "dependabot[bot]"
        assert events[0]["is_bot"] is True
        assert events[1]["reviewer"] == "human-reviewer"
        assert events[1]["is_bot"] is False

    def test_reviews_sorted_by_timestamp(self):
        """Test that reviews are sorted by timestamp."""
        pr = {
            "raw_data": {
                "reviews": [
                    {
                        "state": "APPROVED",
                        "author": {"login": "late-reviewer"},
                        "submittedAt": "2026-01-15T15:00:00Z",
                    },
                    {
                        "state": "COMMENTED",
                        "author": {"login": "early-reviewer"},
                        "submittedAt": "2026-01-15T09:00:00Z",
                    },
                ]
            }
        }

        events = extract_review_events(pr)

        assert len(events) == 2
        assert events[0]["reviewer"] == "early-reviewer"
        assert events[1]["reviewer"] == "late-reviewer"

    def test_review_missing_timestamp_skipped(self):
        """Test that reviews without timestamps are skipped."""
        pr = {
            "raw_data": {
                "reviews": [
                    {
                        "state": "APPROVED",
                        "author": {"login": "reviewer1"},
                        # No submittedAt
                    },
                    {
                        "state": "APPROVED",
                        "author": {"login": "reviewer2"},
                        "submittedAt": "2026-01-15T10:00:00Z",
                    },
                ]
            }
        }

        events = extract_review_events(pr)

        assert len(events) == 1
        assert events[0]["reviewer"] == "reviewer2"

    def test_review_missing_author_uses_unknown(self):
        """Test that reviews without author default to 'unknown'."""
        pr = {
            "raw_data": {
                "reviews": [
                    {
                        "state": "APPROVED",
                        "submittedAt": "2026-01-15T10:00:00Z",
                        # No author
                    },
                ]
            }
        }

        events = extract_review_events(pr)

        assert len(events) == 1
        assert events[0]["reviewer"] == "unknown"


class TestGetHumanReviewTimes:
    """Tests for get_human_review_times function."""

    def test_graphql_format_reviews(self):
        """Test that GraphQL format reviews are correctly processed."""
        pr = {
            "raw_data": {
                "reviews": [
                    {
                        "state": "COMMENTED",
                        "author": {"login": "reviewer1"},
                        "submittedAt": "2026-01-15T10:00:00Z",
                    },
                    {
                        "state": "APPROVED",
                        "author": {"login": "reviewer2"},
                        "submittedAt": "2026-01-15T12:00:00Z",
                    },
                ]
            }
        }

        first_review, approved = get_human_review_times(pr)

        assert first_review == datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        assert approved == datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    def test_rest_format_reviews(self):
        """Test that REST API format reviews still work."""
        pr = {
            "raw_data": {
                "reviews": [
                    {
                        "state": "APPROVED",
                        "user": {"login": "reviewer1"},
                        "submitted_at": "2026-01-15T10:00:00Z",
                    },
                ]
            }
        }

        first_review, approved = get_human_review_times(pr)

        assert first_review == datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        assert approved == datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

    def test_filters_bot_reviewers(self):
        """Test that bot reviewers are filtered out."""
        pr = {
            "raw_data": {
                "reviews": [
                    {
                        "state": "APPROVED",
                        "author": {"login": "dependabot[bot]"},
                        "submittedAt": "2026-01-15T09:00:00Z",
                    },
                    {
                        "state": "COMMENTED",
                        "author": {"login": "human-reviewer"},
                        "submittedAt": "2026-01-15T10:00:00Z",
                    },
                ]
            }
        }

        first_review, approved = get_human_review_times(pr)

        # Bot review at 09:00 is ignored, human review at 10:00 is first
        assert first_review == datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        # No human approval
        assert approved is None

    def test_no_reviews(self):
        """Test handling of PR with no reviews."""
        pr = {"raw_data": {"reviews": []}}

        first_review, approved = get_human_review_times(pr)

        assert first_review is None
        assert approved is None
