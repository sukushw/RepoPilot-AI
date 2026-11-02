"""Repository commands: /connect, /repos, /repo, /switch, /disconnect."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.bot.handlers.common import joined_args, restricted
from app.core.security import RepoValidationError
from app.integrations.github.api import GitHubAPIError
from app.services import repository_service as repos


@restricted
async def connect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    ref = joined_args(context)
    if not ref:
        await update.message.reply_text(
            "Usage: `/connect owner/repo`\n"
            "Example: `/connect octocat/Hello-World`\n"
            "A full https://github.com/owner/repo URL works too.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text("🔗 Connecting…")
    try:
        _, message = await repos.connect_repository(user_id, ref)
    except RepoValidationError as exc:
        await update.message.reply_text(f"❌ {exc}", parse_mode=ParseMode.MARKDOWN)
        return
    except GitHubAPIError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


@restricted
async def list_repos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    repo_list = repos.list_user_repositories(user_id)
    if not repo_list:
        await update.message.reply_text(
            "You haven't connected any repositories yet. Use `/connect owner/repo`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    active = repos.get_active_repository(user_id)
    active_id = active.id if active else None
    lines = ["*Your repositories:*\n"]
    for r in repo_list:
        marker = "⭐" if r.id == active_id else "•"
        vis = "🔒" if r.is_private else "🌐"
        lines.append(f"{marker} `{r.ref}` {vis} (id `{r.id}`, branch `{r.default_branch}`)")
    lines.append("\nSwitch with `/switch <ref|id>`.")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@restricted
async def show_repo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    repo = repos.get_active_repository(user_id)
    if not repo:
        await update.message.reply_text(
            "No active repository. Connect one with `/connect owner/repo`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    vis = "private 🔒" if repo.is_private else "public 🌐"
    cloned = "yes" if repo.local_path else "not yet (clones on first task)"
    await update.message.reply_text(
        f"*Active repository*\n\n"
        f"`{repo.ref}` ({vis})\n"
        f"Default branch: `{repo.default_branch}`\n"
        f"Local clone: {cloned}\n"
        f"id: `{repo.id}`",
        parse_mode=ParseMode.MARKDOWN,
    )


@restricted
async def switch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    arg = joined_args(context)
    if not arg:
        await update.message.reply_text(
            "Usage: `/switch <ref|id>` — see `/repos` for options.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    repo = repos.switch_repository(user_id, arg)
    if not repo:
        await update.message.reply_text(
            "I couldn't find that repository among your connected ones. "
            "Check `/repos`.",
        )
        return
    await update.message.reply_text(
        f"✅ Active repository is now `{repo.ref}`.", parse_mode=ParseMode.MARKDOWN
    )


@restricted
async def disconnect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    arg = joined_args(context)
    if not arg:
        await update.message.reply_text(
            "Usage: `/disconnect <ref|id>`.", parse_mode=ParseMode.MARKDOWN
        )
        return
    ok = repos.disconnect_repository(user_id, arg)
    if ok:
        await update.message.reply_text("🗑️ Repository disconnected.")
    else:
        await update.message.reply_text("I couldn't find that repository.")
