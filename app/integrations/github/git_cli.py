"""
app.integrations.github.git_cli
===============================

Async wrappers around the local ``git`` command (subprocess). We use the real
git CLI rather than GitPython so the only requirement is a working ``git`` on the
PATH — which is already present on a developer laptop.

Design notes
------------
* All calls are ``async`` via ``asyncio.create_subprocess_exec`` so git never
  blocks the Telegram event loop.
* The authenticated remote URL (token-embedded) is only passed to ``clone`` and
  ``push``; it's never stored in a way that would print the token, and all
  error text is routed through :func:`app.core.security.redact_secrets` by
  callers before display.
* We refuse to push to protected branches at this layer as a backstop, even
  though the service layer also enforces it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Optional, Tuple

from app.core.config import settings
from app.core.security import authed_remote_url, redact_secrets


class GitError(RuntimeError):
    """Raised when a git command exits non-zero (message is redacted)."""


async def _run_git(
    args: List[str], cwd: Optional[Path] = None, timeout: int = 300
) -> Tuple[int, str, str]:
    """Run ``git <args>`` and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise GitError(f"git {args[0]} timed out after {timeout}s")
    return (
        proc.returncode or 0,
        out.decode("utf-8", errors="replace"),
        err.decode("utf-8", errors="replace"),
    )


async def _git_or_raise(
    args: List[str], cwd: Optional[Path] = None, timeout: int = 300
) -> str:
    code, out, err = await _run_git(args, cwd=cwd, timeout=timeout)
    if code != 0:
        raise GitError(redact_secrets(err.strip() or out.strip() or "git failed"))
    return out


async def git_available() -> bool:
    try:
        code, _, _ = await _run_git(["--version"], timeout=15)
        return code == 0
    except Exception:
        return False


async def clone(repo_ref: str, dest: Path, branch: Optional[str] = None) -> Path:
    """Clone ``owner/repo`` into ``dest`` (shallow). Returns the clone path."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = authed_remote_url(repo_ref, settings.github_token)
    args = ["clone", "--depth", "50"]
    if branch:
        args += ["--branch", branch]
    args += [url, str(dest)]
    await _git_or_raise(args, timeout=600)
    # Strip the token out of the stored remote so it never persists on disk.
    clean_url = f"https://github.com/{repo_ref}.git"
    await _run_git(["remote", "set-url", "origin", clean_url], cwd=dest)
    return dest


async def ensure_clone(repo_ref: str, dest: Path, branch: Optional[str] = None) -> Path:
    """Clone if missing, otherwise fetch the latest for the clone at ``dest``."""
    if (dest / ".git").exists():
        await _run_git(["fetch", "--all", "--prune"], cwd=dest, timeout=300)
        return dest
    return await clone(repo_ref, dest, branch)


async def current_branch(repo_dir: Path) -> str:
    out = await _git_or_raise(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir)
    return out.strip()


async def create_branch(repo_dir: Path, branch: str, base: Optional[str] = None) -> str:
    """Create and switch to ``branch`` (from ``base`` if given)."""
    if base:
        await _run_git(["checkout", base], cwd=repo_dir)
    await _git_or_raise(["checkout", "-B", branch], cwd=repo_dir)
    return branch


async def diff(repo_dir: Path, staged: bool = False) -> str:
    """Return the working-tree diff (or staged diff)."""
    args = ["diff"]
    if staged:
        args.append("--cached")
    return await _git_or_raise(args, cwd=repo_dir)


async def has_changes(repo_dir: Path) -> bool:
    code, out, _ = await _run_git(["status", "--porcelain"], cwd=repo_dir)
    return bool(out.strip())


async def add_commit(repo_dir: Path, message: str) -> str:
    """Stage all changes and commit. Returns the short commit hash."""
    await _git_or_raise(["add", "-A"], cwd=repo_dir)
    await _git_or_raise(["commit", "-m", message], cwd=repo_dir)
    out = await _git_or_raise(["rev-parse", "--short", "HEAD"], cwd=repo_dir)
    return out.strip()


async def push(repo_ref: str, repo_dir: Path, branch: str) -> None:
    """Push ``branch`` to origin, refusing protected branches as a backstop."""
    if settings.is_protected_branch(branch):
        raise GitError(f"Refusing to push to protected branch '{branch}'.")
    # Push with a one-off token-embedded URL so the stored remote stays clean.
    url = authed_remote_url(repo_ref, settings.github_token)
    await _git_or_raise(
        ["push", "--set-upstream", url, f"{branch}:{branch}"],
        cwd=repo_dir,
        timeout=300,
    )


async def list_branches(repo_dir: Path) -> List[str]:
    out = await _git_or_raise(["branch", "--format=%(refname:short)"], cwd=repo_dir)
    return [b.strip() for b in out.splitlines() if b.strip()]
