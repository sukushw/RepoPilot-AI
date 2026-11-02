"""
Coding commands: /ask, /explain, /analyze (read-only) and
/bugfix, /refactor, /generate (write + approval). Also /review.
"""

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
from app.services import code_review_service, coding_service
from app.services.task_service import task_service

READ_ONLY_KINDS = {"ask", "explain", "analyze"}
WRITE_KINDS = {"bugfix", "refactor", "generate"}


def _resolve_agent(user_id: int) -> str:
    from app.agents.agent_manager import agent_manager

    return agent_manager.resolve_name(db.get_preferred_agent(user_id))


async def _launch_coding(update, context, kind: str) -> None:
    repo = await require_active_repo(update)
    if not repo:
        return
    instruction = joined_args(context)
    if not instruction:
        await update.message.reply_text(
            f"Usage: `/{kind} <description>`\n"
            f"Example: `/{kind} fix the null pointer in HomeFragment`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    user_id = update.effective_user.id
    agent_name = _resolve_agent(user_id)
    task = db.create_task(
        telegram_user_id=user_id,
        kind=kind,
        description=instruction,
        agent=agent_name,
        repository_id=repo.id,
    )
    notify = make_notifier(update, context)

    if kind in WRITE_KINDS:
        workflow = coding_service.make_write_workflow(
            repo, agent_name, kind, instruction, notify
        )
    else:
        workflow = coding_service.make_read_only_workflow(
            repo, agent_name, kind, instruction, notify
        )

    await update.message.reply_text(
        f"🚀 *Task #{task.id} started*\n"
        f"Repo: `{repo.ref}` · Agent: `{agent_name}` · Kind: `{kind}`\n"
        f"I'll post progress here. Cancel with `/cancel {task.id}`.",
        parse_mode=ParseMode.MARKDOWN,
    )
    task_service.launch(task.id, workflow)


@restricted
async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _launch_coding(update, context, "ask")


@restricted
async def explain(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _launch_coding(update, context, "explain")


@restricted
async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _launch_coding(update, context, "analyze")


@restricted
async def bugfix(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _launch_coding(update, context, "bugfix")


@restricted
async def refactor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _launch_coding(update, context, "refactor")


@restricted
async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _launch_coding(update, context, "generate")


@restricted
async def review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    repo = await require_active_repo(update)
    if not repo:
        return
    target = joined_args(context) or None
    user_id = update.effective_user.id
    agent_name = _resolve_agent(user_id)
    task = db.create_task(
        telegram_user_id=user_id,
        kind="review",
        description=target or "working-tree / latest commit",
        agent=agent_name,
        repository_id=repo.id,
    )
    notify = make_notifier(update, context)
    workflow = code_review_service.make_review_workflow(
        repo, agent_name, target, notify
    )
    await update.message.reply_text(
        f"🔍 *Review task #{task.id} started* on `{repo.ref}`.",
        parse_mode=ParseMode.MARKDOWN,
    )
    task_service.launch(task.id, workflow)
