from __future__ import annotations

from app.database import repository as db
from app.database.models import STATUS_COMPLETED, STATUS_WAITING_APPROVAL


def test_repository_crud_and_active():
    repo = db.add_repository(42, "octocat/Hello-World", "octocat", "Hello-World", "main")
    assert repo.id is not None

    # Idempotent add returns the same ref.
    again = db.add_repository(42, "octocat/Hello-World", "octocat", "Hello-World", "dev")
    assert again.ref == "octocat/Hello-World"

    db.set_active_repo(42, repo.id)
    active = db.get_active_repo(42)
    assert active and active.ref == "octocat/Hello-World"

    repos = db.list_repositories(42)
    assert any(r.ref == "octocat/Hello-World" for r in repos)


def test_task_lifecycle():
    repo = db.add_repository(43, "o/r", "o", "r", "main")
    task = db.create_task(43, "bugfix", "fix NPE", "claude", repo.id)
    assert task.status == "pending"

    db.update_task(task.id, status="running")
    running = db.get_task(task.id)
    assert running.status == "running"
    assert running.started_at is not None

    db.update_task(
        task.id, status=STATUS_WAITING_APPROVAL, branch="repopilot/bugfix-1", result="diff"
    )
    waiting = db.latest_task_awaiting_approval(43)
    assert waiting and waiting.id == task.id
    assert waiting.branch == "repopilot/bugfix-1"

    db.update_task(task.id, status=STATUS_COMPLETED, pr_url="https://x/pr/1")
    done = db.get_task(task.id)
    assert done.status == STATUS_COMPLETED
    assert done.completed_at is not None
    assert done.pr_url.endswith("/pr/1")


def test_preferred_agent_persists():
    db.set_preferred_agent(44, "codex")
    assert db.get_preferred_agent(44) == "codex"


def test_disconnect_clears_active():
    repo = db.add_repository(45, "a/b", "a", "b", "main")
    db.set_active_repo(45, repo.id)
    assert db.delete_repository(45, repo.id) is True
    assert db.get_active_repo(45) is None
