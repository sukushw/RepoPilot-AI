"""
app.services.repository_service
==============================

Business logic for connecting and managing repositories. Handlers call these
functions; they coordinate validation, GitHub metadata lookup, the local clone,
and persistence.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    RepoValidationError,
    normalize_repo_ref,
    split_repo_ref,
)
from app.database import repository as db
from app.database.models import Repository
from app.execution.workspace import repo_clone_path
from app.integrations.github import git_cli
from app.integrations.github.api import GitHubAPI, GitHubAPIError

logger = get_logger("repopilot.repos")


async def connect_repository(
    telegram_user_id: int, raw_ref: str
) -> Tuple[Repository, str]:
    """Validate, look up, and persist a repository; make it active.

    Returns ``(repository, human_message)``. Raises :class:`RepoValidationError`
    or :class:`GitHubAPIError` on failure so the handler can show a friendly
    message. The clone is performed lazily (on first coding task) to keep
    ``/connect`` fast — but default branch / visibility are fetched now.
    """
    ref = normalize_repo_ref(raw_ref)
    owner, name = split_repo_ref(ref)

    default_branch = "main"
    is_private = False
    note = ""
    if settings.has_github_token:
        api = GitHubAPI(settings.github_token)
        info = await api.get_repo_info(ref)  # raises GitHubAPIError if not found
        default_branch = info["default_branch"]
        is_private = info["private"]
    else:
        note = (
            "\n\n⚠️ No GITHUB_TOKEN set — I couldn't verify the repo or read "
            "private repositories. Set it in `.env` for full functionality."
        )

    repo = db.add_repository(
        telegram_user_id=telegram_user_id,
        ref=ref,
        owner=owner,
        name=name,
        default_branch=default_branch,
        is_private=is_private,
    )
    db.set_active_repo(telegram_user_id, repo.id)

    visibility = "private" if is_private else "public"
    message = (
        f"✅ Connected *{ref}* ({visibility}, default branch `{default_branch}`).\n"
        f"It's now your active repository." + note
    )
    return repo, message


def list_user_repositories(telegram_user_id: int) -> List[Repository]:
    return db.list_repositories(telegram_user_id)


def get_active_repository(telegram_user_id: int) -> Optional[Repository]:
    return db.get_active_repo(telegram_user_id)


def switch_repository(
    telegram_user_id: int, ref_or_id: str
) -> Optional[Repository]:
    """Switch the active repo by ``owner/repo`` ref or numeric id."""
    repo: Optional[Repository] = None
    if ref_or_id.isdigit():
        candidate = db.get_repository(int(ref_or_id))
        if candidate and candidate.telegram_user_id == telegram_user_id:
            repo = candidate
    else:
        try:
            ref = normalize_repo_ref(ref_or_id)
            repo = db.find_repository(telegram_user_id, ref)
        except RepoValidationError:
            repo = None
    if repo:
        db.set_active_repo(telegram_user_id, repo.id)
    return repo


def disconnect_repository(telegram_user_id: int, ref_or_id: str) -> bool:
    repo: Optional[Repository] = None
    if ref_or_id.isdigit():
        repo = db.get_repository(int(ref_or_id))
    else:
        try:
            ref = normalize_repo_ref(ref_or_id)
            repo = db.find_repository(telegram_user_id, ref)
        except RepoValidationError:
            return False
    if not repo:
        return False
    return db.delete_repository(telegram_user_id, repo.id)


async def ensure_local_clone(repo: Repository, branch: Optional[str] = None) -> Path:
    """Clone (or refresh) the repo locally and record its path. Returns the path."""
    dest = repo_clone_path(repo.telegram_user_id, repo.ref)
    path = await git_cli.ensure_clone(repo.ref, dest, branch or repo.default_branch)
    db.set_repository_local_path(repo.id, str(path))
    return path
