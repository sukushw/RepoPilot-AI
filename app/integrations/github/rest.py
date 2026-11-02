"""
github_tools.py
===============

A thin, async wrapper around the GitHub REST API that lets the agent inspect
the *actual* source code of a repository without cloning it.

We use two endpoints:
  * Git Trees API (recursive) — to locate a file by name anywhere in the repo.
  * Contents API              — to fetch a single file's (base64) contents.

Authentication uses ``GITHUB_TOKEN`` (a Personal Access Token). This is
independent of which LLM provider is used — the agent always needs GitHub
access to read source code.
"""

from __future__ import annotations

import base64
from typing import Dict, List, Optional

import httpx

GITHUB_API = "https://api.github.com"


class GitHubInvestigator:
    """Reads source files from a GitHub repository over the REST API.

    Parameters
    ----------
    token:
        A GitHub Personal Access Token with read access to the repo.
    repo:
        The repository in ``owner/name`` form, e.g. ``"octocat/Hello-World"``.
    default_branch:
        The branch (or ref) to read from, e.g. ``"main"``.
    """

    def __init__(self, token: str, repo: str, default_branch: str = "main"):
        self.token = token
        self.repo = repo.strip().strip("/")
        self.default_branch = default_branch
        self._headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

        # Cache of the recursive tree so repeated lookups don't re-hit the API.
        self._tree_cache: Optional[List[Dict]] = None

    # -- Internal helpers ---------------------------------------------------

    async def _get(self, client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
        """Perform a GET with the standard headers and raise on HTTP errors."""
        resp = await client.get(url, headers=self._headers, timeout=30.0, **kwargs)
        resp.raise_for_status()
        return resp

    async def _load_tree(self) -> List[Dict]:
        """Fetch (and cache) the recursive git tree for the default branch.

        Returns a list of tree entries, each a dict with at least ``path`` and
        ``type`` ("blob" for files, "tree" for directories).
        """
        if self._tree_cache is not None:
            return self._tree_cache

        async with httpx.AsyncClient() as client:
            # The recursive tree API accepts a branch name as the ref.
            url = (
                f"{GITHUB_API}/repos/{self.repo}/git/trees/"
                f"{self.default_branch}?recursive=1"
            )
            resp = await self._get(client, url)
            data = resp.json()

        self._tree_cache = data.get("tree", [])
        return self._tree_cache

    # -- Public API ---------------------------------------------------------

    async def find_file_path(self, filename: str) -> Optional[str]:
        """Find the full repo path of ``filename`` using the recursive Tree API.

        Stack traces only give the bare file name (e.g. ``HomeFragment.kt``),
        not its path. We search the tree for a blob whose path ends with that
        name. If several match, we prefer the shortest path (usually the least
        nested, most likely the real one).
        """
        if not filename:
            return None

        tree = await self._load_tree()
        target = filename.strip()

        matches = [
            entry["path"]
            for entry in tree
            if entry.get("type") == "blob"
            and (entry["path"] == target or entry["path"].endswith("/" + target))
        ]
        if not matches:
            return None

        matches.sort(key=len)
        return matches[0]

    async def get_source_snippet(
        self, file_path: str, target_line: int, window: int = 25
    ) -> str:
        """Return a numbered snippet of ``file_path`` around ``target_line``.

        The crash line is marked with a ``->`` arrow so the LLM can anchor its
        reasoning on it. ``window`` controls how many lines of context appear
        above and below the target line.
        """
        source = await self._fetch_file_text(file_path)
        if source is None:
            return f"(Could not read {file_path} from the repository.)"

        lines = source.splitlines()
        total = len(lines)

        # Clamp the window to the file's bounds. target_line is 1-indexed.
        start = max(1, target_line - window)
        end = min(total, target_line + window)

        rendered: List[str] = []
        gutter = len(str(end))  # width for right-aligned line numbers
        for n in range(start, end + 1):
            marker = "->" if n == target_line else "  "
            rendered.append(f"{marker} {str(n).rjust(gutter)} | {lines[n - 1]}")

        return "\n".join(rendered)

    async def get_manifest_or_layout(self, filename: str) -> str:
        """Fetch a supplementary file (layout XML, AndroidManifest.xml, etc.).

        Returns the full file contents (no line window), or an explanatory
        message if the file can't be found/read. Used by the agent's
        ``read_additional_file`` tool.
        """
        path = await self.find_file_path(filename)
        if path is None:
            # The caller may have passed a full path already; try it directly.
            path = filename

        source = await self._fetch_file_text(path)
        if source is None:
            return f"(File '{filename}' was not found in {self.repo}.)"

        # Add simple line numbers so the model can cite locations.
        numbered = [
            f"{str(i).rjust(4)} | {line}"
            for i, line in enumerate(source.splitlines(), start=1)
        ]
        return "\n".join(numbered)

    # -- Low-level content fetch -------------------------------------------

    async def _fetch_file_text(self, file_path: str) -> Optional[str]:
        """Fetch and base64-decode a single file via the Contents API.

        Returns the decoded UTF-8 text, or ``None`` if the file is missing or
        cannot be decoded as text.
        """
        if not file_path:
            return None

        async with httpx.AsyncClient() as client:
            url = f"{GITHUB_API}/repos/{self.repo}/contents/{file_path}"
            params = {"ref": self.default_branch}
            try:
                resp = await self._get(client, url, params=params)
            except httpx.HTTPStatusError:
                return None

        data = resp.json()

        # The Contents API returns a list for directories — not a file.
        if isinstance(data, list):
            return None

        content = data.get("content")
        encoding = data.get("encoding")
        if content is None or encoding != "base64":
            return None

        try:
            raw = base64.b64decode(content)
            return raw.decode("utf-8", errors="replace")
        except (ValueError, TypeError):
            return None
