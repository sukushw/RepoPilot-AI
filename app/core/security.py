"""
app.core.security
=================

Security helpers that are deliberately independent of Telegram or the database
so they can be unit-tested in isolation.

Covers:
  * Repository URL / ``owner/repo`` validation (reject anything that isn't a
    plausible GitHub repository reference).
  * Path containment checks (never let a task touch files outside its workspace).
  * Secret redaction for logs and Telegram responses.
  * A small helper to mask tokens embedded in git remote URLs.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple

# owner/repo where each part is a conservative GitHub-name character set.
_OWNER_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")

# Patterns that look like credentials; redacted before anything is shown/logged.
_SECRET_PATTERNS = [
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"gho_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    # https://<token>@github.com or https://user:<token>@host
    re.compile(r"(https?://)[^/\s:@]+:[^/\s@]+@"),
]


class RepoValidationError(ValueError):
    """Raised when a repository reference fails validation."""


def normalize_repo_ref(raw: str) -> str:
    """Reduce a GitHub URL or ``owner/repo`` string to canonical ``owner/repo``.

    Accepts forms like::

        https://github.com/octocat/Hello-World.git
        git@github.com:octocat/Hello-World.git
        http://github.com/octocat/Hello-World/
        octocat/Hello-World

    Raises :class:`RepoValidationError` if the result isn't a valid reference.
    """
    if not raw or not raw.strip():
        raise RepoValidationError("Empty repository reference.")

    ref = raw.strip()
    # git@github.com:owner/repo.git  ->  owner/repo.git
    ref = re.sub(r"^git@github\.com:", "", ref)
    # https://github.com/owner/repo  ->  owner/repo
    ref = re.sub(r"^https?://(www\.)?github\.com/", "", ref)
    ref = re.sub(r"\.git$", "", ref)
    ref = ref.strip("/")

    if not _OWNER_REPO_RE.match(ref):
        raise RepoValidationError(
            "That doesn't look like a valid GitHub repository. "
            "Use `owner/repo` or a full https://github.com/owner/repo URL."
        )
    # Reject path traversal / sneaky segments.
    if ".." in ref:
        raise RepoValidationError("Invalid repository reference.")
    return ref


def split_repo_ref(ref: str) -> Tuple[str, str]:
    """Split a validated ``owner/repo`` into ``(owner, repo)``."""
    owner, _, repo = ref.partition("/")
    return owner, repo


def is_within_directory(base: Path, target: Path) -> bool:
    """Return True if ``target`` resolves to a location inside ``base``.

    Used to guarantee task file operations can't escape their workspace via
    symlinks or ``..`` segments.
    """
    try:
        base_r = base.resolve()
        target_r = target.resolve()
    except (OSError, RuntimeError):
        return False
    return base_r == target_r or base_r in target_r.parents


def redact_secrets(text: Optional[str]) -> str:
    """Remove anything that looks like a token/credential from ``text``.

    Always run user-visible errors and log lines through this so a token in a
    git URL or stack trace never leaks into Telegram or the logs.
    """
    if not text:
        return ""
    cleaned = text
    for pattern in _SECRET_PATTERNS:
        if pattern.pattern.startswith("(https"):
            cleaned = pattern.sub(r"\1***@", cleaned)
        else:
            cleaned = pattern.sub("***", cleaned)
    return cleaned


def authed_remote_url(repo_ref: str, token: str) -> str:
    """Build an authenticated HTTPS remote URL for ``git`` operations.

    The token is embedded so ``git clone``/``push`` works non-interactively.
    NEVER log or display the result directly — use :func:`redact_secrets`.
    """
    if token:
        return f"https://x-access-token:{token}@github.com/{repo_ref}.git"
    return f"https://github.com/{repo_ref}.git"
