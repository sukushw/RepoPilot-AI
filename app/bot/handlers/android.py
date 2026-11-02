"""Android commands: /crash, /android, /gradle, /build."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.bot.handlers.common import (
    joined_args,
    make_notifier,
    require_active_repo,
    restricted,
)
from app.database import repository as db
from app.integrations.telegram.formatting import reply_long
from app.services import build_service, crash_analysis_service
from app.services.task_service import task_service


async def process_crash(update: Update, repo, raw_log: str) -> None:
    """Shared entry point for crash analysis (from /crash or a pasted trace)."""
    status = await update.message.reply_text("🔍 Parsing crash…")
    result = await crash_analysis_service.analyze_crash(repo, raw_log)

    if not result.ok:
        await status.edit_text(
            f"{result.summary}\n\n❌ {result.error}" if result.summary else f"❌ {result.error}"
        )
        return

    header = (
        f"🛠️ *CrashFix diagnosis*\n"
        f"Repo: `{repo.ref}` · File: `{result.file_path}:{result.line}`\n"
        f"{'─' * 20}\n"
    )
    try:
        await status.delete()
    except Exception:
        pass
    await reply_long(update, header + result.report)


@restricted
async def crash(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    repo = await require_active_repo(update)
    if not repo:
        return
    raw = joined_args(context)
    # Allow replying to a message that contains the trace.
    if not raw and update.message.reply_to_message:
        raw = update.message.reply_to_message.text or ""
    if not raw:
        await update.message.reply_text(
            "Send the Android stack trace: `/crash <trace>`, reply to a message "
            "containing it, or just paste the trace as a normal message.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await process_crash(update, repo, raw)


@restricted
async def android(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    repo = await require_active_repo(update)
    if not repo:
        return
    question = joined_args(context)
    if not question:
        await update.message.reply_text(
            "*Android diagnostics*\n\n"
            "• Paste a crash trace (or `/crash`) for root-cause analysis.\n"
            "• `/android <question>` — Android-specific code question "
            "(lifecycle, coroutines, ANR, memory, Gradle).\n"
            "• `/gradle` — build via Gradle · `/build` — build the app.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    # Route an Android question through the read-only coding path with focus.
    from app.bot.handlers.coding import _launch_coding

    context.args = [
        "(Android-specific) " + question
    ]
    await _launch_coding(update, context, "analyze")


async def _run_build(update, context, action: str, label: str) -> None:
    repo = await require_active_repo(update)
    if not repo:
        return
    user_id = update.effective_user.id
    task = db.create_task(
        telegram_user_id=user_id,
        kind=label,
        description=f"{label} ({action})",
        agent="-",
        repository_id=repo.id,
    )
    notify = make_notifier(update, context)
    await update.message.reply_text(
        f"🏗️ *{label} task #{task.id}* started on `{repo.ref}`.",
        parse_mode=ParseMode.MARKDOWN,
    )
    workflow = build_service.make_build_workflow(repo, action, notify)
    task_service.launch(task.id, workflow)


@restricted
async def gradle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_build(update, context, "build", "gradle")


@restricted
async def build(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_build(update, context, "build", "build")
