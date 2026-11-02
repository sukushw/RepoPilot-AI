"""
app.bot.handlers.common
======================

Shared utilities for Telegram handlers: the access-control decorator, a notifier
factory for background tasks, and small helpers to resolve the active repository.

Handlers stay thin — they parse input, call a service, and format the reply. All
business logic lives in ``app.services``.
"""

from __future__ import annotations

import functools
from typing import Awaitable, Callable, Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.core.config import settings
from app.core.logging import get_logger
from app.database import repository as db
from app.database.models import Repository
from app.integrations.telegram.formatting import send_long

logger = get_logger("repopilot.bot")


def restricted(handler: Callable) -> Callable:
    """Block anyone not on the admin allowlist.

    If the allowlist is empty (first-time setup), reply with the user's own ID so
    the operator can add it — but do no real work.
    """

    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        user_id = user.id if user else None

        if not settings.is_admin_configured:
            logger.warning("No TELEGRAM_ADMIN_IDS configured; denying user %s", user_id)
            if update.message:
                await update.message.reply_text(
                    "🔒 This bot isn't configured with an admin yet.\n\n"
                    f"Your Telegram ID is: `{user_id}`\n\n"
                    "Add it to `TELEGRAM_ADMIN_IDS` in `.env` and restart.",
                    parse_mode=ParseMode.MARKDOWN,
                )
            return

        if user_id not in settings.admin_ids:
            logger.warning("Unauthorized access attempt from user %s", user_id)
            if update.message:
                await update.message.reply_text(
                    "⛔ Sorry, you're not authorized to use this bot."
                )
            return

        return await handler(update, context)

    return wrapper


def make_notifier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return an async ``notify(text)`` that posts progress to the user's chat."""
    chat_id = update.effective_chat.id

    async def notify(text: str) -> None:
        await send_long(context.bot, chat_id, text)

    return notify


async def require_active_repo(update: Update) -> Optional[Repository]:
    """Return the user's active repo or send a helpful message and return None."""
    user_id = update.effective_user.id
    repo = db.get_active_repo(user_id)
    if not repo:
        await update.message.reply_text(
            "⚠️ No active repository. Connect one first:\n"
            "`/connect owner/repo`",
            parse_mode=ParseMode.MARKDOWN,
        )
    return repo


def joined_args(context: ContextTypes.DEFAULT_TYPE) -> str:
    return " ".join(context.args or []).strip()


async def not_in_this_build(update: Update, feature: str) -> None:
    """Honest placeholder for commands beyond the current build."""
    await update.message.reply_text(
        f"🚧 `{feature}` isn't available in this build yet.\n"
        "It's on the roadmap — see /help for what works today.",
        parse_mode=ParseMode.MARKDOWN,
    )
