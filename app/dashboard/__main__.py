"""Entry point: ``python -m app.dashboard`` — the optional local dashboard."""

from __future__ import annotations

from app.dashboard.server import serve

if __name__ == "__main__":
    serve()
