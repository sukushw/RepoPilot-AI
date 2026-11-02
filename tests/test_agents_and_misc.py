from __future__ import annotations

import asyncio
from pathlib import Path

from app.agents.agent_manager import agent_manager
from app.core.config import Settings, _parse_ids
from app.execution.docker_runner import docker_available
from app.integrations.telegram.formatting import split_message
from app.services.build_service import detect_build_system


def test_agent_manager_names_and_resolve():
    assert set(agent_manager.names) == {"claude", "codex"}
    assert agent_manager.resolve_name(None) in ("claude", "codex")
    assert agent_manager.resolve_name("nope") == "claude"
    assert agent_manager.get("codex").name == "codex"


def test_agent_status_runs_without_crash():
    # Should never raise even if a CLI is missing; returns AgentStatus.
    statuses = asyncio.run(agent_manager.statuses())
    names = {s.name for s in statuses}
    assert names == {"claude", "codex"}
    for s in statuses:
        assert isinstance(s.available, bool)
        assert s.detail  # a human-readable message either way


def test_parse_ids():
    assert _parse_ids("1, 2 ;3, bad, 4") == {1, 2, 3, 4}
    assert _parse_ids("") == set()


def test_protected_branches():
    s = Settings()
    assert s.is_protected_branch("main")
    assert s.is_protected_branch("MASTER")
    assert not s.is_protected_branch("feature/x")


def test_split_message():
    text = "\n".join(f"line {i}" for i in range(1000))
    chunks = split_message(text, limit=200)
    assert all(len(c) <= 200 for c in chunks)
    assert "".join(chunks) == text


def test_detect_build_system(tmp_path: Path):
    (tmp_path / "gradlew").write_text("#!/bin/sh\n")
    assert detect_build_system(tmp_path) == "gradle"

    py = tmp_path / "py"
    py.mkdir()
    (py / "pyproject.toml").write_text("[tool.pytest]\n")
    assert detect_build_system(py) == "python"

    empty = tmp_path / "empty"
    empty.mkdir()
    assert detect_build_system(empty) == "unknown"


def test_docker_available_is_bool():
    assert isinstance(docker_available(), bool)
