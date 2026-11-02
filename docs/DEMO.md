# RepoPilot AI — Local Demo Walkthrough

A complete, reproducible demo on a laptop: Telegram + GitHub + an AI coding agent.

## 0. Prerequisites

- Python deps installed (`pip install -r requirements.txt`).
- `.env` filled: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_IDS`, `GITHUB_TOKEN`
  (with **`repo` write scope** if you want the PR step), `DEFAULT_AGENT=claude`.
- `git` on PATH.
- A coding agent authenticated: `claude --version` should work (run `/agents`
  in Telegram to confirm).
- An Android GitHub repo you can push to (for the PR step).

Start the bot:

```bash
python -m app.bot
# optional, in a second terminal:
python -m app.dashboard   # http://127.0.0.1:8765
```

## 1. Authorize yourself

If `TELEGRAM_ADMIN_IDS` is blank, message the bot — it replies with your numeric
ID. Put it in `.env`, restart.

## 2. Connect a repository

```
/connect your-org/your-android-app
```

RepoPilot verifies the repo (default branch, visibility) and makes it active.
Check with `/repo` and `/repos`.

## 3. Diagnose an Android crash (CrashFix module)

Paste a stack trace as a normal message (or `/crash <trace>`, or upload a
`.txt`/`.log`). Example:

```
FATAL EXCEPTION: main
java.lang.IllegalStateException: Fragment HomeFragment not attached to a context.
    at androidx.fragment.app.Fragment.requireContext(Fragment.java:1000)
    at com.example.app.ui.HomeFragment.onResume(HomeFragment.kt:42)
```

RepoPilot skips framework frames, reads `HomeFragment.kt:42` from GitHub, and
returns **Root Cause / Bug Location / Code Fix (diff)** with confidence.

## 4. Ask RepoPilot to fix it (coding agent + approval)

```
/bugfix fix the lifecycle crash in HomeFragment.onResume
```

- A task starts (`/tasks` to watch). RepoPilot clones the repo, creates a
  `repopilot/bugfix-…` branch, and the agent edits the code.
- You receive the agent's summary **and the proposed git diff**. Nothing is
  committed yet.

## 5. Review the diff and approve

Inspect the diff in Telegram (or `/diff`). Then:

```
/approve
```

RepoPilot commits, pushes the feature branch, and opens a **pull request** —
the PR URL is returned in Telegram. (`/reject` discards instead.)

## 6. Run tests / build

```
/test        # runs Gradle/Python/Node tests, returns a report
/build       # builds the app
/testreport  # re-show the last report
```

## 7. Other things to try

- `/review` — AI code review of the latest changes, grouped by severity.
- `/analyze analyze my repo for performance issues` — read-only analysis.
- `/explain how the login flow works`.
- Natural language: just type _"refactor the networking layer"_.
- `/agent codex` then `/agents` — switch/inspect coding agents.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Bot silent | Check `TELEGRAM_BOT_TOKEN`; only one polling process. |
| "not authorized" | Add your ID to `TELEGRAM_ADMIN_IDS`, restart. |
| Agent "unavailable" | Install/authenticate `claude` (or `codex`); run `/agents`. |
| `/approve` 403 | `GITHUB_TOKEN` needs `repo` (write) scope. |
| "couldn't read repository tree" | Check repo name/branch and token access. |
| Crash "no app frame" | Paste the full trace incl. `at com.yourapp…` lines. |
