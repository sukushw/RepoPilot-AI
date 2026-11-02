"""Agent management: /agents, /agent."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.agents.agent_manager import agent_manager
from app.bot.handlers.common import joined_args, restricted
from app.core.config import settings
from app.database import repository as db


@restricted
async def agents(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔎 Checking agent availability…")
    statuses = await agent_manager.statuses()
    user_id = update.effective_user.id
    current = db.get_preferred_agent(user_id) or settings.default_agent
    lines = ["*Coding agents:*\n"]
    for s in statuses:
        mark = "✅" if s.available else "⚠️"
        star = " ⭐(default)" if s.name == current else ""
        lines.append(f"{mark} `{s.name}`{star} — {s.detail}")
    lines.append("\nSet your default with `/agent <name>`.")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@restricted
async def agent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = joined_args(context).strip().lower()
    if not name:
        await update.message.reply_text(
            f"Usage: `/agent <name>`\nAvailable: {', '.join(agent_manager.names)}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    if name not in agent_manager.names:
        await update.message.reply_text(
            f"Unknown agent `{name}`. Available: {', '.join(agent_manager.names)}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    db.set_preferred_agent(update.effective_user.id, name)
    await update.message.reply_text(
        f"✅ Default agent set to `{name}`.", parse_mode=ParseMode.MARKDOWN
    )
