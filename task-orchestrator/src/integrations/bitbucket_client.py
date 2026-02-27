"""Bitbucket API client for branch and PR management."""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx

from src.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class PullRequest:
    """Pull request data."""

    id: int
    title: str
    description: str
    source_branch: str
    target_branch: str
    url: str
    state: str


class BitbucketClient:
    """Client for Bitbucket API operations."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._base_url = "https://api.bitbucket.org/2.0"

    def _get_auth(self) -> tuple[str, str]:
        """Get authentication tuple."""
        return (
            self._settings.bitbucket.username,
            self._settings.bitbucket.app_password,
        )

    def _get_repo_slug(self, project_path: str) -> str | None:
        """
        Extract repo slug from git remote URL.

        Args:
            project_path: Path to project directory

        Returns:
            Repository slug or None
        """
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=project_path,
                capture_output=True,
                text=True,
                check=True,
            )
            remote_url = result.stdout.strip()

            # Parse repo slug from URL
            # SSH: git@bitbucket.org:workspace/repo.git
            # HTTPS: https://bitbucket.org/workspace/repo.git
            patterns = [
                r"bitbucket\.org[:/]([^/]+)/([^/.]+)",  # workspace/repo
                r"bitbucket\.org[:/]([^/]+)/([^/.]+)\.git",
            ]

            for pattern in patterns:
                match = re.search(pattern, remote_url)
                if match:
                    return match.group(2)

            return None
        except subprocess.CalledProcessError:
            logger.error(f"Failed to get git remote for {project_path}")
            return None

    def create_branch(
        self,
        project_path: str,
        branch_name: str,
        base_branch: str = "develop",
    ) -> bool:
        """
        Create a new branch locally and push to remote.

        Args:
            project_path: Path to project directory
            branch_name: Name for new branch
            base_branch: Base branch to branch from

        Returns:
            True if successful
        """
        logger.info(f"Creating branch: {branch_name} from {base_branch}")

        try:
            # Fetch latest
            subprocess.run(
                ["git", "fetch", "origin"],
                cwd=project_path,
                check=True,
                capture_output=True,
            )

            # Checkout base branch
            subprocess.run(
                ["git", "checkout", base_branch],
                cwd=project_path,
                check=True,
                capture_output=True,
            )

            # Pull latest
            subprocess.run(
                ["git", "pull", "origin", base_branch],
                cwd=project_path,
                check=True,
                capture_output=True,
            )

            # Create and checkout new branch
            subprocess.run(
                ["git", "checkout", "-b", branch_name],
                cwd=project_path,
                check=True,
                capture_output=True,
            )

            logger.info(f"Branch {branch_name} created successfully")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create branch: {e.stderr}")
            return False

    def push_branch(self, project_path: str, branch_name: str) -> bool:
        """
        Push branch to remote.

        Args:
            project_path: Path to project directory
            branch_name: Branch name to push

        Returns:
            True if successful
        """
        logger.info(f"Pushing branch: {branch_name}")

        try:
            subprocess.run(
                ["git", "push", "-u", "origin", branch_name],
                cwd=project_path,
                check=True,
                capture_output=True,
            )
            logger.info(f"Branch {branch_name} pushed successfully")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to push branch: {e.stderr}")
            return False

    def commit_changes(
        self,
        project_path: str,
        message: str,
        add_all: bool = True,
    ) -> bool:
        """
        Commit changes.

        Args:
            project_path: Path to project directory
            message: Commit message
            add_all: Whether to add all changes

        Returns:
            True if successful
        """
        logger.info(f"Committing changes: {message[:50]}...")

        try:
            if add_all:
                subprocess.run(
                    ["git", "add", "-A"],
                    cwd=project_path,
                    check=True,
                    capture_output=True,
                )

            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=project_path,
                check=True,
                capture_output=True,
            )

            logger.info("Changes committed successfully")
            return True

        except subprocess.CalledProcessError as e:
            # No changes to commit is not an error
            if "nothing to commit" in str(e.stderr):
                logger.info("No changes to commit")
                return True
            logger.error(f"Failed to commit: {e.stderr}")
            return False

    def create_pull_request(
        self,
        project_path: str,
        title: str,
        description: str,
        source_branch: str,
        target_branch: str = "develop",
    ) -> PullRequest | None:
        """
        Create a pull request on Bitbucket.

        Args:
            project_path: Path to project directory
            title: PR title
            description: PR description
            source_branch: Source branch name
            target_branch: Target branch name

        Returns:
            PullRequest object if successful, None otherwise
        """
        logger.info(f"Creating PR: {title}")

        repo_slug = self._get_repo_slug(project_path)
        if not repo_slug:
            logger.error("Could not determine repository slug")
            return None

        workspace = self._settings.bitbucket.workspace
        url = f"{self._base_url}/repositories/{workspace}/{repo_slug}/pullrequests"

        payload = {
            "title": title,
            "description": description,
            "source": {
                "branch": {
                    "name": source_branch,
                }
            },
            "destination": {
                "branch": {
                    "name": target_branch,
                }
            },
            "close_source_branch": True,
        }

        try:
            with httpx.Client() as client:
                response = client.post(
                    url,
                    json=payload,
                    auth=self._get_auth(),
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()

                pr = PullRequest(
                    id=data.get("id"),
                    title=data.get("title"),
                    description=data.get("description", ""),
                    source_branch=source_branch,
                    target_branch=target_branch,
                    url=data.get("links", {}).get("html", {}).get("href", ""),
                    state=data.get("state"),
                )

                logger.info(f"PR created: {pr.url}")
                return pr

        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to create PR: {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Failed to create PR: {e}")
            return None

    def get_diff_summary(self, project_path: str) -> str:
        """
        Get summary of changes for PR description.

        Args:
            project_path: Path to project directory

        Returns:
            Diff summary string
        """
        try:
            # Get changed files
            result = subprocess.run(
                ["git", "diff", "--stat", "HEAD~1"],
                cwd=project_path,
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return ""

    def test_connection(self) -> bool:
        """Test Bitbucket connection."""
        try:
            workspace = self._settings.bitbucket.workspace
            url = f"{self._base_url}/repositories/{workspace}"

            with httpx.Client() as client:
                response = client.get(
                    url,
                    auth=self._get_auth(),
                    timeout=10.0,
                )
                response.raise_for_status()
                logger.info("Bitbucket connection successful")
                return True

        except Exception as e:
            logger.error(f"Bitbucket connection failed: {e}")
            return False
