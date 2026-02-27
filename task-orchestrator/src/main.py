"""Main entry point for Task Orchestrator."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from rich.console import Console

from src.config import get_settings, clear_settings_cache
from src.config.settings import TrackerType
from src.utils.logger import setup_logging, print_banner
from src.ui import TaskOrchestratorApp
from src.core import Orchestrator


console = Console()


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Task Orchestrator - Automate Jira/Redmine tasks with Claude CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "-c", "--config",
        type=str,
        help="Path to config file (default: config/config.yaml)",
    )

    parser.add_argument(
        "--run",
        type=str,
        metavar="ISSUE_KEY",
        help="Run a single task immediately (bypass TUI)",
    )

    parser.add_argument(
        "--check",
        action="store_true",
        help="Check connections (Tracker, Bitbucket, Claude CLI)",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    return parser.parse_args()


def check_connections(settings) -> bool:
    """Check all service connections."""
    from src.integrations import (
        JiraClient,
        RedmineClient,
        BitbucketClient,
        ClaudeCLI,
        create_tracker_client,
    )

    console.print("\n[bold]Checking connections...[/bold]\n")
    console.print(f"Active tracker: [cyan]{settings.tracker.value}[/cyan]\n")
    all_ok = True

    # Check Claude CLI
    console.print("Claude CLI: ", end="")
    claude = ClaudeCLI(settings)
    if claude.test_cli_available():
        console.print("[green]OK[/green]")
    else:
        console.print("[red]NOT FOUND[/red]")
        console.print("  Make sure 'claude' is in your PATH")
        all_ok = False

    # Check active tracker (Jira or Redmine)
    tracker_name = settings.tracker.value.capitalize()
    console.print(f"{tracker_name}: ", end="")
    tracker = create_tracker_client(settings)
    if tracker.test_connection():
        console.print("[green]OK[/green]")
    else:
        console.print("[red]FAILED[/red]")
        console.print(f"  Check your {tracker_name} credentials in config")
        all_ok = False

    # Optionally check the other tracker if configured
    if settings.tracker == TrackerType.JIRA and settings.redmine.api_key:
        console.print("Redmine (backup): ", end="")
        redmine = RedmineClient(settings)
        if redmine.test_connection():
            console.print("[green]OK[/green]")
        else:
            console.print("[yellow]NOT CONFIGURED[/yellow]")
    elif settings.tracker == TrackerType.REDMINE and settings.jira.api_token:
        console.print("Jira (backup): ", end="")
        jira = JiraClient(settings)
        if jira.test_connection():
            console.print("[green]OK[/green]")
        else:
            console.print("[yellow]NOT CONFIGURED[/yellow]")

    # Check Bitbucket
    console.print("Bitbucket: ", end="")
    bitbucket = BitbucketClient(settings)
    if bitbucket.test_connection():
        console.print("[green]OK[/green]")
    else:
        console.print("[red]FAILED[/red]")
        console.print("  Check your Bitbucket credentials in config")
        all_ok = False

    console.print()
    return all_ok


async def run_single_task(issue_key: str, settings) -> int:
    """Run a single task without TUI."""
    tracker_name = settings.tracker.value.capitalize()
    console.print(f"\n[bold]Running task: {issue_key}[/bold]")
    console.print(f"Tracker: [cyan]{tracker_name}[/cyan]\n")

    orchestrator = Orchestrator(
        settings,
        on_log=lambda key, msg: console.print(f"[dim]{key}[/dim] {msg}"),
    )

    result = await orchestrator.run_single(issue_key)

    if result.success:
        console.print(f"\n[green]Task completed successfully![/green]")
        if result.pr_url:
            console.print(f"PR: {result.pr_url}")
        return 0
    else:
        console.print(f"\n[red]Task failed![/red]")
        console.print(f"Error: {result.error_message}")
        return 1


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Setup logging
    import logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    setup_logging(level=log_level)

    # Load settings
    clear_settings_cache()
    settings = get_settings(args.config)

    # Check connections mode
    if args.check:
        print_banner()
        success = check_connections(settings)
        return 0 if success else 1

    # Single task mode
    if args.run:
        print_banner()
        return asyncio.run(run_single_task(args.run, settings))

    # TUI mode
    app = TaskOrchestratorApp(settings)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
