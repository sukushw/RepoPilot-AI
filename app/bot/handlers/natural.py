"""
Natural-language + document handlers.

A plain text message is classified by :mod:`app.services.nlu_service` and routed
to the same services the slash commands use. A `.txt`/`.log` upload is treated as
a crash trace. Short, chatty messages get gentle guidance instead of firing an
expensive task.
"""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.agents.agent_manager import agent_manager
from app.bot.handlers.android import process_crash
from app.bot.handlers.common import make_notifier, require_active_repo, restricted
from app.core.config import settings
from app.database import repository as db
from app.services import (
    build_service,
    code_review_service,
    coding_service,
)
from app.services.nlu_service import classify
from app.services.task_service import task_service

WRITE_KINDS = {"bugfix", "refactor", "generate", "tests"}
READ_KINDS = {"ask", "explain", "analyze"}


def _agent_for(user_id: int) -> str:
    return agent_manager.resolve_name(db.get_preferred_agent(user_id))


async def _route(update, context, repo, intent_name: str, instruction: str) -> None:
    user_id = update.effective_user.id
    agent_name = _agent_for(user_id)
    notify = make_notifier(update, context)

    if intent_name == "crash":
        await process_crash(update, repo, instruction)
        return

    if intent_name in ("build",):
        task = db.create_task(user_id, "build", instruction, "-", repo.id)
        await update.message.reply_text(f"🏗️ Build task #{task.id} started.")
        task_service.launch(task.id, build_service.make_build_workflow(repo, "build", notify))
        return

    if intent_name == "test":
        task = db.create_task(user_id, "test", instruction, "-", repo.id)
        await update.message.reply_text(f"🧪 Test task #{task.id} started.")
        task_service.launch(task.id, build_service.make_build_workflow(repo, "test", notify))
        return

    if intent_name == "review":
        task = db.create_task(user_id, "review", instruction, agent_name, repo.id)
        await update.message.reply_text(f"🔍 Review task #{task.id} started.")
        task_service.launch(
            task.id, code_review_service.make_review_workflow(repo, agent_name, None, notify)
        )
        return

    kind = intent_name if intent_name in (READ_KINDS | WRITE_KINDS) else "ask"
    task = db.create_task(user_id, kind, instruction, agent_name, repo.id)
    await update.message.reply_text(
        f"🚀 Task #{task.id} (`{kind}`, agent `{agent_name}`) started on `{repo.ref}`.",
        parse_mode=ParseMode.MARKDOWN,
    )
    if kind in WRITE_KINDS:
        workflow = coding_service.make_write_workflow(repo, agent_name, kind, instruction, notify)
    else:
        workflow = coding_service.make_read_only_workflow(repo, agent_name, kind, instruction, notify)
    task_service.launch(task.id, workflow)


@restricted
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()

    intent = classify(text)

    # A crash trace can be handled even with no obvious verb; otherwise short
    # chatter gets guidance instead of launching work.
    if intent.name != "crash" and len(text) < settings.min_trace_len:
        await update.message.reply_text(
            "Tell me what to do with your repo — e.g. _\"review my latest changes\"_ "
            "or _\"fix the crash in HomeFragment\"_. Type /help for commands.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    repo = await require_active_repo(update)
    if not repo:
        return
    await _route(update, context, repo, intent.name, intent.instruction)


@restricted
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document = update.message.document
    name = (document.file_name or "").lower()
    if not (name.endswith(".txt") or name.endswith(".log")):
        await update.message.reply_text(
            "Please upload a `.txt` or `.log` file (e.g. a crash trace).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    repo = await require_active_repo(update)
    if not repo:
        return
    await update.message.reply_text("📥 Downloading…")
    try:
        tg_file = await document.get_file()
        data = await tg_file.download_as_bytearray()
        raw_log = bytes(data).decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        await update.message.reply_text(f"❌ Couldn't read the file: {exc}")
        return
    await process_crash(update, repo, raw_log)
