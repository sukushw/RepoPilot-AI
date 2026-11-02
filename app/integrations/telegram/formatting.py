"""
app.integrations.telegram.formatting
====================================

Telegram message helpers: split long text into <4096-char chunks and send it
safely, falling back to plain text when Markdown parsing fails on model output.
"""

from __future__ import annotations

from typing import List

from telegram import Update
from telegram.constants import ParseMode

# Telegram caps a single message at 4096 characters; stay comfortably under it.
TELEGRAM_MAX_LEN = 4000


def split_message(text: str, limit: int = TELEGRAM_MAX_LEN) -> List[str]:
    """Split ``text`` into Telegram-sized chunks, preferring line breaks."""
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(line), limit):
                chunks.append(line[i : i + limit])
            continue
        if len(current) + len(line) > limit:
            chunks.append(current)
            current = line
        else:
            current += line
    if current:
        chunks.append(current)
    return chunks


async def reply_long(update: Update, text: str) -> None:
    """Reply to a message, splitting and falling back to plain text."""
    for chunk in split_message(text):
        try:
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.message.reply_text(chunk)


async def send_long(bot, chat_id: int, text: str) -> None:
    """Send a (possibly long) message by chat id (used from background tasks)."""
    for chunk in split_message(text):
        try:
            await bot.send_message(chat_id, chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await bot.send_message(chat_id, chunk)
