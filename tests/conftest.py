"""
Pytest configuration.

Point the database and workspace at a temp location *before* any ``app`` module
imports (which build the engine from ``settings`` at import time). This keeps
tests hermetic and off the network — no real token, repo, or CLI is needed.
"""

from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="repopilot_test_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP}/test.db")
os.environ.setdefault("WORKSPACE_DIR", f"{_TMP}/workspace")
os.environ.setdefault("TELEGRAM_ADMIN_IDS", "111")
os.environ.setdefault("GITHUB_TOKEN", "")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "")

import pytest  # noqa: E402

from app.database.db import init_db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _db():
    init_db()
    yield
