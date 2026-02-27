"""Redmine API client for fetching and updating issues."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.config import Settings
from src.integrations.base import Issue, IssueTrackerClient, TrackerType

logger = logging.getLogger(__name__)


class RedmineClient(IssueTrackerClient):
    """Client for Redmine API operations."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._base_url = settings.redmine.url.rstrip("/")
        self._api_key = settings.redmine.api_key

    @property
    def tracker_type(self) -> TrackerType:
        return TrackerType.REDMINE

    def _get_headers(self) -> dict[str, str]:
        """Get request headers with API key."""
        return {
            "X-Redmine-API-Key": self._api_key,
            "Content-Type": "application/json",
        }

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: dict | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:
        """Make API request to Redmine."""
        url = f"{self._base_url}{endpoint}"

        with httpx.Client(timeout=30.0) as client:
            response = client.request(
                method,
                url,
                headers=self._get_headers(),
                json=data,
                params=params,
            )
            response.raise_for_status()

            if response.content:
                return response.json()
            return {}

    def get_issue(self, issue_key: str) -> Issue:
        """
        Fetch issue details from Redmine.

        Args:
            issue_key: Redmine issue ID (numeric string like "12345")

        Returns:
            Issue object with details
        """
        logger.info(f"Fetching Redmine issue: {issue_key}")

        # Include journals for comments, attachments, etc.
        data = self._make_request(
            "GET",
            f"/issues/{issue_key}.json",
            params={"include": "attachments,journals,watchers"},
        )

        issue_data = data.get("issue", {})
        return self._parse_issue(issue_data)

    def _parse_issue(self, data: dict[str, Any]) -> Issue:
        """Parse Redmine API response to Issue object."""
        # Extract custom fields as labels
        labels = []
        custom_fields = data.get("custom_fields", [])
        for cf in custom_fields:
            if cf.get("value"):
                labels.append(f"{cf.get('name')}: {cf.get('value')}")

        # Category as component
        components = []
        if data.get("category"):
            components.append(data["category"].get("name", ""))

        return Issue(
            key=str(data.get("id", "")),
            summary=data.get("subject", ""),
            description=data.get("description", "") or "",
            status=data.get("status", {}).get("name", ""),
            issue_type=data.get("tracker", {}).get("name", ""),
            priority=data.get("priority", {}).get("name"),
            assignee=data.get("assigned_to", {}).get("name") if data.get("assigned_to") else None,
            project_key=data.get("project", {}).get("identifier", ""),
            project_name=data.get("project", {}).get("name", ""),
            labels=labels,
            components=components,
            tracker_type=TrackerType.REDMINE,
            raw_data=data,
        )

    def update_status(self, issue_key: str, status_name: str) -> bool:
        """
        Update issue status.

        Args:
            issue_key: Redmine issue ID
            status_name: Target status name (e.g., "Done", "In Progress")

        Returns:
            True if successful
        """
        logger.info(f"Updating {issue_key} status to: {status_name}")

        # First, get available statuses
        status_id = self._find_status_id(status_name)
        if not status_id:
            logger.warning(f"Status '{status_name}' not found")
            return False

        try:
            self._make_request(
                "PUT",
                f"/issues/{issue_key}.json",
                data={"issue": {"status_id": status_id}},
            )
            logger.info(f"Successfully updated {issue_key} to {status_name}")
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to update status: {e}")
            return False

    def _find_status_id(self, status_name: str) -> int | None:
        """Find status ID by name."""
        try:
            data = self._make_request("GET", "/issue_statuses.json")
            statuses = data.get("issue_statuses", [])

            for status in statuses:
                if status.get("name", "").lower() == status_name.lower():
                    return status.get("id")

            return None
        except Exception as e:
            logger.error(f"Failed to get statuses: {e}")
            return None

    def add_comment(self, issue_key: str, comment: str) -> bool:
        """
        Add a comment (note) to an issue.

        Args:
            issue_key: Redmine issue ID
            comment: Comment text

        Returns:
            True if successful
        """
        logger.info(f"Adding comment to {issue_key}")

        try:
            self._make_request(
                "PUT",
                f"/issues/{issue_key}.json",
                data={"issue": {"notes": comment}},
            )
            return True
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to add comment: {e}")
            return False

    def search_issues(
        self,
        query: str,
        max_results: int = 50,
        project_id: str | None = None,
    ) -> list[Issue]:
        """
        Search issues.

        Args:
            query: Search query (searches in subject and description)
            max_results: Maximum results
            project_id: Optional project filter

        Returns:
            List of Issue objects
        """
        logger.info(f"Searching Redmine: {query}")

        params = {
            "limit": max_results,
            "status_id": "open",  # Only open issues by default
        }

        if project_id:
            params["project_id"] = project_id

        # Note: Redmine doesn't have full-text search by default
        # This searches by assigned_to=me as a common use case
        try:
            data = self._make_request("GET", "/issues.json", params=params)
            issues = []
            for item in data.get("issues", []):
                # Client-side filter by query if provided
                if query:
                    subject = item.get("subject", "").lower()
                    desc = (item.get("description") or "").lower()
                    if query.lower() not in subject and query.lower() not in desc:
                        continue
                issues.append(self._parse_issue(item))
            return issues
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    def get_my_open_issues(self, project_key: str | None = None) -> list[Issue]:
        """
        Get open issues assigned to current user.

        Args:
            project_key: Optional project identifier filter

        Returns:
            List of Issue objects
        """
        logger.info("Fetching my open issues from Redmine")

        params = {
            "assigned_to_id": "me",
            "status_id": "open",
            "limit": 50,
            "sort": "priority:desc,updated_on:desc",
        }

        if project_key:
            params["project_id"] = project_key

        try:
            data = self._make_request("GET", "/issues.json", params=params)
            return [self._parse_issue(item) for item in data.get("issues", [])]
        except Exception as e:
            logger.error(f"Failed to get my issues: {e}")
            return []

    def get_projects(self) -> list[dict]:
        """Get list of projects."""
        try:
            data = self._make_request("GET", "/projects.json", params={"limit": 100})
            return data.get("projects", [])
        except Exception as e:
            logger.error(f"Failed to get projects: {e}")
            return []

    def test_connection(self) -> bool:
        """Test Redmine connection."""
        try:
            data = self._make_request("GET", "/users/current.json")
            user = data.get("user", {})
            logger.info(f"Redmine connection successful. User: {user.get('login')}")
            return True
        except Exception as e:
            logger.error(f"Redmine connection failed: {e}")
            return False
