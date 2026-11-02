"""
app.execution.workspace
=======================

Manages the on-disk workspace where repositories are cloned and tasks operate.

Layout::

    workspace/
      <telegram_user_id>/
        <owner>__<repo>/        # the local clone / working tree

Keeping each user's clones under their own directory (and each repo in its own
folder) isolates concurrent work and makes cleanup simple. Every path handed out
is guaranteed to live inside the configured ``workspace_dir``.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.core.security import is_within_directory, split_repo_ref


def workspace_root() -> Path:
    root = settings.workspace_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def repo_clone_path(telegram_user_id: int, repo_ref: str) -> Path:
    """Return the local clone path for a user's repo (not created here)."""
    owner, name = split_repo_ref(repo_ref)
    safe = f"{owner}__{name}".replace("/", "_")
    path = workspace_root() / str(telegram_user_id) / safe
    # Containment backstop: the computed path must stay under the workspace.
    if not is_within_directory(workspace_root(), path):
        raise ValueError("Computed clone path escapes the workspace.")
    return path
