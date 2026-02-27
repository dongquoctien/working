"""Main TUI Application using Textual."""

from __future__ import annotations

import asyncio
from datetime import datetime

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    RichLog,
    Static,
)

from src.config import Settings, get_settings
from src.core import Orchestrator, TaskState


class TaskListItem(ListItem):
    """Custom list item for tasks."""

    def __init__(self, jira_key: str, status: str = "PENDING"):
        super().__init__()
        self.jira_key = jira_key
        self.status = status

    def compose(self) -> ComposeResult:
        status_style = self._get_status_style()
        yield Label(f"{self.jira_key} [{self.status}]", classes=status_style)

    def _get_status_style(self) -> str:
        status_map = {
            "PENDING": "status-pending",
            "FETCHING": "status-active",
            "IMPLEMENTING": "status-active",
            "TESTING": "status-active",
            "FIXING": "status-active",
            "CREATING_PR": "status-active",
            "UPDATING_JIRA": "status-active",
            "COMPLETED": "status-completed",
            "FAILED": "status-failed",
            "MANUAL_REVIEW": "status-review",
        }
        return status_map.get(self.status, "")

    def update_status(self, status: str) -> None:
        self.status = status
        label = self.query_one(Label)
        label.update(f"{self.jira_key} [{status}]")
        label.classes = self._get_status_style()


class TaskQueueWidget(Static):
    """Widget displaying task queue."""

    def compose(self) -> ComposeResult:
        yield Label("Task Queue", classes="widget-title")
        yield ListView(id="task-list")


class CurrentTaskWidget(Static):
    """Widget displaying current task details."""

    def compose(self) -> ComposeResult:
        yield Label("Current Task", classes="widget-title")
        yield Label("No active task", id="current-task-key")
        yield Label("Status: -", id="current-task-status")
        yield Label("Project: -", id="current-task-project")
        yield Label("Attempt: -", id="current-task-attempt")

    def update_task(
        self,
        jira_key: str | None,
        status: str = "-",
        project: str = "-",
        attempt: str = "-",
    ) -> None:
        self.query_one("#current-task-key", Label).update(
            jira_key if jira_key else "No active task"
        )
        self.query_one("#current-task-status", Label).update(f"Status: {status}")
        self.query_one("#current-task-project", Label).update(f"Project: {project}")
        self.query_one("#current-task-attempt", Label).update(f"Attempt: {attempt}")


class LogWidget(Static):
    """Widget for live log output."""

    def compose(self) -> ComposeResult:
        yield Label("Live Output", classes="widget-title")
        yield RichLog(id="log-output", highlight=True, markup=True)

    def write_log(self, message: str) -> None:
        log = self.query_one("#log-output", RichLog)
        timestamp = datetime.now().strftime("%H:%M:%S")
        log.write(f"[dim]{timestamp}[/dim] {message}")


class AddTaskModal(Static):
    """Modal for adding new tasks."""

    def compose(self) -> ComposeResult:
        yield Label("Add Task", classes="modal-title")
        yield Input(placeholder="Enter Jira key (e.g., DEV-123)", id="jira-key-input")
        yield Horizontal(
            Button("Add", id="add-btn", variant="primary"),
            Button("Cancel", id="cancel-btn"),
            classes="modal-buttons",
        )


class TaskOrchestratorApp(App):
    """Main TUI Application."""

    CSS = """
    Screen {
        layout: grid;
        grid-size: 2 2;
        grid-columns: 1fr 2fr;
        grid-rows: 1fr 1fr;
    }

    .widget-title {
        text-style: bold;
        color: cyan;
        padding: 0 1;
        margin-bottom: 1;
    }

    TaskQueueWidget {
        row-span: 2;
        border: solid cyan;
        padding: 1;
    }

    CurrentTaskWidget {
        border: solid green;
        padding: 1;
    }

    LogWidget {
        border: solid yellow;
        padding: 1;
    }

    #log-output {
        height: 100%;
        scrollbar-gutter: stable;
    }

    .status-pending { color: gray; }
    .status-active { color: cyan; }
    .status-completed { color: green; }
    .status-failed { color: red; }
    .status-review { color: yellow; }

    AddTaskModal {
        align: center middle;
        width: 50;
        height: 12;
        border: solid cyan;
        padding: 1 2;
        background: $surface;
        layer: modal;
    }

    .modal-title {
        text-style: bold;
        margin-bottom: 1;
    }

    .modal-buttons {
        margin-top: 1;
        align: center middle;
    }

    .modal-buttons Button {
        margin: 0 1;
    }

    #add-task-modal {
        display: none;
    }

    #add-task-modal.visible {
        display: block;
    }
    """

    BINDINGS = [
        Binding("a", "add_task", "Add Task"),
        Binding("p", "toggle_pause", "Pause/Resume"),
        Binding("c", "cancel_task", "Cancel"),
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self, settings: Settings | None = None):
        super().__init__()
        self._settings = settings or get_settings()
        self._orchestrator: Orchestrator | None = None
        self._task_items: dict[str, TaskListItem] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield TaskQueueWidget()
        yield CurrentTaskWidget()
        yield LogWidget()
        yield Container(AddTaskModal(), id="add-task-modal")
        yield Footer()

    async def on_mount(self) -> None:
        """Initialize on mount."""
        self.title = "Task Orchestrator"
        self.sub_title = "Automate Jira Tasks with Claude CLI"

        # Initialize orchestrator
        self._orchestrator = Orchestrator(
            self._settings,
            on_task_update=self._on_task_update,
            on_log=self._on_log,
        )

        # Start orchestrator in background
        asyncio.create_task(self._orchestrator.start())

        self._log("Orchestrator started. Press 'a' to add a task.")

    def _log(self, message: str) -> None:
        """Write to log widget."""
        try:
            log_widget = self.query_one(LogWidget)
            log_widget.write_log(message)
        except Exception:
            pass

    def _on_task_update(self, jira_key: str, state: TaskState) -> None:
        """Handle task state updates."""
        self.call_from_thread(self._update_task_state, jira_key, state)

    def _update_task_state(self, jira_key: str, state: TaskState) -> None:
        """Update task state in UI."""
        if jira_key in self._task_items:
            self._task_items[jira_key].update_status(state.name)

        # Update current task widget if this is the active task
        if state.is_active():
            current = self.query_one(CurrentTaskWidget)
            current.update_task(jira_key, status=state.name)

    def _on_log(self, jira_key: str, message: str) -> None:
        """Handle log messages from task runner."""
        self.call_from_thread(self._log, f"[{jira_key}] {message}")

    def action_add_task(self) -> None:
        """Show add task modal."""
        modal = self.query_one("#add-task-modal")
        modal.add_class("visible")
        self.query_one("#jira-key-input", Input).focus()

    def action_toggle_pause(self) -> None:
        """Toggle pause/resume."""
        if self._orchestrator:
            if self._orchestrator.is_paused:
                self._orchestrator.resume()
                self._log("Orchestrator resumed")
            else:
                self._orchestrator.pause()
                self._log("Orchestrator paused")

    def action_cancel_task(self) -> None:
        """Cancel selected task."""
        task_list = self.query_one("#task-list", ListView)
        if task_list.highlighted_child:
            item = task_list.highlighted_child
            if isinstance(item, TaskListItem):
                if self._orchestrator:
                    self._orchestrator.cancel_task(item.jira_key)
                    self._log(f"Task {item.jira_key} cancelled")

    def action_refresh(self) -> None:
        """Refresh task list."""
        self._refresh_queue()

    def _refresh_queue(self) -> None:
        """Refresh queue display."""
        if not self._orchestrator:
            return

        task_list = self.query_one("#task-list", ListView)
        task_list.clear()
        self._task_items.clear()

        for task in self._orchestrator.get_queue_status():
            item = TaskListItem(task["jira_key"], task["state"])
            self._task_items[task["jira_key"]] = item
            task_list.append(item)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "add-btn":
            await self._add_task_from_input()
        elif event.button.id == "cancel-btn":
            self._hide_modal()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        if event.input.id == "jira-key-input":
            await self._add_task_from_input()

    async def _add_task_from_input(self) -> None:
        """Add task from input field."""
        input_widget = self.query_one("#jira-key-input", Input)
        jira_key = input_widget.value.strip().upper()

        if jira_key and self._orchestrator:
            if self._orchestrator.add_task(jira_key):
                self._log(f"Task {jira_key} added to queue")

                # Add to list
                task_list = self.query_one("#task-list", ListView)
                item = TaskListItem(jira_key, "PENDING")
                self._task_items[jira_key] = item
                task_list.append(item)
            else:
                self._log(f"Failed to add {jira_key} (already exists?)")

        input_widget.value = ""
        self._hide_modal()

    def _hide_modal(self) -> None:
        """Hide the add task modal."""
        modal = self.query_one("#add-task-modal")
        modal.remove_class("visible")

    async def action_quit(self) -> None:
        """Quit the application."""
        if self._orchestrator:
            await self._orchestrator.stop()
        self.exit()
