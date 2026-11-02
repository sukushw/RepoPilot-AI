"""
app.execution.docker_runner
===========================

Runs build/test commands for a repository. Repository code is *untrusted*, so
when Docker is available (and ``USE_DOCKER=true``) commands run inside a
throwaway container with the repo mounted read-write but the network and the
rest of the host filesystem kept out.

When Docker isn't available (the common local-demo case on this machine), we
fall back to running the command locally as a subprocess with a hard timeout and
no shell interpolation. This is clearly less isolated — the README documents the
trade-off — but keeps the demo runnable on a plain laptop.

The command is always passed as an argument *list* (never a shell string), so
untrusted repository content can't inject shell metacharacters.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("repopilot.exec")


@dataclass
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    isolated: bool = False  # True if it ran inside Docker

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    @property
    def combined_output(self) -> str:
        return (self.stdout + "\n" + self.stderr).strip()


def docker_available() -> bool:
    return shutil.which("docker") is not None


async def _run_local(
    args: List[str], cwd: Path, timeout: int
) -> CommandResult:
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return CommandResult(
            exit_code=-1, stdout="", stderr=f"Command timed out after {timeout}s",
            timed_out=True, isolated=False,
        )
    return CommandResult(
        exit_code=proc.returncode or 0,
        stdout=out.decode("utf-8", errors="replace"),
        stderr=err.decode("utf-8", errors="replace"),
        isolated=False,
    )


async def _run_docker(
    args: List[str], cwd: Path, timeout: int, image: str
) -> CommandResult:
    docker_args = [
        "docker", "run", "--rm",
        "--network", "none",            # no network for untrusted code
        "--memory", "2g",
        "-w", "/work",
        "-v", f"{cwd}:/work",
        image,
        *args,
    ]
    result = await _run_local(docker_args, cwd=cwd, timeout=timeout)
    result.isolated = True
    return result


async def run_command(
    args: List[str],
    cwd: Path,
    timeout: Optional[int] = None,
    docker_image: str = "eclipse-temurin:17-jdk",
) -> CommandResult:
    """Run ``args`` in ``cwd`` (Docker-isolated if enabled/available)."""
    timeout = timeout or settings.task_timeout_seconds
    if settings.use_docker and docker_available():
        logger.info("Running in Docker (%s): %s", docker_image, " ".join(args))
        return await _run_docker(args, cwd, timeout, docker_image)
    logger.info("Running locally (no docker isolation): %s", " ".join(args))
    return await _run_local(args, cwd, timeout)
