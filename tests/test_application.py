from __future__ import annotations

import asyncio

import pytest

import app.bot.application as application
from app.core.config import settings


@pytest.fixture
def _event_loop():
    # python-telegram-bot's ApplicationBuilder constructs an asyncio.Queue at
    # build() time, which needs a current event loop on Python 3.9. In
    # production run_polling() provides one; here we set one for the test.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


def test_build_application_registers_all_commands(monkeypatch, _event_loop):
    # Provide a syntactically-valid dummy token; build() doesn't hit the network.
    monkeypatch.setattr(settings, "telegram_bot_token", "123456:dummy", raising=True)
    app = application.build_application()

    registered = set()
    for group in app.handlers.values():
        for h in group:
            cmds = getattr(h, "commands", None)
            if cmds:
                registered.update(cmds)

    expected = {
        "start", "help", "about", "status", "settings",
        "connect", "repos", "repo", "switch", "disconnect",
        "ask", "explain", "analyze", "review", "bugfix", "refactor", "generate",
        "crash", "android", "gradle", "build",
        "test", "testreport",
        "diff", "branch", "commit", "pr",
        "tasks", "task", "cancel", "approve", "reject",
        "agents", "agent",
    }
    missing = expected - registered
    assert not missing, f"Unregistered commands: {missing}"


def test_build_application_requires_token(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "", raising=True)
    try:
        application.build_application()
    except RuntimeError as exc:
        assert "TELEGRAM_BOT_TOKEN" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError for missing token")
