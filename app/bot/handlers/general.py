"""General commands: /start, /help, /about, /status, /settings."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.agents.agent_manager import agent_manager
from app.bot.handlers.common import restricted
from app.core.config import settings
from app.database import repository as db

TAGLINE = "Your AI Software Engineer, accessible through Telegram."


@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 *Welcome to RepoPilot AI*\n"
        f"_{TAGLINE}_\n\n"
        "I connect to your GitHub repos and delegate real engineering tasks to AI "
        "coding agents — analysis, bug fixes, reviews, tests, and pull requests.\n\n"
        "*Quick start:*\n"
        "1️⃣ `/connect owner/repo` — connect a repository\n"
        "2️⃣ `/ask <question>` — ask about the code, or just send a message\n"
        "3️⃣ `/bugfix <description>` — propose a fix (you approve before any PR)\n\n"
        "📱 Android crash? Send the stack trace or use `/crash`.\n\n"
        "Type /help for the full command list.",
        parse_mode=ParseMode.MARKDOWN,
    )


@restricted
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*RepoPilot AI — Commands*\n\n"
        "*General*\n"
        "`/start` `/help` `/about` `/status` `/settings`\n\n"
        "*Repository*\n"
        "`/connect owner/repo` — connect & activate a repo\n"
        "`/repos` — list your repos\n"
        "`/repo` — show the active repo\n"
        "`/switch <ref|id>` — change active repo\n"
        "`/disconnect <ref|id>` — remove a repo\n\n"
        "*Coding* (uses the active repo)\n"
        "`/ask <q>` `/explain <target>` `/analyze <q>`\n"
        "`/review [branch/range]` — AI code review\n"
        "`/bugfix <desc>` `/refactor <desc>` `/generate <desc>`\n\n"
        "*Android*\n"
        "`/crash` — analyze a stack trace (or just paste one)\n"
        "`/android` `/gradle` `/build`\n\n"
        "*Testing*\n"
        "`/test` — run tests · `/testreport` — last report\n\n"
        "*Git*\n"
        "`/diff` `/branch` `/commit` `/pr`\n\n"
        "*Tasks*\n"
        "`/tasks` `/task <id>` `/cancel <id>` `/approve` `/reject`\n\n"
        "*Agents*\n"
        "`/agents` — availability · `/agent <name>` — pick default\n\n"
        "💬 You can also just *type naturally*, e.g. "
        "_\"analyze my repo for performance issues\"_.",
        parse_mode=ParseMode.MARKDOWN,
    )


@restricted
async def about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "*About RepoPilot AI*\n\n"
        f"_{TAGLINE}_\n\n"
        "A local-first AI developer assistant. It runs entirely on your laptop "
        "(Telegram long-polling, SQLite, local clones) and talks to GitHub and AI "
        "coding agents over the internet.\n\n"
        "• Coding agents: Claude Code & Codex (pluggable)\n"
        "• Crash analysis: reads your real source on GitHub\n"
        "• Safety: human approval before any commit, push, or PR; protected "
        "branches are never touched.\n\n"
        "Built on top of the original CrashFix AI, now a specialized Android "
        "debugging module.",
        parse_mode=ParseMode.MARKDOWN,
    )


@restricted
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    repo = db.get_active_repo(user_id)
    repos = db.list_repositories(user_id)
    tasks = db.list_tasks(user_id, limit=50)
    running = sum(1 for t in tasks if t.status in ("running", "pending"))
    waiting = sum(1 for t in tasks if t.status == "waiting_approval")

    active = f"`{repo.ref}` (branch `{repo.default_branch}`)" if repo else "_none_"
    pref_agent = db.get_preferred_agent(user_id) or settings.default_agent
    gh = "configured ✅" if settings.has_github_token else "missing ⚠️"

    await update.message.reply_text(
        "*RepoPilot status*\n\n"
        f"Active repo: {active}\n"
        f"Connected repos: {len(repos)}\n"
        f"Default agent: `{pref_agent}`\n"
        f"GitHub token: {gh}\n"
        f"Tasks — running/pending: {running}, awaiting approval: {waiting}\n"
        f"Docker isolation: {'on' if settings.use_docker else 'off (local)'}",
        parse_mode=ParseMode.MARKDOWN,
    )


@restricted
async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    pref_agent = db.get_preferred_agent(user_id) or settings.default_agent
    await update.message.reply_text(
        "*Settings*\n\n"
        f"• Default agent: `{pref_agent}` — change with `/agent <name>`\n"
        f"• Available agents: {', '.join(agent_manager.names)}\n"
        f"• Task timeout: {settings.task_timeout_seconds}s\n"
        f"• Protected branches: {', '.join(settings.protected_branches)}\n\n"
        "Most settings are configured in `.env` (tokens, model, Docker). "
        "Per-user preferences (active repo, default agent) persist in SQLite.",
        parse_mode=ParseMode.MARKDOWN,
    )
