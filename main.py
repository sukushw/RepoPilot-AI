"""
main.py
=======

The Telegram front-end for CrashFix AI.

Flow:
  1. The developer runs  /repo <owner>/<repo> [branch]  to connect a repository.
  2. They send a crash trace — either as a plain text message or as a .txt/.log
     file upload.
  3. The bot parses the crash, locates the crashing file on GitHub, fetches the
     source around the crash line, and asks the CrashFixAgent to diagnose it.
  4. The resulting Markdown (root cause + fix diff) is sent back, split across
     multiple messages if it exceeds Telegram's length limit.

Run with:  python main.py
"""

from __future__ import annotations

import functools
import logging
import os
import re
from typing import Callable, Dict, Optional, Set

from dotenv import load_dotenv
from openai import AsyncOpenAI
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agent import CrashFixAgent
from github_tools import GitHubInvestigator
from parser import parse_android_crash

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("crashfix")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")


def _parse_admin_ids(raw: str) -> Set[int]:
    """Parse the comma-separated TELEGRAM_ADMIN_IDS env var into a set of ints.

    Blank/invalid entries are ignored so a stray comma or space can't crash
    startup.
    """
    ids: Set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            logger.warning("Ignoring invalid TELEGRAM_ADMIN_IDS entry: %r", part)
    return ids


# The set of Telegram user IDs allowed to use the bot. Empty = not configured.
ADMIN_IDS: Set[int] = _parse_admin_ids(os.getenv("TELEGRAM_ADMIN_IDS", ""))
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://models.inference.ai.azure.com")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")

# Telegram caps a single message at 4096 characters; stay comfortably under it.
TELEGRAM_MAX_LEN = 4000

# Minimum characters before we treat a plain text message as a crash trace
# (so that casual chatter isn't mistaken for a stack trace).
MIN_TRACE_LEN = 30

# In-memory per-user repo configuration: user_id -> {"repo", "branch"}.
# (For a production system you'd persist this; in-memory is fine for an MVP.)
USER_REPOS: Dict[int, Dict[str, str]] = {}


# Build a single shared OpenAI-compatible client and agent.
# GitHub Models uses GITHUB_TOKEN as the LLM API key (same token that reads
# the repository source code).
llm_client = AsyncOpenAI(base_url=AI_BASE_URL, api_key=GITHUB_TOKEN)
agent = CrashFixAgent(openai_client=llm_client, model=AI_MODEL)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_message(text: str, limit: int = TELEGRAM_MAX_LEN) -> list[str]:
    """Split a long message into Telegram-sized chunks, preferring line breaks."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        # A single line longer than the limit must be hard-split.
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


async def _send_long(update: Update, text: str) -> None:
    """Send a (possibly long) message, splitting and falling back to plain text."""
    for chunk in _split_message(text):
        try:
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            # Markdown parsing can fail on model output; fall back to plain text.
            await update.message.reply_text(chunk)


def restricted(handler: Callable) -> Callable:
    """Decorator that blocks anyone not on the admin allowlist.

    Behavior:
      * If ADMIN_IDS is configured and the user is listed → run the handler.
      * If the user is NOT listed → deny with a short message and log it.
      * If ADMIN_IDS is EMPTY (not configured yet) → don't run the handler;
        instead reply with the user's own numeric ID so the operator can add
        it to TELEGRAM_ADMIN_IDS. This keeps an unconfigured bot safe (it does
        no work) while making first-time setup easy.
    """

    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        user_id = user.id if user else None

        if not ADMIN_IDS:
            logger.warning(
                "Bot has no TELEGRAM_ADMIN_IDS configured; denying user %s", user_id
            )
            if update.message:
                await update.message.reply_text(
                    "🔒 This bot isn't configured with an admin yet.\n\n"
                    f"Your Telegram ID is: `{user_id}`\n\n"
                    "The operator should add it to `TELEGRAM_ADMIN_IDS` in `.env` "
                    "and restart the bot.",
                    parse_mode=ParseMode.MARKDOWN,
                )
            return

        if user_id not in ADMIN_IDS:
            logger.warning("Unauthorized access attempt from user %s", user_id)
            if update.message:
                await update.message.reply_text(
                    "⛔ Sorry, you're not authorized to use this bot."
                )
            return

        return await handler(update, context)

    return wrapper


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greet the user and explain how to use the bot."""
    await update.message.reply_text(
        "👋 *Welcome to CrashFix AI*\n\n"
        "I debug Android crashes by reading your app's real source code on "
        "GitHub and proposing a fix.\n\n"
        "*How to use me:*\n"
        "1️⃣ Connect your repo:\n"
        "`/repo owner/repo [branch]`\n"
        "   e.g. `/repo octocat/MyApp main`\n\n"
        "2️⃣ Send me the crash — either paste the stack trace as a message, or "
        "upload a `.txt` / `.log` file.\n\n"
        "I'll find the crashing file, inspect the code, and reply with the root "
        "cause and a code-fix diff.\n\n"
        "Type /help anytime.",
        parse_mode=ParseMode.MARKDOWN,
    )


@restricted
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show available commands."""
    await update.message.reply_text(
        "*CrashFix AI — commands*\n\n"
        "`/repo owner/repo [branch]` — connect a GitHub repository "
        "(branch defaults to `main`).\n"
        "`/start` — show the welcome message.\n"
        "`/help` — show this help.\n\n"
        "Then just send or upload your Android crash trace.",
        parse_mode=ParseMode.MARKDOWN,
    )


@restricted
async def set_repo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle `/repo <owner>/<repo> [branch]`."""
    user_id = update.effective_user.id
    args = context.args or []

    if not args:
        await update.message.reply_text(
            "Usage: `/repo owner/repo [branch]`\n"
            "Example: `/repo octocat/Hello-World main`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    repo = args[0].strip()
    # Accept a full URL too, trimming https://github.com/ and a trailing .git.
    repo = re.sub(r"^https?://github\.com/", "", repo)
    repo = re.sub(r"\.git$", "", repo).strip("/")

    if repo.count("/") != 1 or not all(repo.split("/")):
        await update.message.reply_text(
            "That doesn't look like a valid repo. Use `owner/repo`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    branch = args[1].strip() if len(args) > 1 else "main"
    USER_REPOS[user_id] = {"repo": repo, "branch": branch}

    await update.message.reply_text(
        f"✅ Connected to *{repo}* (branch `{branch}`).\n\n"
        "Now send me the Android crash trace (as text or a `.txt`/`.log` file).",
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# Crash-handling core
# ---------------------------------------------------------------------------

async def _process_crash(update: Update, raw_log: str) -> None:
    """Parse, investigate, and analyze a crash trace, replying with the result."""
    user_id = update.effective_user.id
    config = USER_REPOS.get(user_id)

    if not config:
        await update.message.reply_text(
            "⚠️ No repository connected yet.\n"
            "Run `/repo owner/repo [branch]` first.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not GITHUB_TOKEN:
        await update.message.reply_text(
            "⚠️ GITHUB_TOKEN is not configured on the server, so I can't read "
            "source code. Ask the operator to set it."
        )
        return

    # 1) Parse the crash.
    status = await update.message.reply_text("🔍 Parsing crash...")
    parsed = parse_android_crash(raw_log)

    if parsed.is_empty or parsed.target_frame is None:
        await status.edit_text(
            "I couldn't find an application stack frame in that log. "
            "Make sure you pasted a full Android stack trace including the "
            "`at com.yourapp...` lines."
        )
        return

    tf = parsed.target_frame
    investigator = GitHubInvestigator(
        token=GITHUB_TOKEN,
        repo=config["repo"],
        default_branch=config["branch"],
    )

    # 2) Locate the crashing file on GitHub.
    await status.edit_text("📂 Fetching source code from GitHub...")
    try:
        file_path = await investigator.find_file_path(tf.file_name or "")
    except Exception as exc:  # network / API / auth errors
        logger.exception("GitHub tree lookup failed")
        await status.edit_text(
            f"❌ Couldn't read the repository tree: {exc}\n"
            "Check the repo name, branch, and that GITHUB_TOKEN has access."
        )
        return

    if not file_path:
        await status.edit_text(
            f"❌ I couldn't find `{tf.file_name}` in "
            f"`{config['repo']}` (branch `{config['branch']}`).\n"
            "Double-check the branch, or that the file exists in this repo.",
        )
        return

    # 3) Fetch the source snippet around the crash line.
    target_line = tf.line_number or 1
    try:
        snippet = await investigator.get_source_snippet(file_path, target_line)
    except Exception as exc:
        logger.exception("Fetching source snippet failed")
        await status.edit_text(f"❌ Couldn't fetch the source file: {exc}")
        return

    # 4) Ask the agent to diagnose and fix.
    await status.edit_text("🤖 Analyzing with CrashFix AI...")
    try:
        answer = await agent.analyze(
            parsed=parsed,
            source_snippet=snippet,
            investigator=investigator,
            file_path=file_path,
        )
    except Exception as exc:
        logger.exception("LLM analysis failed")
        await status.edit_text(
            f"❌ Analysis failed: {exc}\n"
            "Check the AI provider configuration (AI_BASE_URL / API key / model)."
        )
        return

    # 5) Deliver the result.
    header = (
        f"🛠️ *CrashFix AI diagnosis*\n"
        f"Repo: `{config['repo']}` · File: `{file_path}:{target_line}`\n"
        f"{'─' * 20}\n"
    )
    try:
        await status.delete()
    except Exception:
        pass
    await _send_long(update, header + answer)


@restricted
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Treat a sufficiently long text message as a crash trace."""
    text = update.message.text or ""
    if len(text.strip()) < MIN_TRACE_LEN:
        await update.message.reply_text(
            "Send me a full Android crash trace, or connect a repo with "
            "`/repo owner/repo [branch]`. Type /help for details.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await _process_crash(update, text)


@restricted
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Accept an uploaded .txt / .log file and treat it as a crash trace."""
    document = update.message.document
    name = (document.file_name or "").lower()

    if not (name.endswith(".txt") or name.endswith(".log")):
        await update.message.reply_text(
            "Please upload a `.txt` or `.log` file containing the crash trace.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text("📥 Downloading crash log...")
    try:
        tg_file = await document.get_file()
        data = await tg_file.download_as_bytearray()
        raw_log = bytes(data).decode("utf-8", errors="replace")
    except Exception as exc:
        logger.exception("Failed to download/read document")
        await update.message.reply_text(f"❌ Couldn't read the file: {exc}")
        return

    await _process_crash(update, raw_log)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_application() -> Application:
    """Construct the Telegram application with all handlers registered."""
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and fill it in."
        )

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("repo", set_repo))

    # Documents first, then free text (text handler excludes commands).
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )

    return app


def main() -> None:
    app = build_application()
    logger.info("CrashFix AI bot starting (provider: %s, model: %s)", AI_BASE_URL, AI_MODEL)
    if ADMIN_IDS:
        logger.info("Admin allowlist active: %d user(s) authorized", len(ADMIN_IDS))
    else:
        logger.warning(
            "TELEGRAM_ADMIN_IDS is empty — the bot will refuse all users and "
            "only reply with their IDs. Set TELEGRAM_ADMIN_IDS in .env."
        )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
