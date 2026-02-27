"""Abstract base classes for issue tracker integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TrackerType(Enum):
    """Supported issue tracker types."""

    JIRA = "jira"
    REDMINE = "redmine"


@dataclass
class Issue:
    """Universal issue data structure for all trackers."""

    # Common fields
    key: str  # Issue ID/key (e.g., "DEV-123" or "12345")
    summary: str  # Title/subject
    description: str
    status: str
    issue_type: str  # Bug, Feature, Task, etc.
    priority: str | None = None
    assignee: str | None = None
    project_key: str = ""
    project_name: str = ""

    # Extended fields
    labels: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)  # Jira components or Redmine categories
    tracker_type: TrackerType = TrackerType.JIRA

    # Original data for reference
    raw_data: dict[str, Any] = field(default_factory=dict)

    def to_prompt(self) -> str:
        """Convert to prompt for Claude."""
        tracker_name = self.tracker_type.value.capitalize()
        parts = [
            f"# {tracker_name} Issue: {self.key}",
            f"## Summary: {self.summary}",
            f"**Type:** {self.issue_type}",
            f"**Status:** {self.status}",
            f"**Priority:** {self.priority or 'None'}",
            f"**Project:** {self.project_name or self.project_key}",
        ]

        if self.labels:
            parts.append(f"**Labels:** {', '.join(self.labels)}")

        if self.components:
            parts.append(f"**Components/Categories:** {', '.join(self.components)}")

        parts.extend([
            "",
            "## Description:",
            self.description or "(No description)",
        ])

        return "\n".join(parts)


class IssueTrackerClient(ABC):
    """Abstract base class for issue tracker clients."""

    @property
    @abstractmethod
    def tracker_type(self) -> TrackerType:
        """Return the tracker type."""
        pass

    @abstractmethod
    def get_issue(self, issue_key: str) -> Issue:
        """
        Fetch issue details.

        Args:
            issue_key: Issue identifier (e.g., "DEV-123" for Jira, "12345" for Redmine)

        Returns:
            Issue object with details
        """
        pass

    @abstractmethod
    def update_status(self, issue_key: str, status_name: str) -> bool:
        """
        Update issue status.

        Args:
            issue_key: Issue identifier
            status_name: Target status name

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    def add_comment(self, issue_key: str, comment: str) -> bool:
        """
        Add a comment to an issue.

        Args:
            issue_key: Issue identifier
            comment: Comment text

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    def test_connection(self) -> bool:
        """Test connection to the tracker."""
        pass

    def search_issues(
        self,
        query: str,
        max_results: int = 50,
    ) -> list[Issue]:
        """
        Search issues. Default implementation returns empty list.
        Override in subclasses that support search.
        """
        return []

    def get_my_open_issues(self, project_key: str | None = None) -> list[Issue]:
        """
        Get open issues assigned to current user.
        Override in subclasses.
        """
        return []
