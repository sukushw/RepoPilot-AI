# RepoPilot AI

> **Your AI Software Engineer, accessible through Telegram.**

RepoPilot AI is a **local-first** AI developer assistant you drive from Telegram.
Connect a GitHub repository, send an instruction in plain language (or a slash
command), and RepoPilot delegates the work to an AI coding agent — it reads your
source, analyzes bugs, modifies files, runs tests/builds, and opens a pull
request. **You approve every code change before anything is committed or pushed.**

The original **CrashFix AI** lives on as a specialized Android crash-debugging
module inside RepoPilot.

Everything runs on your laptop: Telegram **long polling**, **SQLite**, local git
clones. No cloud, no server, no Kubernetes. Internet is only needed to reach
Telegram, GitHub, and the AI agents.
https://github.com/user-attachments/assets/2dd99e5a-b9fe-4965-9a03-41a9f61cfe8b

```
python -m app.bot
```

---

## ✨ What it does

| Area | Capabilities |
|------|--------------|
| **Repositories** | Connect public/private GitHub repos, list, switch, disconnect. Clones locally on demand. |
| **Coding** | `/ask`, `/explain`, `/analyze` (read-only) · `/bugfix`, `/refactor`, `/generate` (edit → **approval** → PR). |
| **Code review** | `/review` — findings grouped by severity (Critical → Informational) with file/line references. |
| **Android** | `/crash` crash diagnosis from a real stack trace; `/android`, `/gradle`, `/build`. |
| **Testing/Build** | `/test`, `/testreport`, Gradle/Python/Node detection, failure capture. |
| **Git** | `/diff`, `/branch`, `/commit`, `/pr` — protected branches are never touched. |
| **Tasks** | `/tasks`, `/task`, `/cancel`, `/approve`, `/reject` — persisted in SQLite, run in the background. |
| **Agents** | `/agents` (availability), `/agent <name>` — pluggable Claude Code / Codex adapters. |
| **Natural language** | Just type: _"analyze my repo for performance issues"_ or _"fix the crash in HomeFragment"_. |
| **Dashboard** (optional) | `python -m app.dashboard` — local read-only web view of repos & tasks. |

## 🔒 Safety model

- **Human-in-the-loop:** code modifications apply to a feature branch in an
  isolated clone, you see the **git diff**, and nothing is committed/pushed/PR'd
  until you `/approve`.
- **Protected branches** (`main`, `master`, `production`, …) are never pushed to.
- **Allowlist:** only Telegram IDs in `TELEGRAM_ADMIN_IDS` may use the bot.
- **Secrets** are redacted from Telegram replies and logs; tokens are never
  stored in git remotes on disk.
- **Untrusted repo content:** build/test commands run in **Docker** when enabled
  (`USE_DOCKER=true`), otherwise locally with a hard timeout (clearly less
  isolated — see Limitations).

## 🏛️ Architecture

Clean, layered, provider-agnostic. Telegram handlers are thin; all logic is in
services.

```
app/
├── bot/            Telegram presentation (handlers/, application.py, __main__.py)
├── core/           config, security, logging
├── agents/         CodingAgent abstraction + ClaudeCodeAgent, CodexAgent, manager
├── services/       task, repository, coding, code_review, crash_analysis, build, nlu
├── integrations/   github/ (rest, api, git_cli) · telegram/ (formatting)
├── modules/        crashfix/ (parser, agent) · code_review/ · testing/
├── database/       models, db, repository (DAO)
├── execution/      workspace, docker_runner
└── dashboard/      optional local web UI
tests/              pytest suite (no network/token needed)
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the layer map and
[`docs/DEMO.md`](docs/DEMO.md) for the end-to-end demo script.

## 🛠️ Tech stack

- **Python 3.10+** (runs on 3.9 too), async throughout
- **python-telegram-bot** v20+ (long polling)
- **SQLAlchemy 2** + **SQLite**, **Pydantic 2** settings
- **git CLI** (subprocess) for clone/branch/diff/commit/push
- **GitHub REST API** (httpx) for metadata + pull requests
- **Claude Code CLI** / **OpenAI Codex CLI** as coding agents (pluggable)
- **GitHub Models** (free, OpenAI-compatible) for crash analysis & reasoning

## 🚀 Setup

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                  # then edit .env
```

Fill in `.env` (see the file for full comments):

```env
TELEGRAM_BOT_TOKEN=...               # from @BotFather
TELEGRAM_ADMIN_IDS=123456789         # your numeric Telegram ID
GITHUB_TOKEN=ghp_...                 # read for public; `repo` (write) for PRs
AI_BASE_URL=https://models.inference.ai.azure.com
AI_MODEL=gpt-4o-mini
DEFAULT_AGENT=claude
```

### Coding agent setup

RepoPilot shells out to a coding-agent CLI. Install and authenticate at least one:

- **Claude Code**: install the `claude` CLI and sign in. Check with `claude --version`.
- **Codex** *(optional)*: install the `codex` CLI and authenticate.

Run `/agents` in Telegram to see live availability. A missing/unauthenticated
agent produces a clear setup message rather than a failure.

> **Finding your Telegram ID:** leave `TELEGRAM_ADMIN_IDS` blank, start the bot,
> message it — it replies with your numeric ID. Paste it in and restart.

## ▶️ Run

```bash
python -m app.bot            # the Telegram bot
python -m app.dashboard      # optional: http://127.0.0.1:8765
```

## 🎬 Demo flow

1. `/connect your/android-repo`
2. Paste an Android crash trace → evidence-based diagnosis (root cause + fix diff).
3. `/bugfix fix the null pointer in HomeFragment` → RepoPilot edits a branch and
   shows you the **git diff**.
4. `/approve` → it commits, pushes the branch, and opens a **pull request**; the
   PR link comes back in Telegram.
5. `/test` → runs the project's tests and returns a readable report.

Full script: [`docs/DEMO.md`](docs/DEMO.md).

## ✅ Testing

```bash
python -m pytest -q
```

The suite is hermetic — no token, network, or CLI required (it covers the parser,
security/validation, intent routing, task & repository persistence, agent-manager
availability, build-system detection, and full command registration).

## ⚠️ Limitations (honest status)

- **CLI agents must be installed & authenticated** by you (`claude`/`codex`).
  RepoPilot invokes them; it doesn't bundle credentials.
- **PRs require a write-scoped `GITHUB_TOKEN`** (`repo`). Read-only tokens can do
  crash analysis and read-only coding, but `/approve` (push + PR) will 403.
- **Isolation is reduced without Docker.** With `USE_DOCKER=false` (the default on
  a plain laptop), build/test commands run locally with a timeout but no sandbox.
  Set `USE_DOCKER=true` with Docker installed for real isolation of untrusted
  repo code.
- Agent CLIs evolve; adapters target the verified current interfaces
  (`claude -p --output-format json --permission-mode …`, `codex exec …`). The
  Claude adapter's JSON contract and non-interactive edit behavior are verified
  against the installed CLI.
- **Cancelling a running task** interrupts RepoPilot's `await`, but a coding-agent
  or git subprocess already spawned may keep running to completion in the
  background. Fine for a local demo; noted for honesty.
- **One change at a time per repo:** approve or reject a pending change before
  starting another write task on the same repo (the second would branch from a
  dirty working tree). The primary flow (one task → approve) is unaffected.

## 📄 License

MIT — see [LICENSE](LICENSE).
