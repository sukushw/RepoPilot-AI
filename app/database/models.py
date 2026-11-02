"""
app.database.models
===================

SQLAlchemy ORM models for RepoPilot AI. Three tables cover the whole product:

  * ``Repository`` — a GitHub repo a user has connected (and its local clone).
  * ``Task``       — a unit of work delegated to a coding agent, with status.
  * ``UserState``  — per-user preferences (active repo, preferred agent).

Task/repository status values are kept as plain strings (see the ``*_STATUSES``
constants) rather than native SQL enums so the schema stays portable and easy to
migrate by hand for a local-first app.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all models."""


# --- Task status vocabulary -------------------------------------------------

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_WAITING_APPROVAL = "waiting_approval"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

TASK_STATUSES = (
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_WAITING_APPROVAL,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_CANCELLED,
)

# Terminal states a task can't move out of.
TERMINAL_STATUSES = (STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED)


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(Integer, index=True)
    # Canonical "owner/repo".
    ref: Mapped[str] = mapped_column(String(255), index=True)
    owner: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(120))
    default_branch: Mapped[str] = mapped_column(String(120), default="main")
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    # Absolute path to the local clone once it has been created (nullable).
    local_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    tasks: Mapped[list["Task"]] = relationship(back_populates="repository")

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"<Repository {self.ref} user={self.telegram_user_id}>"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(Integer, index=True)
    repository_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("repositories.id"), nullable=True
    )
    # e.g. "bugfix", "refactor", "review", "crash", "generate", "ask", "test".
    kind: Mapped[str] = mapped_column(String(40), default="task")
    description: Mapped[str] = mapped_column(Text, default="")
    agent: Mapped[str] = mapped_column(String(40), default="claude")
    status: Mapped[str] = mapped_column(
        String(40), default=STATUS_PENDING, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Final (or in-progress) human-readable result / report.
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Approval workflow: the branch created for the change and the action that is
    # pending (e.g. "commit_push_pr"), set while status == waiting_approval.
    branch: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pending_action: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    pr_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    repository: Mapped[Optional[Repository]] = relationship(back_populates="tasks")

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"<Task #{self.id} {self.kind} {self.status}>"


class UserState(Base):
    __tablename__ = "user_state"

    telegram_user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    active_repo_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("repositories.id"), nullable=True
    )
    preferred_agent: Mapped[Optional[str]] = mapped_column(
        String(40), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"<UserState user={self.telegram_user_id} repo={self.active_repo_id}>"
