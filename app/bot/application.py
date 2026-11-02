"""
app.bot.application
==================

Builds the python-telegram-bot ``Application`` and registers every handler. All
command handlers delegate to services — there is no business logic here.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.bot.handlers import (
    agents as agents_h,
    android as android_h,
    coding as coding_h,
    general as general_h,
    git_ops as git_h,
    natural as natural_h,
    repository as repo_h,
    tasks as tasks_h,
    testing as testing_h,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.database.db import init_db

logger = get_logger("repopilot.app")


def build_application() -> Application:
    if not settings.telegram_bot_token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and fill it in."
        )

    init_db()
    app = ApplicationBuilder().token(settings.telegram_bot_token).build()

    # --- General ---
    app.add_handler(CommandHandler("start", general_h.start))
    app.add_handler(CommandHandler("help", general_h.help_command))
    app.add_handler(CommandHandler("about", general_h.about))
    app.add_handler(CommandHandler("status", general_h.status))
    app.add_handler(CommandHandler("settings", general_h.settings_command))

    # --- Repository ---
    app.add_handler(CommandHandler("connect", repo_h.connect))
    app.add_handler(CommandHandler("repos", repo_h.list_repos))
    app.add_handler(CommandHandler("repo", repo_h.show_repo))
    app.add_handler(CommandHandler("switch", repo_h.switch))
    app.add_handler(CommandHandler("disconnect", repo_h.disconnect))

    # --- Coding ---
    app.add_handler(CommandHandler("ask", coding_h.ask))
    app.add_handler(CommandHandler("explain", coding_h.explain))
    app.add_handler(CommandHandler("analyze", coding_h.analyze))
    app.add_handler(CommandHandler("review", coding_h.review))
    app.add_handler(CommandHandler("bugfix", coding_h.bugfix))
    app.add_handler(CommandHandler("refactor", coding_h.refactor))
    app.add_handler(CommandHandler("generate", coding_h.generate))

    # --- Android ---
    app.add_handler(CommandHandler("crash", android_h.crash))
    app.add_handler(CommandHandler("android", android_h.android))
    app.add_handler(CommandHandler("gradle", android_h.gradle))
    app.add_handler(CommandHandler("build", android_h.build))

    # --- Testing ---
    app.add_handler(CommandHandler("test", testing_h.test))
    app.add_handler(CommandHandler("testreport", testing_h.testreport))

    # --- Git ---
    app.add_handler(CommandHandler("diff", git_h.diff))
    app.add_handler(CommandHandler("branch", git_h.branch))
    app.add_handler(CommandHandler("commit", git_h.commit))
    app.add_handler(CommandHandler("pr", git_h.pr))

    # --- Tasks ---
    app.add_handler(CommandHandler("tasks", tasks_h.tasks))
    app.add_handler(CommandHandler("task", tasks_h.task_detail))
    app.add_handler(CommandHandler("cancel", tasks_h.cancel))
    app.add_handler(CommandHandler("approve", tasks_h.approve))
    app.add_handler(CommandHandler("reject", tasks_h.reject))

    # --- Agents ---
    app.add_handler(CommandHandler("agents", agents_h.agents))
    app.add_handler(CommandHandler("agent", agents_h.agent))

    # --- Documents then free text (text handler excludes commands) ---
    app.add_handler(MessageHandler(filters.Document.ALL, natural_h.handle_document))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, natural_h.handle_text)
    )

    return app


def run() -> None:
    app = build_application()
    logger.info(
        "RepoPilot AI starting (LLM: %s / %s, default agent: %s)",
        settings.ai_base_url, settings.ai_model, settings.default_agent,
    )
    if settings.is_admin_configured:
        logger.info("Admin allowlist active: %d user(s)", len(settings.admin_ids))
    else:
        logger.warning(
            "TELEGRAM_ADMIN_IDS is empty — the bot will refuse all users and only "
            "reply with their IDs. Set TELEGRAM_ADMIN_IDS in .env."
        )
    app.run_polling(allowed_updates=Update.ALL_TYPES)
