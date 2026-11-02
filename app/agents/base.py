"""
app.agents.base
===============

The provider-agnostic contract for coding agents. Telegram handlers and services
depend only on :class:`CodingAgent`, never on a concrete CLI, so a new provider
can be added as one adapter without touching the rest of the app.

A "coding agent" here is a CLI tool (Claude Code, Codex, …) that operates on a
*local clone* of a repository: reading files, explaining code, reviewing diffs,
fixing bugs, generating code/tests. The crash-analysis path is intentionally
separate (it uses the GitHub REST API + a hosted LLM and needs no clone).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class AgentResult:
    """The outcome of a single agent invocation."""

    success: bool
    output: str
    error: Optional[str] = None


@dataclass
class AgentStatus:
    """Availability/health of an agent."""

    name: str
    available: bool
    detail: str = ""


class CodingAgent(abc.ABC):
    """Abstract base all coding-agent adapters implement.

    Concrete adapters typically implement :meth:`run` (the primitive that
    invokes the CLI in a working directory) and inherit the task-shaped helpers
    below, which just build prompts. ``read_only`` tells the adapter whether the
    invocation is allowed to modify files.
    """

    name: str = "base"

    # -- Core primitive ------------------------------------------------------

    @abc.abstractmethod
    async def run(
        self, prompt: str, cwd: Path, read_only: bool = True, timeout: int = 1800
    ) -> AgentResult:
        """Invoke the underlying agent with ``prompt`` inside ``cwd``."""

    @abc.abstractmethod
    async def get_status(self) -> AgentStatus:
        """Report whether the agent is installed/authenticated."""

    # -- Task-shaped helpers (shared across adapters) ------------------------

    async def analyze(self, cwd: Path, instruction: str) -> AgentResult:
        prompt = (
            "Analyze this repository and answer the request below. "
            "Do not modify any files; report findings only.\n\n"
            f"Request: {instruction}"
        )
        return await self.run(prompt, cwd, read_only=True)

    async def explain_code(self, cwd: Path, target: str) -> AgentResult:
        prompt = (
            "Explain the following code / file / symbol clearly and concisely, "
            "reading the actual source as needed. Do not modify files.\n\n"
            f"Target: {target}"
        )
        return await self.run(prompt, cwd, read_only=True)

    async def review_code(self, cwd: Path, diff_or_scope: str) -> AgentResult:
        prompt = (
            "Perform a code review. Identify bugs, quality issues, security "
            "concerns, and performance problems. Group findings by severity "
            "(Critical, High, Medium, Low, Informational) and cite file paths "
            "and line numbers. Do not modify files.\n\n"
            f"Scope:\n{diff_or_scope}"
        )
        return await self.run(prompt, cwd, read_only=True)

    async def fix_bug(self, cwd: Path, instruction: str) -> AgentResult:
        prompt = (
            "Fix the bug described below. Locate the relevant source, make the "
            "minimal correct change, and briefly summarize what you changed and "
            "why. Apply the edits to the working tree.\n\n"
            f"Bug / request: {instruction}"
        )
        return await self.run(prompt, cwd, read_only=False)

    async def refactor(self, cwd: Path, instruction: str) -> AgentResult:
        prompt = (
            "Refactor the code as described below without changing behavior. "
            "Apply the edits and summarize the changes.\n\n"
            f"Refactor request: {instruction}"
        )
        return await self.run(prompt, cwd, read_only=False)

    async def generate_code(self, cwd: Path, instruction: str) -> AgentResult:
        prompt = (
            "Implement the feature/change described below. Apply the edits to "
            "the working tree and summarize what you added.\n\n"
            f"Request: {instruction}"
        )
        return await self.run(prompt, cwd, read_only=False)

    async def generate_tests(self, cwd: Path, instruction: str) -> AgentResult:
        prompt = (
            "Generate unit tests for the code described below. Follow the "
            "project's existing test conventions and framework. Apply the new "
            "test files to the working tree and summarize coverage.\n\n"
            f"Target: {instruction}"
        )
        return await self.run(prompt, cwd, read_only=False)

    async def execute_task(
        self, cwd: Path, instruction: str, read_only: bool = False
    ) -> AgentResult:
        """Generic free-form task (used for natural-language requests)."""
        return await self.run(instruction, cwd, read_only=read_only)
