"""Task state machine for managing task lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Callable


class TaskState(Enum):
    """Task states in the workflow."""

    PENDING = auto()
    FETCHING = auto()
    IMPLEMENTING = auto()
    TESTING = auto()
    FIXING = auto()
    CREATING_PR = auto()
    UPDATING_JIRA = auto()
    COMPLETED = auto()
    FAILED = auto()
    MANUAL_REVIEW = auto()
    CANCELLED = auto()

    def is_terminal(self) -> bool:
        """Check if this is a terminal state."""
        return self in (
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.MANUAL_REVIEW,
            TaskState.CANCELLED,
        )

    def is_active(self) -> bool:
        """Check if task is actively being processed."""
        return self in (
            TaskState.FETCHING,
            TaskState.IMPLEMENTING,
            TaskState.TESTING,
            TaskState.FIXING,
            TaskState.CREATING_PR,
            TaskState.UPDATING_JIRA,
        )


# Valid state transitions
VALID_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.PENDING: {TaskState.FETCHING, TaskState.CANCELLED},
    TaskState.FETCHING: {TaskState.IMPLEMENTING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.IMPLEMENTING: {TaskState.TESTING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.TESTING: {
        TaskState.CREATING_PR,  # Test passed
        TaskState.FIXING,  # Test failed, retry
        TaskState.MANUAL_REVIEW,  # Max retries exceeded
        TaskState.FAILED,
        TaskState.CANCELLED,
    },
    TaskState.FIXING: {TaskState.TESTING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.CREATING_PR: {TaskState.UPDATING_JIRA, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.UPDATING_JIRA: {TaskState.COMPLETED, TaskState.FAILED},
    TaskState.COMPLETED: set(),
    TaskState.FAILED: set(),
    TaskState.MANUAL_REVIEW: set(),
    TaskState.CANCELLED: set(),
}


@dataclass
class StateTransition:
    """Record of a state transition."""

    from_state: TaskState
    to_state: TaskState
    timestamp: datetime
    message: str = ""


@dataclass
class TaskContext:
    """Context data for a task throughout its lifecycle."""

    jira_key: str
    project_name: str = ""
    project_path: str = ""
    branch_name: str = ""
    pr_url: str = ""

    # Execution tracking
    attempt: int = 0
    max_retries: int = 5
    test_output: str = ""
    error_message: str = ""

    # Timestamps
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # History
    transitions: list[StateTransition] = field(default_factory=list)


class TaskStateMachine:
    """State machine for managing task state transitions."""

    def __init__(
        self,
        jira_key: str,
        max_retries: int = 5,
        on_transition: Callable[[TaskState, TaskState, TaskContext], None] | None = None,
    ):
        self._state = TaskState.PENDING
        self._context = TaskContext(jira_key=jira_key, max_retries=max_retries)
        self._on_transition = on_transition

    @property
    def state(self) -> TaskState:
        """Current task state."""
        return self._state

    @property
    def context(self) -> TaskContext:
        """Task context data."""
        return self._context

    @property
    def jira_key(self) -> str:
        """Jira issue key."""
        return self._context.jira_key

    def can_transition_to(self, new_state: TaskState) -> bool:
        """Check if transition to new state is valid."""
        return new_state in VALID_TRANSITIONS.get(self._state, set())

    def transition_to(self, new_state: TaskState, message: str = "") -> bool:
        """
        Attempt to transition to a new state.

        Returns True if transition was successful, False otherwise.
        """
        if not self.can_transition_to(new_state):
            return False

        old_state = self._state
        transition = StateTransition(
            from_state=old_state,
            to_state=new_state,
            timestamp=datetime.now(),
            message=message,
        )
        self._context.transitions.append(transition)
        self._state = new_state

        # Track timestamps
        if new_state == TaskState.FETCHING and self._context.started_at is None:
            self._context.started_at = datetime.now()
        elif new_state.is_terminal():
            self._context.completed_at = datetime.now()

        # Callback
        if self._on_transition:
            self._on_transition(old_state, new_state, self._context)

        return True

    def increment_attempt(self) -> int:
        """Increment retry attempt counter."""
        self._context.attempt += 1
        return self._context.attempt

    def has_retries_left(self) -> bool:
        """Check if there are retries remaining."""
        return self._context.attempt < self._context.max_retries

    def set_test_output(self, output: str) -> None:
        """Store test output for error analysis."""
        self._context.test_output = output

    def set_error(self, message: str) -> None:
        """Set error message."""
        self._context.error_message = message

    def set_project(self, name: str, path: str) -> None:
        """Set project info."""
        self._context.project_name = name
        self._context.project_path = path

    def set_branch(self, branch_name: str) -> None:
        """Set branch name."""
        self._context.branch_name = branch_name

    def set_pr_url(self, url: str) -> None:
        """Set PR URL."""
        self._context.pr_url = url

    def get_status_display(self) -> str:
        """Get human-readable status string."""
        state_display = {
            TaskState.PENDING: "Pending",
            TaskState.FETCHING: "Fetching from Jira...",
            TaskState.IMPLEMENTING: "Claude implementing...",
            TaskState.TESTING: f"Testing (attempt {self._context.attempt + 1}/{self._context.max_retries})",
            TaskState.FIXING: f"Fixing issues (attempt {self._context.attempt}/{self._context.max_retries})",
            TaskState.CREATING_PR: "Creating PR...",
            TaskState.UPDATING_JIRA: "Updating Jira...",
            TaskState.COMPLETED: "Completed",
            TaskState.FAILED: "Failed",
            TaskState.MANUAL_REVIEW: "Needs manual review",
            TaskState.CANCELLED: "Cancelled",
        }
        return state_display.get(self._state, str(self._state))

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "jira_key": self._context.jira_key,
            "state": self._state.name,
            "project_name": self._context.project_name,
            "branch_name": self._context.branch_name,
            "pr_url": self._context.pr_url,
            "attempt": self._context.attempt,
            "max_retries": self._context.max_retries,
            "error_message": self._context.error_message,
            "started_at": self._context.started_at.isoformat() if self._context.started_at else None,
            "completed_at": self._context.completed_at.isoformat() if self._context.completed_at else None,
        }
