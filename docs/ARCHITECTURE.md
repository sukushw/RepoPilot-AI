# RepoPilot AI — Architecture

RepoPilot is organized into layers. Telegram handlers never contain business
logic — they parse input, call a service, and format the reply.

## Layers

1. **Telegram presentation** (`app/bot/`)
   - `application.py` builds the PTB `Application` and registers every command.
   - `handlers/` — one module per command group; `common.py` holds the
     `restricted` allowlist decorator and the progress-notifier factory.
   - `__main__.py` — `python -m app.bot`.

2. **Application / task orchestration** (`app/services/task_service.py`)
   - Runs work as background `asyncio` tasks (the event loop never blocks).
   - Owns task lifecycle: running → completed / failed / cancelled, with a hard
     timeout and cancellation.

3. **AI coding agent abstraction** (`app/agents/`)
   - `base.CodingAgent` — the provider-agnostic contract
     (`analyze/explain/review/fix_bug/refactor/generate_code/generate_tests/…`).
   - `claude_agent.ClaudeCodeAgent` — real `claude` CLI adapter.
   - `codex_agent.CodexAgent` — `codex` CLI adapter (availability-guarded).
   - `agent_manager` — registry + selection + availability reporting.

4. **Repository management** (`app/services/repository_service.py`,
   `app/execution/workspace.py`)
   - Connect/list/switch/disconnect; lazy local clone under `workspace/<user>/`.

5. **Code analysis & debugging** (`app/modules/crashfix/`,
   `app/services/crash_analysis_service.py`)
   - The preserved CrashFix pipeline: parse trace → locate file via GitHub REST →
     fetch source → `CrashFixAgent` diagnoses with a tool-calling loop.

6. **Build & testing** (`app/services/build_service.py`,
   `app/execution/docker_runner.py`)
   - Detects Gradle/Python/Node; runs commands Docker-isolated or locally.

7. **GitHub integration** (`app/integrations/github/`)
   - `rest.py` — read-only investigator (trees + contents).
   - `api.py` — repo metadata + pull-request creation.
   - `git_cli.py` — async `git` subprocess (clone/branch/diff/commit/push).

8. **Database & persistence** (`app/database/`)
   - `models.py` (Repository, Task, UserState), `db.py` (engine/session),
     `repository.py` (DAO used by services).

9. **Security & execution** (`app/core/security.py`, `app/execution/`)
   - Repo URL validation, path containment, secret redaction, token-embedded
     remotes, protected-branch enforcement, task timeouts, workspace isolation.

## The write workflow (safety-critical)

```
/bugfix <desc>
  → create task (pending → running)
  → clone/refresh repo, create feature branch from default branch
  → coding agent edits the working tree
  → git diff computed → task set to WAITING_APPROVAL (nothing committed)
  → user reviews diff in Telegram
     /approve → commit → push branch → open PR → COMPLETED (PR url returned)
     /reject  → discard → CANCELLED
```

`main`/`master`/`production`/… are never pushed to (enforced in both the service
and `git_cli.push`).

## Data model

- **Repository**: user, `owner/repo`, default branch, visibility, local path.
- **Task**: user, repo, kind, description, agent, status, timestamps, result,
  error, branch, pending_action, pr_url.
- **UserState**: active repo + preferred agent per user.
