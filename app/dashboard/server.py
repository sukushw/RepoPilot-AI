"""
app.dashboard.server
====================

An optional, local-only web dashboard. Read-only view of connected repositories,
tasks, and recent reports. Uses only the Python standard library (no Flask) to
avoid extra dependencies — the primary interface is always Telegram.

Run with::

    python -m app.dashboard        # serves on http://127.0.0.1:8765

Binds to 127.0.0.1 only, so it is never exposed off the machine.
"""

from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sqlalchemy import select

from app.core.config import settings
from app.database.db import SessionLocal, init_db
from app.database.models import Repository, Task

HOST = "127.0.0.1"
PORT = 8765


def _collect() -> dict:
    with SessionLocal() as s:
        repos = list(s.scalars(select(Repository).order_by(Repository.created_at.desc())))
        tasks = list(s.scalars(select(Task).order_by(Task.created_at.desc()).limit(50)))
        return {
            "repos": [
                {"id": r.id, "ref": r.ref, "branch": r.default_branch,
                 "private": r.is_private, "user": r.telegram_user_id}
                for r in repos
            ],
            "tasks": [
                {"id": t.id, "kind": t.kind, "status": t.status, "agent": t.agent,
                 "desc": (t.description or "")[:80], "pr": t.pr_url or ""}
                for t in tasks
            ],
        }


def _render(data: dict) -> str:
    def esc(x) -> str:
        return html.escape(str(x))

    repo_rows = "".join(
        f"<tr><td>{esc(r['id'])}</td><td>{esc(r['ref'])}</td>"
        f"<td>{esc(r['branch'])}</td><td>{'private' if r['private'] else 'public'}</td></tr>"
        for r in data["repos"]
    ) or "<tr><td colspan=4><em>No repositories connected</em></td></tr>"

    def badge(status: str) -> str:
        colors = {
            "completed": "#1a7f37", "failed": "#cf222e", "running": "#9a6700",
            "waiting_approval": "#8250df", "cancelled": "#57606a", "pending": "#0969da",
        }
        return (
            f"<span style='background:{colors.get(status,'#57606a')};color:#fff;"
            f"padding:2px 8px;border-radius:10px;font-size:12px'>{esc(status)}</span>"
        )

    def pr_cell(pr: str) -> str:
        return '<a href="' + esc(pr) + '">PR</a>' if pr else ""

    task_rows = "".join(
        f"<tr><td>{esc(t['id'])}</td><td>{esc(t['kind'])}</td>"
        f"<td>{badge(t['status'])}</td><td>{esc(t['agent'])}</td>"
        f"<td>{esc(t['desc'])}</td>"
        f"<td>{pr_cell(t['pr'])}</td></tr>"
        for t in data["tasks"]
    ) or "<tr><td colspan=6><em>No tasks yet</em></td></tr>"

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>RepoPilot AI — Dashboard</title>
<meta http-equiv="refresh" content="10">
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f6f8fa;color:#1f2328}}
 header{{background:#24292f;color:#fff;padding:16px 24px}}
 h1{{margin:0;font-size:20px}} .sub{{opacity:.8;font-size:13px}}
 main{{max-width:960px;margin:24px auto;padding:0 16px}}
 .card{{background:#fff;border:1px solid #d0d7de;border-radius:8px;margin-bottom:24px;overflow:hidden}}
 .card h2{{font-size:15px;margin:0;padding:12px 16px;border-bottom:1px solid #d0d7de;background:#f6f8fa}}
 table{{width:100%;border-collapse:collapse;font-size:14px}}
 td,th{{text-align:left;padding:8px 16px;border-bottom:1px solid #eaeef2}}
 th{{font-size:12px;text-transform:uppercase;color:#656d76}}
 .meta{{font-size:12px;color:#656d76;padding:8px 16px}}
</style></head>
<body>
<header><h1>🚀 RepoPilot AI</h1>
<div class="sub">Local dashboard — auto-refreshes every 10s · agent: {esc(settings.default_agent)} ·
docker: {'on' if settings.use_docker else 'off'}</div></header>
<main>
 <div class="card"><h2>Connected repositories ({len(data['repos'])})</h2>
 <table><tr><th>ID</th><th>Repo</th><th>Branch</th><th>Visibility</th></tr>{repo_rows}</table></div>
 <div class="card"><h2>Tasks (latest {len(data['tasks'])})</h2>
 <table><tr><th>ID</th><th>Kind</th><th>Status</th><th>Agent</th><th>Description</th><th>PR</th></tr>{task_rows}</table></div>
 <div class="meta">Primary interface is Telegram. This page is read-only.</div>
</main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence noisy per-request logging
        pass

    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/") in ("/api/data",):
            payload = json.dumps(_collect()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)
            return
        body = _render(_collect()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)


def serve(host: str = HOST, port: int = PORT) -> None:
    init_db()
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"RepoPilot dashboard: http://{host}:{port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
