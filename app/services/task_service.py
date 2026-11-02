"""
app.services.task_service
========================

Runs delegated work as background ``asyncio`` tasks so the Telegram event loop
never blocks while a coding agent, git operation, or build is in flight. Also the
single source of truth for task lifecycle in the database.

A *workflow* is an ``async`` coroutine that performs the actual work and is
responsible for setting the task's terminal or waiting-for-approval status. This
service wraps it with:

  * ``running`` status on start,
  * a hard timeout (``settings.task_timeout_seconds``),
  * ``cancelled`` handling (via :meth:`cancel`),
  * ``failed`` capture for any unhandled exception.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Dict, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import redact_secrets
from app.database import repository as db
from app.database.models import (
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_RUNNING,
    TERMINAL_STATUSES,
)

logger = get_logger("repopilot.tasks")

# A workflow receives the task id and returns nothing (it updates its own status).
Workflow = Callable[[int], Awaitable[None]]


class TaskService:
    def __init__(self) -> None:
        self._running: Dict[int, asyncio.Task] = {}

    def is_running(self, task_id: int) -> bool:
        aio = self._running.get(task_id)
        return aio is not None and not aio.done()

    def cancel(self, task_id: int) -> bool:
        """Request cancellation of a running task. Returns True if it was live."""
        aio = self._running.get(task_id)
        if aio and not aio.done():
            aio.cancel()
            return True
        return False

    def launch(self, task_id: int, workflow: Workflow) -> asyncio.Task:
        """Start ``workflow`` for ``task_id`` as a tracked background task."""
        aio = asyncio.create_task(self._supervise(task_id, workflow))
        self._running[task_id] = aio
        aio.add_done_callback(lambda _t: self._running.pop(task_id, None))
        return aio

    async def _supervise(self, task_id: int, workflow: Workflow) -> None:
        db.update_task(task_id, status=STATUS_RUNNING)
        try:
            await asyncio.wait_for(
                workflow(task_id), timeout=settings.task_timeout_seconds
            )
        except asyncio.CancelledError:
            db.update_task(
                task_id, status=STATUS_CANCELLED, error="Cancelled by user."
            )
            logger.info("Task %s cancelled", task_id)
            raise
        except asyncio.TimeoutError:
            db.update_task(
                task_id,
                status=STATUS_FAILED,
                error=f"Timed out after {settings.task_timeout_seconds}s.",
            )
            logger.warning("Task %s timed out", task_id)
        except Exception as exc:  # noqa: BLE001 - we want to record any failure
            db.update_task(
                task_id, status=STATUS_FAILED, error=redact_secrets(str(exc))
            )
            logger.exception("Task %s failed", task_id)
        else:
            # If the workflow didn't set a terminal/waiting status, mark complete.
            task = db.get_task(task_id)
            if task and task.status == STATUS_RUNNING:
                db.update_task(task_id, status="completed")


# Module-level singleton.
task_service = TaskService()
