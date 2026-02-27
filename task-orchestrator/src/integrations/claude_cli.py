"""Claude CLI wrapper for AI-powered code implementation."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncGenerator

from src.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class ClaudeResponse:
    """Response from Claude CLI."""

    success: bool
    output: str
    error: str = ""
    exit_code: int = 0


class ClaudeCLI:
    """Wrapper for Claude CLI operations."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._cli_path = settings.claude.cli_path
        self._timeout = settings.claude.timeout_minutes * 60  # Convert to seconds

    def _build_command(
        self,
        prompt: str,
        project_path: str,
        print_mode: bool = True,
    ) -> list[str]:
        """Build Claude CLI command."""
        cmd = [self._cli_path]

        if print_mode:
            cmd.append("--print")

        # Add model if specified
        if self._settings.claude.model:
            cmd.extend(["--model", self._settings.claude.model])

        cmd.append(prompt)
        return cmd

    async def execute(
        self,
        prompt: str,
        project_path: str,
        stream_output: bool = False,
    ) -> ClaudeResponse:
        """
        Execute Claude CLI with a prompt.

        Args:
            prompt: The prompt/instruction for Claude
            project_path: Working directory for execution
            stream_output: Whether to stream output (for live display)

        Returns:
            ClaudeResponse with result
        """
        cmd = self._build_command(prompt, project_path)
        logger.info(f"Executing Claude CLI in {project_path}")
        logger.debug(f"Command: {' '.join(cmd)}")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._timeout,
            )

            return ClaudeResponse(
                success=process.returncode == 0,
                output=stdout.decode("utf-8", errors="replace"),
                error=stderr.decode("utf-8", errors="replace"),
                exit_code=process.returncode or 0,
            )

        except asyncio.TimeoutError:
            logger.error(f"Claude CLI timed out after {self._timeout}s")
            return ClaudeResponse(
                success=False,
                output="",
                error=f"Timeout after {self._settings.claude.timeout_minutes} minutes",
                exit_code=-1,
            )
        except Exception as e:
            logger.error(f"Claude CLI execution failed: {e}")
            return ClaudeResponse(
                success=False,
                output="",
                error=str(e),
                exit_code=-1,
            )

    async def stream_execute(
        self,
        prompt: str,
        project_path: str,
    ) -> AsyncGenerator[str, None]:
        """
        Execute Claude CLI and stream output line by line.

        Args:
            prompt: The prompt/instruction for Claude
            project_path: Working directory

        Yields:
            Output lines as they become available
        """
        cmd = self._build_command(prompt, project_path)
        logger.info(f"Streaming Claude CLI execution in {project_path}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=project_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        try:
            async for line in process.stdout:
                decoded = line.decode("utf-8", errors="replace").rstrip()
                yield decoded

            await process.wait()

        except asyncio.CancelledError:
            process.terminate()
            await process.wait()
            raise

    def execute_sync(
        self,
        prompt: str,
        project_path: str,
    ) -> ClaudeResponse:
        """
        Synchronous execution of Claude CLI.

        Args:
            prompt: The prompt/instruction for Claude
            project_path: Working directory

        Returns:
            ClaudeResponse with result
        """
        cmd = self._build_command(prompt, project_path)
        logger.info(f"Executing Claude CLI (sync) in {project_path}")

        try:
            result = subprocess.run(
                cmd,
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )

            return ClaudeResponse(
                success=result.returncode == 0,
                output=result.stdout,
                error=result.stderr,
                exit_code=result.returncode,
            )

        except subprocess.TimeoutExpired:
            return ClaudeResponse(
                success=False,
                output="",
                error=f"Timeout after {self._settings.claude.timeout_minutes} minutes",
                exit_code=-1,
            )
        except Exception as e:
            return ClaudeResponse(
                success=False,
                output="",
                error=str(e),
                exit_code=-1,
            )

    async def implement_task(
        self,
        task_description: str,
        project_path: str,
        additional_context: str = "",
    ) -> ClaudeResponse:
        """
        Implement a task/feature.

        Args:
            task_description: Description of what to implement
            project_path: Project directory
            additional_context: Extra context/requirements

        Returns:
            ClaudeResponse with result
        """
        prompt = f"""Please implement the following task:

{task_description}

{additional_context}

Requirements:
- Write clean, maintainable code
- Follow existing project patterns and conventions
- Add appropriate error handling
- Include comments where necessary

Please implement this task now."""

        return await self.execute(prompt, project_path)

    async def fix_test_failures(
        self,
        error_log: str,
        project_path: str,
        test_file: str = "",
    ) -> ClaudeResponse:
        """
        Fix failing tests based on error output.

        Args:
            error_log: Test failure output
            project_path: Project directory
            test_file: Specific test file that failed (optional)

        Returns:
            ClaudeResponse with result
        """
        prompt = f"""The tests are failing with the following errors:

```
{error_log}
```

Please analyze the error and fix the code to make the tests pass.
Focus on:
1. Understanding what the test expects
2. Finding the root cause of the failure
3. Fixing the implementation (not the test, unless the test is clearly wrong)

Fix the issues now."""

        return await self.execute(prompt, project_path)

    async def generate_pr_description(
        self,
        task_description: str,
        changes_summary: str,
        project_path: str,
    ) -> str:
        """
        Generate PR description.

        Args:
            task_description: Original task description
            changes_summary: Git diff summary
            project_path: Project directory

        Returns:
            Generated PR description
        """
        prompt = f"""Generate a concise pull request description for the following:

Task: {task_description}

Changes made:
{changes_summary}

Format the description with:
- Brief summary (1-2 sentences)
- List of key changes
- Any important notes for reviewers

Output only the PR description, no extra commentary."""

        response = await self.execute(prompt, project_path)
        return response.output if response.success else ""

    def test_cli_available(self) -> bool:
        """Check if Claude CLI is available."""
        try:
            result = subprocess.run(
                [self._cli_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            logger.info(f"Claude CLI available: {result.stdout.strip()}")
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Claude CLI not available: {e}")
            return False
