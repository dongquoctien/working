"""Main orchestrator for managing task queue and execution."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from src.config import Settings
from src.core.state_machine import TaskState, TaskStateMachine
from src.core.task_runner import TaskRunner, TaskResult

logger = logging.getLogger(__name__)


@dataclass
class QueuedTask:
    """Task in the queue."""

    jira_key: str
    priority: int = 0
    added_at: datetime = field(default_factory=datetime.now)
    state_machine: TaskStateMachine | None = None

    def __lt__(self, other: "QueuedTask") -> bool:
        # Higher priority first, then earlier added
        if self.priority != other.priority:
            return self.priority > other.priority
        return self.added_at < other.added_at


class Orchestrator:
    """
    Manages task queue and coordinates execution.

    Features:
    - Task queue with priority
    - Concurrent task limit
    - Pause/resume
    - History tracking
    """

    def __init__(
        self,
        settings: Settings,
        on_task_update: Callable[[str, TaskState], None] | None = None,
        on_log: Callable[[str, str], None] | None = None,
    ):
        self._settings = settings
        self._queue: deque[QueuedTask] = deque()
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._completed: list[TaskResult] = []
        self._paused = False
        self._running = False
        self._on_task_update = on_task_update
        self._on_log = on_log

        # History file
        self._history_path = Path(settings.history_file)

        # Create task runner
        self._runner = TaskRunner(
            settings,
            on_state_change=self._handle_state_change,
            on_log=on_log,
        )

    def _handle_state_change(
        self,
        jira_key: str,
        old_state: TaskState,
        new_state: TaskState,
    ) -> None:
        """Handle state change from task runner."""
        if self._on_task_update:
            self._on_task_update(jira_key, new_state)

    @property
    def queue_size(self) -> int:
        """Number of tasks in queue."""
        return len(self._queue)

    @property
    def active_count(self) -> int:
        """Number of currently executing tasks."""
        return len(self._active_tasks)

    @property
    def is_paused(self) -> bool:
        """Whether orchestrator is paused."""
        return self._paused

    @property
    def is_running(self) -> bool:
        """Whether orchestrator is running."""
        return self._running

    def add_task(self, jira_key: str, priority: int = 0) -> bool:
        """
        Add a task to the queue.

        Args:
            jira_key: Jira issue key
            priority: Task priority (higher = more urgent)

        Returns:
            True if added, False if already in queue
        """
        # Check if already queued or active
        if any(t.jira_key == jira_key for t in self._queue):
            logger.warning(f"Task {jira_key} already in queue")
            return False

        if jira_key in self._active_tasks:
            logger.warning(f"Task {jira_key} is already running")
            return False

        task = QueuedTask(
            jira_key=jira_key,
            priority=priority,
            state_machine=TaskStateMachine(jira_key, self._settings.workflow.max_retries),
        )

        # Insert maintaining priority order
        inserted = False
        for i, queued in enumerate(self._queue):
            if task < queued:
                continue
            self._queue.insert(i, task)
            inserted = True
            break

        if not inserted:
            self._queue.append(task)

        logger.info(f"Task {jira_key} added to queue (priority: {priority})")

        if self._on_task_update:
            self._on_task_update(jira_key, TaskState.PENDING)

        return True

    def remove_task(self, jira_key: str) -> bool:
        """
        Remove a task from the queue.

        Args:
            jira_key: Jira issue key

        Returns:
            True if removed
        """
        for i, task in enumerate(self._queue):
            if task.jira_key == jira_key:
                del self._queue[i]
                logger.info(f"Task {jira_key} removed from queue")
                return True
        return False

    def cancel_task(self, jira_key: str) -> bool:
        """
        Cancel a running task.

        Args:
            jira_key: Jira issue key

        Returns:
            True if cancelled
        """
        if jira_key in self._active_tasks:
            self._active_tasks[jira_key].cancel()
            logger.info(f"Task {jira_key} cancelled")
            return True
        return self.remove_task(jira_key)

    def pause(self) -> None:
        """Pause processing new tasks."""
        self._paused = True
        logger.info("Orchestrator paused")

    def resume(self) -> None:
        """Resume processing tasks."""
        self._paused = False
        logger.info("Orchestrator resumed")

    async def start(self, max_concurrent: int = 1) -> None:
        """
        Start the orchestrator loop.

        Args:
            max_concurrent: Maximum concurrent tasks (default 1)
        """
        self._running = True
        logger.info(f"Orchestrator started (max concurrent: {max_concurrent})")

        try:
            while self._running:
                # Clean up completed tasks
                self._cleanup_completed()

                # Check if we can start new tasks
                if (
                    not self._paused
                    and self._queue
                    and len(self._active_tasks) < max_concurrent
                ):
                    await self._start_next_task()

                await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            logger.info("Orchestrator cancelled")
            await self._cancel_all_tasks()
        finally:
            self._running = False

    async def stop(self) -> None:
        """Stop the orchestrator."""
        self._running = False
        await self._cancel_all_tasks()
        logger.info("Orchestrator stopped")

    async def _start_next_task(self) -> None:
        """Start the next task from queue."""
        if not self._queue:
            return

        queued = self._queue.popleft()
        jira_key = queued.jira_key

        logger.info(f"Starting task: {jira_key}")

        async def run_and_record():
            result = await self._runner.run(jira_key)
            self._completed.append(result)
            self._save_history(result)

            # Remove from active
            if jira_key in self._active_tasks:
                del self._active_tasks[jira_key]

        task = asyncio.create_task(run_and_record())
        self._active_tasks[jira_key] = task

    def _cleanup_completed(self) -> None:
        """Clean up finished tasks from active dict."""
        completed = [
            key for key, task in self._active_tasks.items() if task.done()
        ]
        for key in completed:
            del self._active_tasks[key]

    async def _cancel_all_tasks(self) -> None:
        """Cancel all active tasks."""
        for jira_key, task in list(self._active_tasks.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._active_tasks.clear()

    def _save_history(self, result: TaskResult) -> None:
        """Save task result to history file."""
        try:
            history = []
            if self._history_path.exists():
                with open(self._history_path, "r") as f:
                    history = json.load(f)

            history.append({
                "jira_key": result.jira_key,
                "success": result.success,
                "pr_url": result.pr_url,
                "error_message": result.error_message,
                "attempts": result.attempts,
                "completed_at": datetime.now().isoformat(),
            })

            # Keep last 100 entries
            history = history[-100:]

            with open(self._history_path, "w") as f:
                json.dump(history, f, indent=2)

        except Exception as e:
            logger.error(f"Failed to save history: {e}")

    def get_history(self, limit: int = 20) -> list[dict]:
        """Get recent task history."""
        if not self._history_path.exists():
            return []

        try:
            with open(self._history_path, "r") as f:
                history = json.load(f)
            return history[-limit:]
        except Exception:
            return []

    def get_queue_status(self) -> list[dict]:
        """Get current queue status."""
        return [
            {
                "jira_key": t.jira_key,
                "priority": t.priority,
                "added_at": t.added_at.isoformat(),
                "state": t.state_machine.state.name if t.state_machine else "PENDING",
            }
            for t in self._queue
        ]

    def get_active_status(self) -> list[dict]:
        """Get active tasks status."""
        return [
            {"jira_key": key, "running": not task.done()}
            for key, task in self._active_tasks.items()
        ]

    async def run_single(self, jira_key: str) -> TaskResult:
        """
        Run a single task immediately (bypass queue).

        Args:
            jira_key: Jira issue key

        Returns:
            TaskResult
        """
        logger.info(f"Running single task: {jira_key}")
        result = await self._runner.run(jira_key)
        self._completed.append(result)
        self._save_history(result)
        return result
