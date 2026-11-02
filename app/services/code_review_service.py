"""
app.services.code_review_service
===============================

AI code review over a repository's changes. Builds the review *scope* (a git diff)
and hands it to a coding agent, which returns findings grouped by severity
(Critical / High / Medium / Low / Informational) with file/line references.

Scope selection:
  * If the working tree has uncommitted changes, review those.
  * Else, review the most recent commit (``HEAD~1..HEAD``).
  * A caller-supplied ``target`` (branch/range) overrides both.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Optional

from app.agents.agent_manager import agent_manager
from app.core.logging import get_logger
from app.core.security import redact_secrets
from app.database import repository as db
from app.database.models import Repository, STATUS_COMPLETED, STATUS_FAILED
from app.integrations.github import git_cli
from app.services.repository_service import ensure_local_clone

logger = get_logger("repopilot.review")

Notifier = Callable[[str], Awaitable[None]]


async def _build_scope(clone, target: Optional[str]) -> str:
    """Return a git diff string describing what to review."""
    if target:
        out = await git_cli._git_or_raise(["diff", target], cwd=clone)
        return out
    if await git_cli.has_changes(clone):
        return await git_cli.diff(clone)
    # Fall back to the last commit.
    try:
        return await git_cli._git_or_raise(["diff", "HEAD~1..HEAD"], cwd=clone)
    except Exception:
        return ""


def make_review_workflow(
    repo: Repository, agent_name: str, target: Optional[str], notify: Notifier
):
    async def workflow(task_id: int) -> None:
        agent = agent_manager.get(agent_name)
        status = await agent.get_status()
        if not status.available:
            db.update_task(task_id, status=STATUS_FAILED, error=status.detail)
            await notify(f"❌ Agent `{agent_name}` is unavailable:\n{status.detail}")
            return

        await notify("📂 Preparing the repository…")
        clone = await ensure_local_clone(repo)

        scope = await _build_scope(clone, target)
        if not scope.strip():
            db.update_task(
                task_id,
                status=STATUS_COMPLETED,
                result="No changes found to review.",
            )
            await notify(
                "ℹ️ I found no diff to review (clean working tree and no recent "
                "commit). Make some changes or pass a branch/range to `/review`."
            )
            return

        await notify(f"🔍 {agent_name} is reviewing the changes…")
        result = await agent.review_code(clone, scope)
        if not result.success:
            db.update_task(task_id, status=STATUS_FAILED, error=result.error)
            await notify(f"❌ Review failed:\n{redact_secrets(result.error or '')}")
            return

        db.update_task(task_id, status=STATUS_COMPLETED, result=result.output)
        await notify("🧾 *Code Review*\n\n" + (result.output or "(No findings.)"))

    return workflow
