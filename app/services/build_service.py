"""
app.services.build_service
=========================

Build and test automation. Detects the project's build system from the clone,
runs the appropriate command inside the execution runner (Docker-isolated when
available, otherwise local), captures output, and returns a readable report.

Supported first-class:
  * **Android / Gradle** — ``./gradlew test`` / ``./gradlew assembleDebug``.
  * **Python** — ``pytest``.
Extensible: add a detector + command pair for other ecosystems.

Build failures are summarized; when an agent is available the raw output can be
handed to it for root-cause analysis (``analyze_failure``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable, List, Optional, Tuple

from app.core.logging import get_logger
from app.database import repository as db
from app.database.models import Repository, STATUS_COMPLETED, STATUS_FAILED
from app.execution.docker_runner import CommandResult, run_command
from app.services.repository_service import ensure_local_clone

logger = get_logger("repopilot.build")

Notifier = Callable[[str], Awaitable[None]]


def detect_build_system(clone: Path) -> str:
    if (clone / "gradlew").exists() or (clone / "build.gradle").exists() or (
        clone / "build.gradle.kts"
    ).exists():
        return "gradle"
    if (clone / "pytest.ini").exists() or (clone / "pyproject.toml").exists() or (
        clone / "setup.py"
    ).exists() or (clone / "tests").exists():
        return "python"
    if (clone / "package.json").exists():
        return "node"
    return "unknown"


def _command_for(system: str, action: str, clone: Path) -> Optional[List[str]]:
    """Return the argv for ``action`` ("test" | "build") in ``system``."""
    if system == "gradle":
        gradlew = "./gradlew" if (clone / "gradlew").exists() else "gradle"
        return [gradlew, "test"] if action == "test" else [gradlew, "assembleDebug"]
    if system == "python":
        return ["pytest", "-q"] if action == "test" else ["python", "-m", "compileall", "."]
    if system == "node":
        return ["npm", "test"] if action == "test" else ["npm", "run", "build"]
    return None


def _summarize(result: CommandResult, system: str, action: str) -> str:
    isolation = "Docker-isolated" if result.isolated else "local (no sandbox)"
    header = f"*{system} {action}* — {'✅ passed' if result.ok else '❌ failed'} ({isolation})\n"
    output = result.combined_output
    if len(output) > 3500:
        output = output[-3500:]  # tail is where failures live
    return header + f"```\n{output or '(no output)'}\n```"


async def run(
    repo: Repository, action: str, notify: Notifier, task_id: Optional[int] = None
) -> Tuple[bool, str]:
    """Run build or test for ``repo``; returns (ok, report) and updates the task."""
    await notify("📂 Preparing the repository…")
    clone = await ensure_local_clone(repo)

    system = detect_build_system(clone)
    cmd = _command_for(system, action, clone)
    if cmd is None:
        msg = (
            f"I couldn't detect a supported build system in `{repo.ref}` "
            "(looked for Gradle, Python, Node). "
        )
        if task_id:
            db.update_task(task_id, status=STATUS_FAILED, error=msg)
        await notify("⚠️ " + msg)
        return False, msg

    await notify(f"🏗️ Running `{' '.join(cmd)}` ({system})…")
    result = await run_command(cmd, cwd=clone)
    report = _summarize(result, system, action)

    if task_id:
        db.update_task(
            task_id,
            status=STATUS_COMPLETED if result.ok else STATUS_FAILED,
            result=report,
            error=None if result.ok else "Build/test reported failures.",
        )
    await notify(report)
    return result.ok, report


def make_build_workflow(repo: Repository, action: str, notify: Notifier):
    async def workflow(task_id: int) -> None:
        await run(repo, action, notify, task_id=task_id)

    return workflow
