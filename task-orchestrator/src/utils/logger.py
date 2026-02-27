"""Rich-formatted logging setup."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

import os

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

# Force UTF-8 on Windows
if sys.platform == "win32":
    os.system("")  # Enable ANSI escape sequences on Windows
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore

# Custom theme for logging
CUSTOM_THEME = Theme(
    {
        "info": "cyan",
        "warning": "yellow",
        "error": "bold red",
        "success": "bold green",
        "task": "bold magenta",
        "state": "bold blue",
    }
)

# Global console instance
console = Console(theme=CUSTOM_THEME, force_terminal=True)


class TaskFormatter(logging.Formatter):
    """Custom formatter for task-related logs."""

    def format(self, record: logging.LogRecord) -> str:
        # Add task key if available
        if hasattr(record, "task_key"):
            record.msg = f"[{record.task_key}] {record.msg}"
        return super().format(record)


def setup_logging(
    log_dir: str | Path = "logs",
    level: int = logging.INFO,
    log_to_file: bool = True,
) -> None:
    """
    Setup logging with Rich console handler and optional file handler.

    Args:
        log_dir: Directory to store log files
        level: Logging level
        log_to_file: Whether to also log to file
    """
    # Create log directory
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear existing handlers
    root_logger.handlers.clear()

    # Rich console handler
    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
        tracebacks_show_locals=True,
        markup=True,
    )
    rich_handler.setFormatter(TaskFormatter("%(message)s"))
    root_logger.addHandler(rich_handler)

    # File handler
    if log_to_file:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_path / f"orchestrator_{timestamp}.log"

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root_logger.addHandler(file_handler)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the specified name."""
    return logging.getLogger(name)


class TaskLogger:
    """Logger wrapper for task-specific logging."""

    def __init__(self, task_key: str):
        self.task_key = task_key
        self._logger = logging.getLogger(f"task.{task_key}")

    def _log(self, level: int, msg: str, *args, **kwargs) -> None:
        extra = kwargs.pop("extra", {})
        extra["task_key"] = self.task_key
        self._logger.log(level, msg, *args, extra=extra, **kwargs)

    def info(self, msg: str, *args, **kwargs) -> None:
        self._log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs) -> None:
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs) -> None:
        self._log(logging.ERROR, msg, *args, **kwargs)

    def debug(self, msg: str, *args, **kwargs) -> None:
        self._log(logging.DEBUG, msg, *args, **kwargs)

    def state_change(self, from_state: str, to_state: str) -> None:
        """Log a state transition."""
        self.info(f"State: [state]{from_state}[/state] -> [state]{to_state}[/state]")

    def success(self, msg: str) -> None:
        """Log success message."""
        self.info(f"[success]{msg}[/success]")

    def test_result(self, passed: bool, details: str = "") -> None:
        """Log test result."""
        if passed:
            self.info(f"[success]Tests PASSED[/success] {details}")
        else:
            self.warning(f"[error]Tests FAILED[/error] {details}")


def print_banner() -> None:
    """Print application banner."""
    banner = """
+==============================================================+
|                    Task Orchestrator                         |
|         Automate Jira/Redmine Tasks with Claude CLI          |
+==============================================================+
"""
    console.print(banner, style="bold cyan")
