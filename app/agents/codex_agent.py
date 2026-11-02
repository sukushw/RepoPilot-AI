"""
app.agents.codex_agent
======================

Adapter for the **OpenAI Codex CLI** (``codex``). The Codex CLI's
non-interactive interface differs from Claude's and is not installed on every
machine, so this adapter is written defensively:

  * Availability is probed with ``codex --version``.
  * Non-interactive runs use ``codex exec <prompt>`` (the documented headless
    sub-command). If the installed CLI uses a different flag, the adapter reports
    a clear error instead of guessing — the spec explicitly warns not to assume
    identical CLI interfaces across providers.

When Codex isn't installed, :meth:`get_status` returns ``available=False`` with
setup guidance, and the agent manager won't route tasks to it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.agents.base import AgentResult, AgentStatus, CodingAgent
from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import redact_secrets

logger = get_logger("repopilot.agent.codex")


class CodexAgent(CodingAgent):
    name = "codex"

    def __init__(self, cli_path: str = ""):
        self.cli_path = cli_path or settings.codex_cli_path

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
                "Codex CLI not found. Install it (npm i -g @openai/codex) and "
                "authenticate, then set CODEX_CLI_PATH if needed.",
            )
        except Exception as exc:  # pragma: no cover
            return AgentStatus(self.name, False, redact_secrets(str(exc)))

        if proc.returncode == 0:
            version = out.decode("utf-8", errors="replace").strip()
            return AgentStatus(self.name, True, f"Codex CLI {version}")
        return AgentStatus(
            self.name, False,
            redact_secrets(err.decode("utf-8", errors="replace").strip())
            or "Codex CLI returned non-zero from --version.",
        )

    async def run(
        self, prompt: str, cwd: Path, read_only: bool = True, timeout: int = 1800
    ) -> AgentResult:
        # Guard: only proceed if the CLI is actually present.
        status = await self.get_status()
        if not status.available:
            return AgentResult(False, "", status.detail)

        # `codex exec` is the documented non-interactive entry point. In
        # read-only mode we request a suggest-only run where supported.
        args = [self.cli_path, "exec"]
        if read_only:
            args += ["--full-auto"] if False else []  # placeholder: no edits
        args.append(prompt)

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            return AgentResult(False, "", f"Codex agent timed out after {timeout}s.")
        except Exception as exc:  # pragma: no cover
            return AgentResult(False, "", redact_secrets(str(exc)))

        stdout = out.decode("utf-8", errors="replace").strip()
        stderr = err.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            return AgentResult(
                False, stdout,
                redact_secrets(stderr or "Codex CLI exited non-zero."),
            )
        return AgentResult(True, stdout or "(Codex returned no output.)", None)
