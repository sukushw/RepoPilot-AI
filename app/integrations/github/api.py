"""
app.integrations.github.api
===========================

Higher-level GitHub REST calls that complement the read-only
:class:`GitHubInvestigator` in ``rest.py``:

  * Fetch repository metadata (default branch, visibility, description).
  * Create a pull request.

Uses ``httpx`` with the same ``GITHUB_TOKEN``. Kept separate from the crash
investigator so the read-only analysis path has no accidental write surface.
"""

from __future__ import annotations

from typing import Optional, Tuple

import httpx

GITHUB_API = "https://api.github.com"


class GitHubAPIError(RuntimeError):
    """Raised when a GitHub API call fails (with a redactable message)."""


class GitHubAPI:
    def __init__(self, token: str):
        self.token = token
        self._headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    async def get_repo_info(self, repo_ref: str) -> dict:
        """Return repository metadata: default_branch, private, description…"""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GITHUB_API}/repos/{repo_ref}",
                headers=self._headers,
                timeout=30.0,
            )
        if resp.status_code == 404:
            raise GitHubAPIError(
                f"Repository '{repo_ref}' not found (or your token can't see it)."
            )
        if resp.status_code == 401:
            raise GitHubAPIError("GitHub authentication failed. Check GITHUB_TOKEN.")
        resp.raise_for_status()
        data = resp.json()
        return {
            "default_branch": data.get("default_branch", "main"),
            "private": bool(data.get("private", False)),
            "description": data.get("description") or "",
            "full_name": data.get("full_name", repo_ref),
            "html_url": data.get("html_url", f"https://github.com/{repo_ref}"),
            "stars": data.get("stargazers_count", 0),
            "language": data.get("language") or "unknown",
        }

    async def create_pull_request(
        self,
        repo_ref: str,
        head_branch: str,
        base_branch: str,
        title: str,
        body: str = "",
    ) -> str:
        """Open a PR from ``head_branch`` into ``base_branch``; return its URL."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{GITHUB_API}/repos/{repo_ref}/pulls",
                headers=self._headers,
                json={
                    "title": title,
                    "head": head_branch,
                    "base": base_branch,
                    "body": body,
                },
                timeout=30.0,
            )
        if resp.status_code == 422:
            # Often "a PR already exists" or "no commits between branches".
            detail = ""
            try:
                errors = resp.json().get("errors", [])
                if errors:
                    detail = "; ".join(
                        e.get("message", "") for e in errors if e.get("message")
                    )
                detail = detail or resp.json().get("message", "")
            except Exception:
                detail = resp.text[:200]
            raise GitHubAPIError(f"Could not create pull request: {detail}")
        if resp.status_code == 401:
            raise GitHubAPIError(
                "GitHub authentication failed creating the PR. The token needs "
                "`repo` (write) scope."
            )
        if resp.status_code == 403:
            raise GitHubAPIError(
                "GitHub refused the PR (403). The token likely lacks write access "
                "to this repository."
            )
        resp.raise_for_status()
        return resp.json().get("html_url", "")

    async def check_auth(self) -> Tuple[bool, Optional[str]]:
        """Return (ok, login) for the authenticated user, or (False, None)."""
        if not self.token:
            return False, None
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{GITHUB_API}/user", headers=self._headers, timeout=20.0
                )
            if resp.status_code == 200:
                return True, resp.json().get("login")
        except Exception:
            pass
        return False, None
