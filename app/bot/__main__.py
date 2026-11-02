"""
Entry point: ``python -m app.bot``.

Keeps the module import side-effect free; all startup happens in :func:`run`.
"""

from __future__ import annotations

from app.bot.application import run
from app.core.logging import setup_logging


def main() -> None:
    setup_logging()
    run()


if __name__ == "__main__":
    main()
