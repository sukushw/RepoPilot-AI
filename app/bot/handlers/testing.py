"""Testing commands: /test, /testreport."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.bot.handlers.common import make_notifier, require_active_repo, restricted
from app.database import repository as db
from app.integrations.telegram.formatting import reply_long
from app.services import build_service
from app.services.task_service import task_service


@restricted
async def test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    repo = await require_active_repo(update)
    if not repo:
        return
    user_id = update.effective_user.id
    task = db.create_task(
        telegram_user_id=user_id,
        kind="test",
        description="run tests",
        agent="-",
        repository_id=repo.id,
    )
    notify = make_notifier(update, context)
    await update.message.reply_text(
        f"🧪 *Test task #{task.id}* started on `{repo.ref}`.",
        parse_mode=ParseMode.MARKDOWN,
    )
    workflow = build_service.make_build_workflow(repo, "test", notify)
    task_service.launch(task.id, workflow)


@restricted
async def testreport(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    tasks = db.list_tasks(user_id, limit=50)
    last = next((t for t in tasks if t.kind in ("test", "build", "gradle")), None)
    if not last or not last.result:
        await update.message.reply_text(
            "No test/build report yet. Run `/test` first.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await reply_long(
        update,
        f"🧪 *Last {last.kind} report* (task #{last.id}, {last.status}):\n\n{last.result}",
    )
