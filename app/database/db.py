"""
app.database.db
===============

Database engine + session management. SQLite via SQLAlchemy. A single engine is
created from ``settings.database_url`` and tables are created on first use.

The coding agents and git operations run in background threads, so we use a
``scoped_session`` style factory and short-lived sessions (open → use → close)
rather than one long-lived session, which keeps SQLite happy under concurrency.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.database.models import Base

# check_same_thread=False: background task threads reuse the engine safely as
# long as each uses its own short-lived Session (which we enforce below).
_engine = create_engine(
    settings.database_url,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
)

SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)


def init_db() -> None:
    """Create all tables if they don't already exist."""
    Base.metadata.create_all(_engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_engine():
    """Expose the engine (used by tests that need a clean teardown)."""
    return _engine
