"""
app.core.config
===============

Central configuration for RepoPilot AI, loaded from environment variables
(usually via a local ``.env`` file). Keeping all configuration in one typed
object means handlers and services never read ``os.environ`` directly.

We deliberately avoid ``pydantic-settings`` (not a required dependency) and
build a plain pydantic model from ``os.environ`` so the project stays light.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Set

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load .env once, as early as possible.
load_dotenv()

# Repository root (…/RepoPilot-ai). Used to anchor the workspace and the DB.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _parse_ids(raw: str) -> Set[int]:
    """Parse a comma/semicolon-separated list of Telegram user IDs."""
    ids: Set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            # Ignore junk rather than crash on startup.
            continue
    return ids


class Settings(BaseModel):
    """Typed application settings sourced from the environment."""

    # --- Telegram -----------------------------------------------------------
    telegram_bot_token: str = ""
    admin_ids: Set[int] = Field(default_factory=set)

    # --- GitHub -------------------------------------------------------------
    # Doubles as the GitHub Models LLM key AND the GitHub API/Git token.
    github_token: str = ""

    # --- LLM (OpenAI-compatible, defaults to free GitHub Models) ------------
    ai_base_url: str = "https://models.inference.ai.azure.com"
    ai_model: str = "gpt-4o-mini"

    # --- Coding agents ------------------------------------------------------
    # Which CLI coding agent to use by default: "claude" or "codex".
    default_agent: str = "claude"
    claude_cli_path: str = "claude"
    codex_cli_path: str = "codex"
    claude_model: str = ""  # optional alias like "sonnet"/"opus"; "" = CLI default

    # --- Execution / safety -------------------------------------------------
    workspace_dir: Path = PROJECT_ROOT / "workspace"
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'repopilot.db'}"
    task_timeout_seconds: int = 1800  # hard cap for a single coding/build task
    use_docker: bool = False  # opt-in; falls back to local if docker missing
    # Branches we must never push to directly.
    protected_branches: List[str] = Field(
        default_factory=lambda: ["main", "master", "production", "prod", "release"]
    )

    # --- Behaviour ----------------------------------------------------------
    # Minimum characters before a plain text message is treated as a crash trace.
    min_trace_len: int = 30

    @property
    def is_admin_configured(self) -> bool:
        return bool(self.admin_ids)

    @property
    def has_github_token(self) -> bool:
        return bool(self.github_token)

    def is_protected_branch(self, branch: str) -> bool:
        return branch.strip().lower() in {b.lower() for b in self.protected_branches}


def load_settings() -> Settings:
    """Build a :class:`Settings` from the current environment."""
    workspace = os.getenv("WORKSPACE_DIR")
    database_url = os.getenv(
        "DATABASE_URL", f"sqlite:///{PROJECT_ROOT / 'repopilot.db'}"
    )
    return Settings(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        admin_ids=_parse_ids(os.getenv("TELEGRAM_ADMIN_IDS", "")),
        github_token=os.getenv("GITHUB_TOKEN", ""),
        ai_base_url=os.getenv("AI_BASE_URL", "https://models.inference.ai.azure.com"),
        ai_model=os.getenv("AI_MODEL", "gpt-4o-mini"),
        default_agent=os.getenv("DEFAULT_AGENT", "claude").strip().lower(),
        claude_cli_path=os.getenv("CLAUDE_CLI_PATH", "claude"),
        codex_cli_path=os.getenv("CODEX_CLI_PATH", "codex"),
        claude_model=os.getenv("CLAUDE_MODEL", ""),
        workspace_dir=Path(workspace) if workspace else PROJECT_ROOT / "workspace",
        database_url=database_url,
        task_timeout_seconds=int(os.getenv("TASK_TIMEOUT_SECONDS", "1800")),
        use_docker=os.getenv("USE_DOCKER", "false").strip().lower()
        in ("1", "true", "yes"),
    )


# A module-level singleton most code can import directly.
settings = load_settings()
