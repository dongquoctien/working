"""Jira API client for fetching and updating issues."""

from __future__ import annotations

import logging
from typing import Any

from atlassian import Jira

from src.config import Settings
from src.integrations.base import Issue, IssueTrackerClient, TrackerType

logger = logging.getLogger(__name__)


class JiraClient(IssueTrackerClient):
    """Client for Jira API operations."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client: Jira | None = None

    @property
    def tracker_type(self) -> TrackerType:
        return TrackerType.JIRA

    def _get_client(self) -> Jira:
        """Get or create Jira client."""
        if self._client is None:
            self._client = Jira(
                url=self._settings.jira.url,
                username=self._settings.jira.email,
                password=self._settings.jira.api_token,
                cloud=True,
            )
        return self._client

    def _parse_issue(self, data: dict[str, Any]) -> Issue:
        """Parse Jira API response to Issue object."""
        fields = data.get("fields", {})
        return Issue(
            key=data.get("key", ""),
            summary=fields.get("summary", ""),
            description=fields.get("description", "") or "",
            issue_type=fields.get("issuetype", {}).get("name", ""),
            status=fields.get("status", {}).get("name", ""),
            assignee=fields.get("assignee", {}).get("displayName") if fields.get("assignee") else None,
            project_key=fields.get("project", {}).get("key", ""),
            project_name=fields.get("project", {}).get("name", ""),
            labels=fields.get("labels", []),
            components=[c.get("name", "") for c in fields.get("components", [])],
            priority=fields.get("priority", {}).get("name") if fields.get("priority") else None,
            tracker_type=TrackerType.JIRA,
            raw_data=data,
        )

    def get_issue(self, issue_key: str) -> Issue:
        """
        Fetch issue details from Jira.

        Args:
            issue_key: Jira issue key (e.g., "DEV-123")

        Returns:
            Issue object with issue details
        """
        logger.info(f"Fetching Jira issue: {issue_key}")
        client = self._get_client()
        data = client.issue(issue_key)
        return self._parse_issue(data)

    def update_status(self, issue_key: str, status_name: str) -> bool:
        """
        Update issue status (transition).

        Args:
            issue_key: Jira issue key
            status_name: Target status name (e.g., "Done", "In Progress")

        Returns:
            True if successful
        """
        logger.info(f"Updating {issue_key} status to: {status_name}")
        client = self._get_client()

        # Get available transitions
        transitions = client.get_issue_transitions(issue_key)
        target_transition = None

        for t in transitions:
            if t.get("name", "").lower() == status_name.lower():
                target_transition = t
                break
            # Also check "to" status name
            to_status = t.get("to", {}).get("name", "")
            if to_status.lower() == status_name.lower():
                target_transition = t
                break

        if not target_transition:
            logger.warning(f"Transition to '{status_name}' not found for {issue_key}")
            available = [t.get("name") for t in transitions]
            logger.debug(f"Available transitions: {available}")
            return False

        client.issue_transition(issue_key, target_transition["id"])
        logger.info(f"Successfully transitioned {issue_key} to {status_name}")
        return True

    def add_comment(self, issue_key: str, comment: str) -> bool:
        """
        Add a comment to an issue.

        Args:
            issue_key: Jira issue key
            comment: Comment text

        Returns:
            True if successful
        """
        logger.info(f"Adding comment to {issue_key}")
        client = self._get_client()
        client.issue_add_comment(issue_key, comment)
        return True

    def search_issues(
        self,
        query: str,
        max_results: int = 50,
    ) -> list[Issue]:
        """
        Search issues using JQL.

        Args:
            query: JQL query string
            max_results: Maximum number of results

        Returns:
            List of Issue objects
        """
        logger.info(f"Searching Jira: {query}")
        client = self._get_client()

        result = client.jql(
            query,
            limit=max_results,
            fields=["summary", "description", "issuetype", "status", "assignee", "project", "labels", "components", "priority"],
        )

        issues = []
        for item in result.get("issues", []):
            issues.append(self._parse_issue(item))

        logger.info(f"Found {len(issues)} issues")
        return issues

    def get_my_open_issues(self, project_key: str | None = None) -> list[Issue]:
        """
        Get open issues assigned to current user.

        Args:
            project_key: Optional project key filter

        Returns:
            List of Issue objects
        """
        jql = "assignee = currentUser() AND status != Done"
        if project_key:
            jql += f" AND project = {project_key}"
        jql += " ORDER BY priority DESC, created DESC"

        return self.search_issues(jql)

    def test_connection(self) -> bool:
        """Test Jira connection."""
        try:
            client = self._get_client()
            client.myself()
            logger.info("Jira connection successful")
            return True
        except Exception as e:
            logger.error(f"Jira connection failed: {e}")
            return False
