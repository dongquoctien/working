"""Task runner for executing single task workflow."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Callable

from src.config import Settings, ProjectConfig
from src.config.settings import TrackerType
from src.integrations import (
    IssueTrackerClient,
    JiraClient,
    RedmineClient,
    BitbucketClient,
    ClaudeCLI,
    TestRunner,
    create_tracker_client,
)
from src.core.state_machine import TaskState, TaskStateMachine

logger = logging.getLogger(__name__)


@dataclass
class TaskResult:
    """Result of task execution."""

    jira_key: str  # Actually issue_key, kept for backward compatibility
    success: bool
    pr_url: str = ""
    error_message: str = ""
    attempts: int = 0


class TaskRunner:
    """
    Runs a single task through the full workflow:
    Fetch -> Implement -> Test -> (Fix Loop) -> PR -> Update Tracker
    """

    def __init__(
        self,
        settings: Settings,
        on_state_change: Callable[[str, TaskState, TaskState], None] | None = None,
        on_log: Callable[[str, str], None] | None = None,
    ):
        self._settings = settings
        self._tracker = create_tracker_client(settings)
        self._bitbucket = BitbucketClient(settings)
        self._claude = ClaudeCLI(settings)
        self._on_state_change = on_state_change
        self._on_log = on_log

    def _log(self, task_key: str, message: str) -> None:
        """Log message and notify callback."""
        logger.info(f"[{task_key}] {message}")
        if self._on_log:
            self._on_log(task_key, message)

    def _notify_state_change(
        self,
        old_state: TaskState,
        new_state: TaskState,
        context,
    ) -> None:
        """Notify state change callback."""
        if self._on_state_change:
            self._on_state_change(context.jira_key, old_state, new_state)

    def _find_project(self, issue) -> ProjectConfig | None:
        """
        Find matching project config based on issue.

        Uses labels, components, or project key to match.
        """
        for project in self._settings.projects:
            # Match by label
            if project.name.lower() in [l.lower() for l in issue.labels]:
                return project

            # Match by component
            if project.name.lower() in [c.lower() for c in issue.components]:
                return project

            # Match by project key/name
            if project.name.lower() == issue.project_key.lower():
                return project
            if project.name.lower() == issue.project_name.lower():
                return project

        # Return first project as default if only one configured
        if len(self._settings.projects) == 1:
            return self._settings.projects[0]

        return None

    def _generate_branch_name(self, issue_key: str, summary: str) -> str:
        """Generate branch name from issue."""
        # Sanitize summary for branch name
        safe_summary = re.sub(r"[^a-zA-Z0-9\s-]", "", summary)
        safe_summary = re.sub(r"\s+", "-", safe_summary.strip())
        safe_summary = safe_summary[:40].rstrip("-")  # Limit length

        return f"feature/{issue_key}-{safe_summary}".lower()

    def _get_tracker_name(self) -> str:
        """Get current tracker name for logging."""
        return self._settings.tracker.value.capitalize()

    async def run(self, issue_key: str) -> TaskResult:
        """
        Execute the full task workflow.

        Args:
            issue_key: Issue key (e.g., "DEV-123" for Jira or "12345" for Redmine)

        Returns:
            TaskResult with execution outcome
        """
        tracker_name = self._get_tracker_name()
        state_machine = TaskStateMachine(
            jira_key=issue_key,  # Field name kept for compatibility
            max_retries=self._settings.workflow.max_retries,
            on_transition=self._notify_state_change,
        )

        try:
            # Phase 1: Fetch issue from tracker
            state_machine.transition_to(TaskState.FETCHING, f"Fetching issue from {tracker_name}")
            self._log(issue_key, f"Fetching issue from {tracker_name}...")

            issue = self._tracker.get_issue(issue_key)
            self._log(issue_key, f"Issue: {issue.summary}")

            # Find matching project
            project = self._find_project(issue)
            if not project:
                state_machine.transition_to(TaskState.FAILED, "No matching project found")
                return TaskResult(
                    jira_key=issue_key,
                    success=False,
                    error_message="Could not determine which project this task belongs to",
                )

            state_machine.set_project(project.name, project.path)
            self._log(issue_key, f"Project: {project.name} at {project.path}")

            # Create branch
            branch_name = self._generate_branch_name(issue_key, issue.summary)
            state_machine.set_branch(branch_name)

            self._bitbucket.create_branch(
                project.path,
                branch_name,
                base_branch="develop",
            )
            self._log(issue_key, f"Created branch: {branch_name}")

            # Update tracker to In Progress
            if self._settings.workflow.auto_update_tracker:
                self._tracker.update_status(
                    issue_key,
                    self._settings.get_in_progress_status(),
                )

            # Phase 2: Implement
            state_machine.transition_to(TaskState.IMPLEMENTING, "Claude implementing")
            self._log(issue_key, "Claude is implementing the task...")

            task_prompt = issue.to_prompt()
            response = await self._claude.implement_task(task_prompt, project.path)

            if not response.success:
                state_machine.set_error(response.error)
                state_machine.transition_to(TaskState.FAILED, "Implementation failed")
                return TaskResult(
                    jira_key=issue_key,
                    success=False,
                    error_message=f"Claude implementation failed: {response.error}",
                )

            self._log(issue_key, "Implementation completed")

            # Commit changes
            self._bitbucket.commit_changes(
                project.path,
                f"{issue_key}: {issue.summary}",
            )

            # Phase 3: Test loop
            test_runner = TestRunner(project)

            while True:
                state_machine.transition_to(TaskState.TESTING, "Running tests")
                self._log(
                    issue_key,
                    f"Running tests (attempt {state_machine.context.attempt + 1}/{state_machine.context.max_retries})...",
                )

                test_result = await test_runner.run_tests(project.path)
                state_machine.set_test_output(test_result.output)

                if test_result.success:
                    self._log(issue_key, f"Tests passed! {test_result.summary}")
                    break

                # Tests failed
                self._log(issue_key, f"Tests failed: {test_result.summary}")
                state_machine.increment_attempt()

                if not state_machine.has_retries_left():
                    state_machine.transition_to(
                        TaskState.MANUAL_REVIEW,
                        "Max retries exceeded",
                    )
                    return TaskResult(
                        jira_key=issue_key,
                        success=False,
                        error_message=f"Max retries ({state_machine.context.max_retries}) exceeded. Manual review needed.",
                        attempts=state_machine.context.attempt,
                    )

                # Fix and retry
                state_machine.transition_to(TaskState.FIXING, "Fixing test failures")
                self._log(issue_key, "Claude is fixing the issues...")

                error_summary = test_runner.get_error_summary(test_result)
                fix_response = await self._claude.fix_test_failures(
                    error_summary,
                    project.path,
                )

                if not fix_response.success:
                    self._log(issue_key, f"Fix attempt failed: {fix_response.error}")

                # Commit fix
                self._bitbucket.commit_changes(
                    project.path,
                    f"{issue_key}: Fix test failures (attempt {state_machine.context.attempt})",
                )

            # Phase 4: Create PR
            state_machine.transition_to(TaskState.CREATING_PR, "Creating pull request")
            self._log(issue_key, "Creating pull request...")

            # Push branch
            self._bitbucket.push_branch(project.path, branch_name)

            # Generate PR description
            diff_summary = self._bitbucket.get_diff_summary(project.path)
            pr_description = await self._claude.generate_pr_description(
                issue.summary,
                diff_summary,
                project.path,
            )

            if self._settings.workflow.auto_create_pr:
                pr = self._bitbucket.create_pull_request(
                    project.path,
                    title=f"{issue_key}: {issue.summary}",
                    description=pr_description,
                    source_branch=branch_name,
                    target_branch="develop",
                )

                if pr:
                    state_machine.set_pr_url(pr.url)
                    self._log(issue_key, f"PR created: {pr.url}")
                else:
                    self._log(issue_key, "Failed to create PR, but changes are pushed")

            # Phase 5: Update tracker
            state_machine.transition_to(TaskState.UPDATING_JIRA, f"Updating {tracker_name}")

            if self._settings.workflow.auto_update_tracker:
                # Add comment with PR link
                if state_machine.context.pr_url:
                    self._tracker.add_comment(
                        issue_key,
                        f"Pull request created: {state_machine.context.pr_url}",
                    )

                # Update status to Done
                self._tracker.update_status(
                    issue_key,
                    self._settings.get_done_status(),
                )
                self._log(issue_key, f"{tracker_name} updated to Done")

            # Complete
            state_machine.transition_to(TaskState.COMPLETED, "Task completed")
            self._log(issue_key, "Task completed successfully!")

            return TaskResult(
                jira_key=issue_key,
                success=True,
                pr_url=state_machine.context.pr_url,
                attempts=state_machine.context.attempt + 1,
            )

        except Exception as e:
            logger.exception(f"Task {issue_key} failed with error")
            state_machine.set_error(str(e))
            state_machine.transition_to(TaskState.FAILED, str(e))

            return TaskResult(
                jira_key=issue_key,
                success=False,
                error_message=str(e),
                attempts=state_machine.context.attempt,
            )
