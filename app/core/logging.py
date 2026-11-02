"""
app.core.logging
================

Single place to configure logging for the whole application. Importing and
calling :func:`setup_logging` once (from the entry point) gives every module a
consistent, timestamped logger.
"""

from __future__ import annotations

import logging

_CONFIGURED = False


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logging once. Safe to call multiple times."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=level,
    )
    # Telegram's httpx logging is noisy at INFO; quiet it down.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger, e.g. ``get_logger("repopilot.tasks")``."""
    return logging.getLogger(name)
