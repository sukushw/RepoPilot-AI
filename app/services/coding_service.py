"""
app.services.coding_service
==========================

Orchestrates the coding workflows that run a CLI coding agent against a local
clone. Two shapes:

  * **Read-only** (``ask``, ``explain``, ``review``, ``analyze``) — run the agent,
    return its answer, mark the task complete. No file changes.

  * **Write** (``bugfix``, ``refactor``, ``generate``, ``tests``) — clone, create
    a feature branch, run the agent so it edits the working tree, compute the git
    diff, then STOP at ``waiting_approval``. Nothing is committed, pushed, or
    turned into a PR until the user runs ``/approve``. ``/reject`` discards it.

This enforces the spec's hard rule: never silently modify a repo, and never touch
a protected branch.

Each workflow is a coroutine ``(task_id) -> None`` suitable for
``task_service.launch``. A ``notifier`` (async ``str -> None``) streams progress
back to the user's chat.
"""

from __future__ import annotations

import time
from typing import Awaitable, Callable, Optional

from app.agents.agent_manager import agent_manager
from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import redact_secrets
from app.database import repository as db
from app.database.models import (
    Repository,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_WAITING_APPROVAL,
)
from app.integrations.github import git_cli
from app.integrations.github.api import GitHubAPI, GitHubAPIError
from app.services.repository_service import ensure_local_clone

logger = get_logger("repopilot.coding")

Notifier = Callable[[str], Awaitable[None]]

# Map of task kind -> CodingAgent method name for write workflows.
_WRITE_METHODS = {
    "bugfix": "fix_bug",
    "refactor": "refactor",
    "generate": "generate_code",
    "tests": "generate_tests",
}
_READ_METHODS = {
    "ask": "analyze",
    "analyze": "analyze",
    "explain": "explain_code",
    "review": "review_code",
}


def _branch_name(kind: str, task_id: int) -> str:
    return f"repopilot/{kind}-{task_id}-{int(time.time())}"


def make_read_only_workflow(
    repo: Repository, agent_name: str, kind: str, instruction: str, notify: Notifier
):
    async def workflow(task_id: int) -> None:
        agent = agent_manager.get(agent_name)
        status = await agent.get_status()
        if not status.available:
            db.update_task(task_id, status=STATUS_FAILED, error=status.detail)
            await notify(f"❌ Agent `{agent_name}` is unavailable:\n{status.detail}")
            return

        await notify("📂 Preparing a local copy of the repository…")
        clone = await ensure_local_clone(repo)

        await notify(f"🤖 {agent_name} is working on it…")
        method = getattr(agent, _READ_METHODS.get(kind, "analyze"))
        result = await method(clone, instruction)

        if not result.success:
            db.update_task(task_id, status=STATUS_FAILED, error=result.error)
            await notify(f"❌ {agent_name} failed:\n{redact_secrets(result.error or '')}")
            return

        db.update_task(task_id, status=STATUS_COMPLETED, result=result.output)
        await notify(result.output or "(No output.)")

    return workflow


def make_write_workflow(
    repo: Repository, agent_name: str, kind: str, instruction: str, notify: Notifier
):
    async def workflow(task_id: int) -> None:
        agent = agent_manager.get(agent_name)
        status = await agent.get_status()
        if not status.available:
            db.update_task(task_id, status=STATUS_FAILED, error=status.detail)
            await notify(f"❌ Agent `{agent_name}` is unavailable:\n{status.detail}")
            return

        await notify("📂 Cloning / refreshing the repository…")
        clone = await ensure_local_clone(repo)

        branch = _branch_name(kind, task_id)
        await notify(f"🌿 Creating work branch `{branch}`…")
        await git_cli.create_branch(clone, branch, base=repo.default_branch)
        db.update_task(task_id, branch=branch)

        await notify(f"🤖 {agent_name} is applying changes…")
        method = getattr(agent, _WRITE_METHODS[kind])
        result = await method(clone, instruction)

        if not result.success:
            db.update_task(task_id, status=STATUS_FAILED, error=result.error)
            await notify(f"❌ {agent_name} failed:\n{redact_secrets(result.error or '')}")
            return

        if not await git_cli.has_changes(clone):
            db.update_task(
                task_id,
                status=STATUS_COMPLETED,
                result=result.output
                + "\n\n(No file changes were produced, so there's nothing to commit.)",
            )
            await notify(
                f"ℹ️ {agent_name} finished but made no file changes.\n\n{result.output}"
            )
            return

        diff = await git_cli.diff(clone)
        db.update_task(
            task_id,
            status=STATUS_WAITING_APPROVAL,
            pending_action="commit_push_pr",
            result=result.output + "\n\n----- DIFF -----\n" + diff,
        )
        preview = diff if len(diff) < 6000 else diff[:6000] + "\n… (diff truncated)"
        await notify(
            f"🤖 *{agent_name}* finished. Summary:\n\n{result.output}\n\n"
            f"*Proposed git diff:*\n```diff\n{preview}\n```\n\n"
            f"Review it, then `/approve` to commit, push to `{branch}`, and open a "
            f"pull request — or `/reject` to discard. (Task #{task_id})"
        )

    return workflow


async def approve_change(task_id: int, notify: Notifier) -> None:
    """Commit, push the feature branch, and open a PR for an approved task."""
    task = db.get_task(task_id)
    if not task or task.status != STATUS_WAITING_APPROVAL:
        await notify("That task isn't waiting for approval.")
        return
    repo = db.get_repository(task.repository_id) if task.repository_id else None
    if not repo or not task.branch:
        db.update_task(task_id, status=STATUS_FAILED, error="Missing repo/branch.")
        await notify("❌ Can't approve: repository or branch is missing.")
        return

    from app.execution.workspace import repo_clone_path

    clone = repo_clone_path(repo.telegram_user_id, repo.ref)
    try:
        await notify("💾 Committing changes…")
        summary = (task.description or "RepoPilot change")[:72]
        commit_msg = f"{task.kind}: {summary}\n\nApplied by RepoPilot AI (task #{task_id})."
        await git_cli.add_commit(clone, commit_msg)

        await notify(f"⬆️ Pushing `{task.branch}`…")
        await git_cli.push(repo.ref, clone, task.branch)

        await notify("🔀 Opening a pull request…")
        api = GitHubAPI(settings.github_token)
        pr_url = await api.create_pull_request(
            repo_ref=repo.ref,
            head_branch=task.branch,
            base_branch=repo.default_branch,
            title=f"[RepoPilot] {task.kind}: {summary}",
            body=(
                f"Automated change by RepoPilot AI (task #{task_id}).\n\n"
                f"**Request:** {task.description}\n\n"
                "Please review before merging."
            ),
        )
        db.update_task(task_id, status=STATUS_COMPLETED, pr_url=pr_url)
        await notify(f"✅ Done! Pull request opened:\n{pr_url}")
    except (GitHubAPIError, Exception) as exc:  # noqa: BLE001
        db.update_task(task_id, status=STATUS_FAILED, error=redact_secrets(str(exc)))
        await notify(f"❌ Approval step failed: {redact_secrets(str(exc))}")


async def reject_change(task_id: int, notify: Notifier) -> None:
    task = db.get_task(task_id)
    if not task or task.status != STATUS_WAITING_APPROVAL:
        await notify("That task isn't waiting for approval.")
        return
    db.update_task(task_id, status="cancelled", error="Rejected by user.")
    await notify(
        f"🗑️ Discarded the proposed changes for task #{task_id}. "
        "Nothing was committed or pushed."
    )
