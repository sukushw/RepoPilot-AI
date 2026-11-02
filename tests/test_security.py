from __future__ import annotations

from pathlib import Path

import pytest

from app.core.security import (
    RepoValidationError,
    authed_remote_url,
    is_within_directory,
    normalize_repo_ref,
    redact_secrets,
    split_repo_ref,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("octocat/Hello-World", "octocat/Hello-World"),
        ("https://github.com/octocat/Hello-World", "octocat/Hello-World"),
        ("https://github.com/octocat/Hello-World.git", "octocat/Hello-World"),
        ("http://github.com/octocat/Hello-World/", "octocat/Hello-World"),
        ("git@github.com:octocat/Hello-World.git", "octocat/Hello-World"),
        ("  octocat/Hello-World  ", "octocat/Hello-World"),
    ],
)
def test_normalize_repo_ref_ok(raw, expected):
    assert normalize_repo_ref(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "not-a-repo", "owner/", "/repo", "owner/repo/extra", "../../etc/passwd"],
)
def test_normalize_repo_ref_rejects(raw):
    with pytest.raises(RepoValidationError):
        normalize_repo_ref(raw)


def test_split_repo_ref():
    assert split_repo_ref("octocat/Hello-World") == ("octocat", "Hello-World")


def test_redact_secrets():
    assert "ghp_" not in redact_secrets("token ghp_" + "a" * 36)
    assert "***" in redact_secrets("sk-" + "b" * 40)
    url = "https://x-access-token:ghp_secretsecretsecret12345@github.com/o/r.git"
    red = redact_secrets(url)
    assert "ghp_secret" not in red and "***@" in red


def test_authed_remote_url_contains_token():
    url = authed_remote_url("o/r", "ghp_tok")
    assert url.startswith("https://x-access-token:ghp_tok@github.com/o/r")


def test_is_within_directory(tmp_path):
    base = tmp_path / "ws"
    base.mkdir()
    inside = base / "a" / "b"
    assert is_within_directory(base, inside)
    assert not is_within_directory(base, tmp_path / "other")
