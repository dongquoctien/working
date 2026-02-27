"""Configuration settings loader with YAML and environment variables support."""

from __future__ import annotations

import os
import re
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class TrackerType(str, Enum):
    """Supported issue tracker types."""

    JIRA = "jira"
    REDMINE = "redmine"


class JiraConfig(BaseModel):
    """Jira configuration."""

    url: str = "https://company.atlassian.net"
    email: str = ""
    api_token: str = ""


class RedmineConfig(BaseModel):
    """Redmine configuration."""

    url: str = "https://redmine.company.com"
    api_key: str = ""
    # Status names (customize based on your Redmine workflow)
    done_status: str = "Closed"
    in_progress_status: str = "In Progress"


class BitbucketConfig(BaseModel):
    """Bitbucket configuration."""

    workspace: str = ""
    username: str = ""
    app_password: str = ""


class ProjectConfig(BaseModel):
    """Project configuration."""

    name: str
    path: str
    test_command: str = "gradlew test"
    build_command: str = "gradlew build"
    branch_prefix: str = "feature"
    # Optional: specify tracker for this project (overrides global setting)
    tracker: TrackerType | None = None


class WorkflowConfig(BaseModel):
    """Workflow configuration."""

    max_retries: int = 5
    retry_delay_seconds: int = 10
    auto_create_pr: bool = True
    auto_update_tracker: bool = True  # Renamed from auto_update_jira
    # Status names (can be overridden by tracker-specific config)
    done_status: str = "Done"
    in_progress_status: str = "In Progress"


class ClaudeConfig(BaseModel):
    """Claude CLI configuration."""

    model: str = "sonnet"
    timeout_minutes: int = 30
    cli_path: str = "claude"


class Settings(BaseSettings):
    """Application settings."""

    # Tracker selection - which tracker to use by default
    tracker: TrackerType = TrackerType.JIRA

    # Tracker configurations
    jira: JiraConfig = Field(default_factory=JiraConfig)
    redmine: RedmineConfig = Field(default_factory=RedmineConfig)

    # Other configs
    bitbucket: BitbucketConfig = Field(default_factory=BitbucketConfig)
    projects: list[ProjectConfig] = Field(default_factory=list)
    workflow: WorkflowConfig = Field(default_factory=WorkflowConfig)
    claude: ClaudeConfig = Field(default_factory=ClaudeConfig)

    # App settings
    log_dir: str = "logs"
    history_file: str = "history.json"

    class Config:
        env_prefix = "ORCHESTRATOR_"
        env_nested_delimiter = "__"

    def get_done_status(self) -> str:
        """Get done status based on active tracker."""
        if self.tracker == TrackerType.REDMINE:
            return self.redmine.done_status
        return self.workflow.done_status

    def get_in_progress_status(self) -> str:
        """Get in-progress status based on active tracker."""
        if self.tracker == TrackerType.REDMINE:
            return self.redmine.in_progress_status
        return self.workflow.in_progress_status


def _resolve_env_vars(value: Any) -> Any:
    """Resolve environment variables in string values like ${VAR_NAME}."""
    if isinstance(value, str):
        pattern = r"\$\{([^}]+)\}"
        matches = re.findall(pattern, value)
        for match in matches:
            env_value = os.getenv(match, "")
            value = value.replace(f"${{{match}}}", env_value)
        return value
    elif isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


def load_config_file(config_path: Path | None = None) -> dict[str, Any]:
    """Load configuration from YAML file."""
    if config_path is None:
        # Try default locations
        locations = [
            Path("config/config.yaml"),
            Path("config.yaml"),
            Path.home() / ".task-orchestrator" / "config.yaml",
        ]
        for loc in locations:
            if loc.exists():
                config_path = loc
                break

    if config_path is None or not config_path.exists():
        return {}

    with open(config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f) or {}

    # Resolve environment variables
    return _resolve_env_vars(config_data)


@lru_cache
def get_settings(config_path: str | None = None) -> Settings:
    """Get application settings (cached)."""
    path = Path(config_path) if config_path else None
    config_data = load_config_file(path)

    # Convert tracker string to enum
    if "tracker" in config_data:
        config_data["tracker"] = TrackerType(config_data["tracker"].lower())

    # Convert nested dicts to Pydantic models
    if "jira" in config_data:
        config_data["jira"] = JiraConfig(**config_data["jira"])
    if "redmine" in config_data:
        config_data["redmine"] = RedmineConfig(**config_data["redmine"])
    if "bitbucket" in config_data:
        config_data["bitbucket"] = BitbucketConfig(**config_data["bitbucket"])
    if "projects" in config_data:
        projects = []
        for p in config_data["projects"]:
            if "tracker" in p and isinstance(p["tracker"], str):
                p["tracker"] = TrackerType(p["tracker"].lower())
            projects.append(ProjectConfig(**p))
        config_data["projects"] = projects
    if "workflow" in config_data:
        config_data["workflow"] = WorkflowConfig(**config_data["workflow"])
    if "claude" in config_data:
        config_data["claude"] = ClaudeConfig(**config_data["claude"])

    return Settings(**config_data)


def clear_settings_cache() -> None:
    """Clear the settings cache."""
    get_settings.cache_clear()
