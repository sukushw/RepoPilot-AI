"""
app.database.repository
=======================

Data-access helpers (a thin repository/DAO layer) over the ORM models. Services
call these functions instead of touching SQLAlchemy sessions directly, which
keeps session lifetimes short and the rest of the code free of ORM plumbing.

Every function opens its own short-lived session via ``session_scope``. Because
the engine is configured with ``expire_on_commit=False``, returned objects stay
usable (read-only) after the session closes.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import select

from app.database.db import session_scope
from app.database.models import (
    Repository,
    Task,
    UserState,
    STATUS_PENDING,
    TERMINAL_STATUSES,
)

# --- Repositories -----------------------------------------------------------


def add_repository(
    telegram_user_id: int,
    ref: str,
    owner: str,
    name: str,
    default_branch: str = "main",
    is_private: bool = False,
) -> Repository:
    """Insert a repository for a user (or return the existing one)."""
    with session_scope() as s:
        existing = s.scalar(
            select(Repository).where(
                Repository.telegram_user_id == telegram_user_id,
                Repository.ref == ref,
            )
        )
        if existing:
            existing.default_branch = default_branch
            existing.is_private = is_private
            s.flush()
            s.refresh(existing)
            s.expunge(existing)
            return existing

        repo = Repository(
            telegram_user_id=telegram_user_id,
            ref=ref,
            owner=owner,
            name=name,
            default_branch=default_branch,
            is_private=is_private,
        )
        s.add(repo)
        s.flush()
        s.refresh(repo)
        s.expunge(repo)
        return repo


def list_repositories(telegram_user_id: int) -> List[Repository]:
    with session_scope() as s:
        rows = list(
            s.scalars(
                select(Repository)
                .where(Repository.telegram_user_id == telegram_user_id)
                .order_by(Repository.created_at.desc())
            )
        )
        for r in rows:
            s.expunge(r)
        return rows


def get_repository(repo_id: int) -> Optional[Repository]:
    with session_scope() as s:
        repo = s.get(Repository, repo_id)
        if repo:
            s.expunge(repo)
        return repo


def find_repository(telegram_user_id: int, ref: str) -> Optional[Repository]:
    with session_scope() as s:
        repo = s.scalar(
            select(Repository).where(
                Repository.telegram_user_id == telegram_user_id,
                Repository.ref == ref,
            )
        )
        if repo:
            s.expunge(repo)
        return repo


def set_repository_local_path(repo_id: int, local_path: str) -> None:
    with session_scope() as s:
        repo = s.get(Repository, repo_id)
        if repo:
            repo.local_path = local_path


def delete_repository(telegram_user_id: int, repo_id: int) -> bool:
    with session_scope() as s:
        repo = s.get(Repository, repo_id)
        if not repo or repo.telegram_user_id != telegram_user_id:
            return False
        # Clear it from user state if it was active.
        state = s.get(UserState, telegram_user_id)
        if state and state.active_repo_id == repo_id:
            state.active_repo_id = None
        s.delete(repo)
        return True


# --- User state (active repo, preferred agent) ------------------------------


def _get_or_create_state(s, telegram_user_id: int) -> UserState:
    state = s.get(UserState, telegram_user_id)
    if not state:
        state = UserState(telegram_user_id=telegram_user_id)
        s.add(state)
        s.flush()
    return state


def set_active_repo(telegram_user_id: int, repo_id: Optional[int]) -> None:
    with session_scope() as s:
        state = _get_or_create_state(s, telegram_user_id)
        state.active_repo_id = repo_id


def get_active_repo(telegram_user_id: int) -> Optional[Repository]:
    with session_scope() as s:
        state = s.get(UserState, telegram_user_id)
        if not state or not state.active_repo_id:
            return None
        repo = s.get(Repository, state.active_repo_id)
        if repo:
            s.expunge(repo)
        return repo


def set_preferred_agent(telegram_user_id: int, agent: str) -> None:
    with session_scope() as s:
        state = _get_or_create_state(s, telegram_user_id)
        state.preferred_agent = agent


def get_preferred_agent(telegram_user_id: int) -> Optional[str]:
    with session_scope() as s:
        state = s.get(UserState, telegram_user_id)
        return state.preferred_agent if state else None


# --- Tasks ------------------------------------------------------------------


def create_task(
    telegram_user_id: int,
    kind: str,
    description: str,
    agent: str,
    repository_id: Optional[int] = None,
) -> Task:
    with session_scope() as s:
        task = Task(
            telegram_user_id=telegram_user_id,
            kind=kind,
            description=description,
            agent=agent,
            repository_id=repository_id,
            status=STATUS_PENDING,
        )
        s.add(task)
        s.flush()
        s.refresh(task)
        s.expunge(task)
        return task


def update_task(task_id: int, **fields) -> Optional[Task]:
    """Update arbitrary columns on a task, managing status timestamps."""
    with session_scope() as s:
        task = s.get(Task, task_id)
        if not task:
            return None
        for key, value in fields.items():
            setattr(task, key, value)
        # Maintain lifecycle timestamps automatically.
        status = fields.get("status")
        if status == "running" and task.started_at is None:
            task.started_at = datetime.utcnow()
        if status in TERMINAL_STATUSES and task.completed_at is None:
            task.completed_at = datetime.utcnow()
        s.flush()
        s.refresh(task)
        s.expunge(task)
        return task


def get_task(task_id: int) -> Optional[Task]:
    with session_scope() as s:
        task = s.get(Task, task_id)
        if task:
            s.expunge(task)
        return task


def list_tasks(telegram_user_id: int, limit: int = 15) -> List[Task]:
    with session_scope() as s:
        rows = list(
            s.scalars(
                select(Task)
                .where(Task.telegram_user_id == telegram_user_id)
                .order_by(Task.created_at.desc())
                .limit(limit)
            )
        )
        for t in rows:
            s.expunge(t)
        return rows


def latest_task_awaiting_approval(telegram_user_id: int) -> Optional[Task]:
    with session_scope() as s:
        task = s.scalar(
            select(Task)
            .where(
                Task.telegram_user_id == telegram_user_id,
                Task.status == "waiting_approval",
            )
            .order_by(Task.created_at.desc())
        )
        if task:
            s.expunge(task)
        return task
