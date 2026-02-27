"""Integration modules for external services."""

from .base import Issue, IssueTrackerClient, TrackerType
from .jira_client import JiraClient
from .redmine_client import RedmineClient
from .bitbucket_client import BitbucketClient
from .claude_cli import ClaudeCLI
from .test_runner import TestRunner, ProjectType, TestResult

__all__ = [
    # Base
    "Issue",
    "IssueTrackerClient",
    "TrackerType",
    # Tracker clients
    "JiraClient",
    "RedmineClient",
    # Other integrations
    "BitbucketClient",
    "ClaudeCLI",
    "TestRunner",
    "ProjectType",
    "TestResult",
]


def create_tracker_client(settings) -> IssueTrackerClient:
    """
    Factory function to create the appropriate tracker client.

    Args:
        settings: Application settings

    Returns:
        IssueTrackerClient instance (JiraClient or RedmineClient)
    """
    from src.config.settings import TrackerType as ConfigTrackerType

    if settings.tracker == ConfigTrackerType.REDMINE:
        return RedmineClient(settings)
    return JiraClient(settings)
