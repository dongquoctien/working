"""Test runner for detecting and running project tests."""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

from src.config import ProjectConfig

logger = logging.getLogger(__name__)


class ProjectType(Enum):
    """Project types based on build system."""

    GRADLE = auto()
    MAVEN = auto()
    NPM = auto()
    UNKNOWN = auto()


@dataclass
class TestError:
    """Single test error details."""

    test_name: str
    test_class: str
    message: str
    stack_trace: str = ""


@dataclass
class TestResult:
    """Test execution result."""

    success: bool
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[TestError] = field(default_factory=list)
    output: str = ""
    duration_seconds: float = 0.0

    @property
    def summary(self) -> str:
        """Human-readable summary."""
        if self.success:
            return f"PASSED ({self.passed}/{self.total_tests} tests)"
        return f"FAILED ({self.failed} failures, {self.passed} passed)"


class TestRunner:
    """Runner for project tests with auto-detection."""

    def __init__(self, project_config: ProjectConfig | None = None):
        self._config = project_config

    def detect_project_type(self, project_path: str) -> ProjectType:
        """
        Detect project type based on build files.

        Args:
            project_path: Path to project directory

        Returns:
            ProjectType enum value
        """
        path = Path(project_path)

        # Check for build files
        if (path / "build.gradle").exists() or (path / "build.gradle.kts").exists():
            logger.debug(f"Detected Gradle project: {project_path}")
            return ProjectType.GRADLE

        if (path / "pom.xml").exists():
            logger.debug(f"Detected Maven project: {project_path}")
            return ProjectType.MAVEN

        if (path / "package.json").exists():
            logger.debug(f"Detected NPM project: {project_path}")
            return ProjectType.NPM

        logger.warning(f"Unknown project type: {project_path}")
        return ProjectType.UNKNOWN

    def _get_test_command(self, project_path: str) -> list[str]:
        """Get test command for project."""
        # Use configured command if available
        if self._config and self._config.test_command:
            cmd = self._config.test_command
            # Handle gradlew on Windows
            if cmd.startswith("gradlew"):
                cmd = cmd.replace("gradlew", "gradlew.bat", 1)
            return cmd.split()

        # Auto-detect
        project_type = self.detect_project_type(project_path)
        path = Path(project_path)

        if project_type == ProjectType.GRADLE:
            if (path / "gradlew.bat").exists():
                return ["gradlew.bat", "test"]
            return ["gradle", "test"]

        if project_type == ProjectType.MAVEN:
            return ["mvn", "test"]

        if project_type == ProjectType.NPM:
            return ["npm", "test"]

        raise ValueError(f"Cannot determine test command for {project_path}")

    async def run_tests(self, project_path: str) -> TestResult:
        """
        Run tests for the project.

        Args:
            project_path: Path to project directory

        Returns:
            TestResult with execution details
        """
        import time

        cmd = self._get_test_command(project_path)
        logger.info(f"Running tests: {' '.join(cmd)}")

        start_time = time.time()

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=None,  # Use parent environment
            )

            stdout, _ = await process.communicate()
            output = stdout.decode("utf-8", errors="replace")

            duration = time.time() - start_time
            success = process.returncode == 0

            # Parse results based on project type
            project_type = self.detect_project_type(project_path)
            result = self._parse_test_output(output, project_type)
            result.success = success
            result.output = output
            result.duration_seconds = duration

            logger.info(f"Tests completed: {result.summary}")
            return result

        except Exception as e:
            logger.error(f"Test execution failed: {e}")
            return TestResult(
                success=False,
                output=str(e),
                duration_seconds=time.time() - start_time,
            )

    def run_tests_sync(self, project_path: str) -> TestResult:
        """
        Run tests synchronously.

        Args:
            project_path: Path to project directory

        Returns:
            TestResult with execution details
        """
        import time

        cmd = self._get_test_command(project_path)
        logger.info(f"Running tests (sync): {' '.join(cmd)}")

        start_time = time.time()

        try:
            result = subprocess.run(
                cmd,
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout
            )

            output = result.stdout + result.stderr
            duration = time.time() - start_time
            success = result.returncode == 0

            project_type = self.detect_project_type(project_path)
            test_result = self._parse_test_output(output, project_type)
            test_result.success = success
            test_result.output = output
            test_result.duration_seconds = duration

            logger.info(f"Tests completed: {test_result.summary}")
            return test_result

        except subprocess.TimeoutExpired:
            return TestResult(
                success=False,
                output="Test execution timed out after 10 minutes",
                duration_seconds=600,
            )
        except Exception as e:
            return TestResult(
                success=False,
                output=str(e),
                duration_seconds=time.time() - start_time,
            )

    def _parse_test_output(self, output: str, project_type: ProjectType) -> TestResult:
        """Parse test output to extract results."""
        if project_type == ProjectType.GRADLE:
            return self._parse_gradle_output(output)
        elif project_type == ProjectType.MAVEN:
            return self._parse_maven_output(output)
        elif project_type == ProjectType.NPM:
            return self._parse_npm_output(output)
        else:
            return TestResult(success=False, output=output)

    def _parse_gradle_output(self, output: str) -> TestResult:
        """Parse Gradle test output."""
        result = TestResult(success=True)

        # Look for test summary
        # Example: "3 tests completed, 1 failed"
        summary_pattern = r"(\d+) tests? completed(?:, (\d+) failed)?(?:, (\d+) skipped)?"
        match = re.search(summary_pattern, output)

        if match:
            result.total_tests = int(match.group(1))
            result.failed = int(match.group(2)) if match.group(2) else 0
            result.skipped = int(match.group(3)) if match.group(3) else 0
            result.passed = result.total_tests - result.failed - result.skipped

        # Parse individual failures
        # Example: "MyTest > testMethod FAILED"
        failure_pattern = r"(\w+) > (\w+).*FAILED"
        for match in re.finditer(failure_pattern, output):
            result.errors.append(
                TestError(
                    test_class=match.group(1),
                    test_name=match.group(2),
                    message="Test failed",
                )
            )

        return result

    def _parse_maven_output(self, output: str) -> TestResult:
        """Parse Maven test output."""
        result = TestResult(success=True)

        # Look for Surefire summary
        # Example: "Tests run: 5, Failures: 1, Errors: 0, Skipped: 0"
        summary_pattern = r"Tests run: (\d+), Failures: (\d+), Errors: (\d+), Skipped: (\d+)"
        match = re.search(summary_pattern, output)

        if match:
            result.total_tests = int(match.group(1))
            result.failed = int(match.group(2)) + int(match.group(3))
            result.skipped = int(match.group(4))
            result.passed = result.total_tests - result.failed - result.skipped

        # Parse failures
        # Example: "testMethod(com.example.MyTest)  Time elapsed: 0.1 s  <<< FAILURE!"
        failure_pattern = r"(\w+)\(([^)]+)\).*<<<\s+(FAILURE|ERROR)"
        for match in re.finditer(failure_pattern, output):
            result.errors.append(
                TestError(
                    test_name=match.group(1),
                    test_class=match.group(2),
                    message=match.group(3),
                )
            )

        return result

    def _parse_npm_output(self, output: str) -> TestResult:
        """Parse NPM/Jest test output."""
        result = TestResult(success=True)

        # Jest summary
        # Example: "Tests:       1 failed, 5 passed, 6 total"
        summary_pattern = r"Tests:\s+(?:(\d+) failed,\s+)?(?:(\d+) skipped,\s+)?(\d+) passed,\s+(\d+) total"
        match = re.search(summary_pattern, output)

        if match:
            result.failed = int(match.group(1)) if match.group(1) else 0
            result.skipped = int(match.group(2)) if match.group(2) else 0
            result.passed = int(match.group(3))
            result.total_tests = int(match.group(4))

        # Parse failed test names
        # Example: "✕ should do something (5 ms)"
        failure_pattern = r"[✕×]\s+(.+?)\s+\("
        for match in re.finditer(failure_pattern, output):
            result.errors.append(
                TestError(
                    test_name=match.group(1),
                    test_class="",
                    message="Test failed",
                )
            )

        return result

    def get_error_summary(self, result: TestResult, max_lines: int = 50) -> str:
        """
        Get a summary of errors for Claude to fix.

        Args:
            result: TestResult from test run
            max_lines: Maximum lines of output to include

        Returns:
            Error summary string
        """
        parts = [f"Test Result: {result.summary}", ""]

        if result.errors:
            parts.append("Failed Tests:")
            for error in result.errors:
                parts.append(f"  - {error.test_class}.{error.test_name}: {error.message}")
            parts.append("")

        # Include relevant output (last N lines)
        if result.output:
            lines = result.output.strip().split("\n")
            if len(lines) > max_lines:
                lines = lines[-max_lines:]
                parts.append(f"Output (last {max_lines} lines):")
            else:
                parts.append("Full Output:")
            parts.extend(lines)

        return "\n".join(parts)
