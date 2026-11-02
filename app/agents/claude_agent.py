"""
app.agents.claude_agent
=======================

Adapter for the **Claude Code CLI** (``claude``). Verified against the installed
CLI interface (``claude --help``):

  * ``-p/--print``                    non-interactive output
  * ``--output-format json``          single JSON result object
  * ``--permission-mode <mode>``      acceptEdits | plan | …
  * ``--model <alias>``               optional (e.g. "sonnet", "opus")
  * ``--add-dir`` / cwd               scope tool access to the clone

Read-only invocations use ``--permission-mode plan`` (explores + answers, never
edits). Write invocations use ``--permission-mode acceptEdits`` so file edits are
applied to the working tree without an interactive prompt. The working directory
is the repository clone, which scopes file access to that repo.

Availability is checked with ``claude --version``; a missing/unauthenticated CLI
produces a clear, actionable error rather than a crash.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from app.agents.base import AgentResult, AgentStatus, CodingAgent
from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import redact_secrets

logger = get_logger("repopilot.agent.claude")


class ClaudeCodeAgent(CodingAgent):
    name = "claude"

    def __init__(self, cli_path: str = "", model: str = ""):
        self.cli_path = cli_path or settings.claude_cli_path
        self.model = model or settings.claude_model

    async def get_status(self) -> AgentStatus:
        try:
            proc = await asyncio.create_subprocess_exec(
                self.cli_path, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=20)
        except FileNotFoundError:
            return AgentStatus(
                self.name, False,
                "Claude Code CLI not found. Install it and ensure `claude` is on PATH.",
            )
        except Exception as exc:  # pragma: no cover - environment dependent
            return AgentStatus(self.name, False, redact_secrets(str(exc)))

        if proc.returncode == 0:
            version = out.decode("utf-8", errors="replace").strip()
            return AgentStatus(self.name, True, f"Claude Code {version}")
        return AgentStatus(
            self.name, False,
            redact_secrets(err.decode("utf-8", errors="replace").strip())
            or "Claude CLI returned a non-zero exit from --version.",
        )

    async def run(
        self, prompt: str, cwd: Path, read_only: bool = True, timeout: int = 1800
    ) -> AgentResult:
        mode = "plan" if read_only else os.getenv(
            "CLAUDE_PERMISSION_MODE", "acceptEdits"
        )
        args = [
            self.cli_path,
            "-p", prompt,
            "--output-format", "json",
            "--permission-mode", mode,
        ]
        if self.model:
            args += ["--model", self.model]
        if os.getenv("CLAUDE_SKIP_PERMISSIONS", "").lower() in ("1", "true", "yes"):
            args.append("--dangerously-skip-permissions")

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except FileNotFoundError:
            return AgentResult(
                False, "",
                "Claude Code CLI not found. Install it and set CLAUDE_CLI_PATH.",
            )
        except asyncio.TimeoutError:
            return AgentResult(False, "", f"Claude agent timed out after {timeout}s.")
        except Exception as exc:  # pragma: no cover
            return AgentResult(False, "", redact_secrets(str(exc)))

        stdout = out.decode("utf-8", errors="replace")
        stderr = err.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            return AgentResult(
                False, stdout,
                redact_secrets(stderr.strip() or "Claude CLI exited non-zero."),
            )

        text = self._extract_text(stdout)
        return AgentResult(True, text, None)

    @staticmethod
    def _extract_text(stdout: str) -> str:
        """Pull the final assistant text out of the JSON result object."""
        stdout = stdout.strip()
        if not stdout:
            return "(Claude returned no output.)"
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return stdout  # Already plain text.
        if isinstance(data, dict):
            # The CLI's json result object exposes the answer under "result".
            return (
                data.get("result")
                or data.get("output")
                or json.dumps(data)[:4000]
            )
        return stdout
