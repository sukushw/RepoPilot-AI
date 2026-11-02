"""Task management: /tasks, /task, /cancel, /approve, /reject."""

from __future__ import annotations

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.bot.handlers.common import joined_args, make_notifier, restricted
from app.database import repository as db
from app.integrations.telegram.formatting import reply_long
from app.services import coding_service
from app.services.task_service import task_service

_STATUS_EMOJI = {
    "pending": "⏳",
    "running": "⚙️",
    "waiting_approval": "✋",
    "completed": "✅",
    "failed": "❌",
    "cancelled": "🚫",
}


@restricted
async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    rows = db.list_tasks(user_id, limit=15)
    if not rows:
        await update.message.reply_text("No tasks yet.")
        return
    lines = ["*Recent tasks:*\n"]
    for t in rows:
        emoji = _STATUS_EMOJI.get(t.status, "•")
        desc = (t.description or "")[:48]
        lines.append(f"{emoji} #{t.id} `{t.kind}` — {t.status}\n   _{desc}_")
    lines.append("\nDetails: `/task <id>` · Cancel: `/cancel <id>`")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@restricted
async def task_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    arg = joined_args(context)
    if not arg.isdigit():
        await update.message.reply_text("Usage: `/task <id>`", parse_mode=ParseMode.MARKDOWN)
        return
    t = db.get_task(int(arg))
    if not t or t.telegram_user_id != update.effective_user.id:
        await update.message.reply_text("Task not found.")
        return
    emoji = _STATUS_EMOJI.get(t.status, "•")
    body = (
        f"{emoji} *Task #{t.id}*\n"
        f"Kind: `{t.kind}` · Agent: `{t.agent}` · Status: `{t.status}`\n"
        f"Created: {t.created_at}\n"
        f"Description: {t.description}\n"
    )
    if t.branch:
        body += f"Branch: `{t.branch}`\n"
    if t.pr_url:
        body += f"PR: {t.pr_url}\n"
    if t.error:
        body += f"\n❌ Error: {t.error}\n"
    if t.result:
        body += f"\n----- Result -----\n{t.result}"
    await reply_long(update, body)


@restricted
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    arg = joined_args(context)
    if not arg.isdigit():
        await update.message.reply_text("Usage: `/cancel <id>`", parse_mode=ParseMode.MARKDOWN)
        return
    task_id = int(arg)
    t = db.get_task(task_id)
    if not t or t.telegram_user_id != update.effective_user.id:
        await update.message.reply_text("Task not found.")
        return
    if task_service.cancel(task_id):
        await update.message.reply_text(f"🚫 Cancelling task #{task_id}…")
    else:
        await update.message.reply_text(
            f"Task #{task_id} isn't running (status: {t.status})."
        )


@restricted
async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    arg = joined_args(context)
    if arg.isdigit():
        t = db.get_task(int(arg))
    else:
        t = db.latest_task_awaiting_approval(user_id)
    if not t or t.telegram_user_id != user_id or t.status != "waiting_approval":
        await update.message.reply_text(
            "Nothing is waiting for approval. Start a change with `/bugfix …` first.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await update.message.reply_text(f"✅ Approving task #{t.id} — committing & opening a PR…")
    notify = make_notifier(update, context)
    asyncio.create_task(coding_service.approve_change(t.id, notify))


@restricted
async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    arg = joined_args(context)
    if arg.isdigit():
        t = db.get_task(int(arg))
    else:
        t = db.latest_task_awaiting_approval(user_id)
    if not t or t.telegram_user_id != user_id or t.status != "waiting_approval":
        await update.message.reply_text("Nothing is waiting for approval.")
        return
    notify = make_notifier(update, context)
    asyncio.create_task(coding_service.reject_change(t.id, notify))
