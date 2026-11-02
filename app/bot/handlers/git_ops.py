"""Git commands: /diff, /branch, /commit, /pr."""

from __future__ import annotations

from pathlib import Path

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.bot.handlers.common import joined_args, require_active_repo, restricted
from app.core.security import redact_secrets
from app.database import repository as db
from app.execution.workspace import repo_clone_path
from app.integrations.github import git_cli
from app.integrations.telegram.formatting import reply_long


def _clone_path(repo) -> Path:
    return repo_clone_path(repo.telegram_user_id, repo.ref)


@restricted
async def diff(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    repo = await require_active_repo(update)
    if not repo:
        return
    clone = _clone_path(repo)
    if not (clone / ".git").exists():
        await update.message.reply_text(
            "No local clone yet. Run a coding task (e.g. `/bugfix …`) first.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    try:
        out = await git_cli.diff(clone)
    except Exception as exc:  # noqa: BLE001
        await update.message.reply_text(f"❌ {redact_secrets(str(exc))}")
        return
    if not out.strip():
        await update.message.reply_text("Working tree is clean — no diff.")
        return
    await reply_long(update, f"*git diff* — `{repo.ref}`\n```diff\n{out[:7000]}\n```")


@restricted
async def branch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    repo = await require_active_repo(update)
    if not repo:
        return
    clone = _clone_path(repo)
    if not (clone / ".git").exists():
        await update.message.reply_text(
            "No local clone yet. Run a coding task first.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    name = joined_args(context)
    try:
        if name:
            await git_cli.create_branch(clone, name, base=repo.default_branch)
            await update.message.reply_text(
                f"🌿 Created and switched to `{name}`.", parse_mode=ParseMode.MARKDOWN
            )
            return
        branches = await git_cli.list_branches(clone)
        current = await git_cli.current_branch(clone)
        lines = [("➡️ " if b == current else "• ") + f"`{b}`" for b in branches]
        await update.message.reply_text(
            "*Branches*\n" + "\n".join(lines), parse_mode=ParseMode.MARKDOWN
        )
    except Exception as exc:  # noqa: BLE001
        await update.message.reply_text(f"❌ {redact_secrets(str(exc))}")


@restricted
async def commit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Commits are gated through the approval workflow, never done ad-hoc."""
    user_id = update.effective_user.id
    pending = db.latest_task_awaiting_approval(user_id)
    if pending:
        await update.message.reply_text(
            f"✋ Task #{pending.id} is waiting for your approval. "
            f"Review the diff, then `/approve` to commit + push + open a PR, "
            f"or `/reject` to discard.",
        )
    else:
        await update.message.reply_text(
            "Commits happen only through the approval workflow for safety.\n"
            "Run a change (e.g. `/bugfix …`), review the proposed diff, then "
            "`/approve`.",
            parse_mode=ParseMode.MARKDOWN,
        )


@restricted
async def pr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    tasks = db.list_tasks(user_id, limit=50)
    with_pr = [t for t in tasks if t.pr_url]
    if with_pr:
        lines = ["*Recent pull requests:*\n"]
        for t in with_pr[:10]:
            lines.append(f"• Task #{t.id} ({t.kind}): {t.pr_url}")
        await update.message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
        return
    pending = db.latest_task_awaiting_approval(user_id)
    if pending:
        await update.message.reply_text(
            f"No PRs yet. Task #{pending.id} is ready — `/approve` to open one."
        )
    else:
        await update.message.reply_text(
            "No pull requests yet. Make a change with `/bugfix`/`/generate`, "
            "then `/approve` the proposed diff to open a PR.",
            parse_mode=ParseMode.MARKDOWN,
        )
