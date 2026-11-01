# CrashFix AI — Android Crash Debugging Agent (Telegram)

Send an Android crash report to a Telegram bot, point it at your GitHub
repository, and an AI agent inspects the **actual source code on GitHub**,
diagnoses the root cause, and replies with a code-fix diff.

Unlike a generic "paste your stack trace" chatbot, CrashFix AI reads the real
file at the crashing line (and any related layouts/manifest it asks for) before
answering.

## 🎥 Demo

Watch CrashFix AI in action:

**▶️ [Watch the demo video](REPLACE_WITH_YOUR_VIDEO_LINK)**

<!-- Replace REPLACE_WITH_YOUR_VIDEO_LINK above with your video URL
     (e.g. a YouTube, Loom, or Google Drive link). -->

## How it works

```text
Telegram user
   │  /repo owner/repo [branch]   +   crash trace (text or .txt/.log file)
   ▼
main.py  (python-telegram-bot)
   │
   ├─ parser.py          parse the stack trace, find the topmost APP frame
   │
   ├─ github_tools.py    locate the file via GitHub Tree API,
   │                     fetch the source around the crash line
   │
   └─ agent.py           LLM diagnoses the root cause & writes a fix diff;
                         may call read_additional_file for layouts/manifest
   ▼
Root Cause + Bug Location + Code Fix (diff)  ──▶  back to Telegram
```

## Files

| File | Responsibility |
|------|----------------|
| `parser.py` | Parse Android/Java/Kotlin stack traces; separate framework frames from app frames; pick the crash target frame. |
| `github_tools.py` | `GitHubInvestigator` — find a file's path (Tree API), fetch numbered source snippets and supplementary files (Contents API). |
| `agent.py` | `CrashFixAgent` — Android-specialized prompt, tool-calling loop for `read_additional_file`, returns Markdown (root cause / location / diff). |
| `main.py` | Telegram bot: commands, message/document handlers, status updates, response splitting, provider wiring. |

## Requirements

- Python 3.10+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A GitHub Personal Access Token (`GITHUB_TOKEN`) with read access to the repo
- A free LLM endpoint — **GitHub Models** (uses `GITHUB_TOKEN`)

## Setup

```bash
python -m venv .venv

# macOS/Linux
source .venv/bin/activate
# Windows PowerShell
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
cp .env.example .env
```

Then edit `.env`:

```env
TELEGRAM_BOT_TOKEN=your_telegram_token
TELEGRAM_ADMIN_IDS=123456789
GITHUB_TOKEN=ghp_your_token
AI_BASE_URL=https://models.inference.ai.azure.com
AI_MODEL=gpt-4o-mini
```

> **Note:** `GITHUB_TOKEN` does double duty — it authenticates the GitHub API
> calls that read your source code *and* serves as the LLM key for GitHub
> Models. One token is all you need.

### Access control (admin only)

The bot only responds to the Telegram user IDs listed in
`TELEGRAM_ADMIN_IDS` (comma-separated). Everyone else is denied — this prevents
strangers from using your token quota or inspecting repos.

**Finding your ID:** leave `TELEGRAM_ADMIN_IDS` blank the first time, start the
bot, and message it — it replies with your numeric ID. Paste that into
`TELEGRAM_ADMIN_IDS`, restart, and you're the only one who can use it. Add more
IDs separated by commas to authorize additional people.

## Run

```bash
python main.py
```

Then, in Telegram:

1. `/start` — see the welcome and instructions.
2. `/repo owner/repo [branch]` — connect a repository (branch defaults to `main`).
   e.g. `/repo octocat/MyApp main`
3. Send the crash — paste the stack trace as a message, **or** upload a `.txt` /
   `.log` file.
4. The bot replies with **Root Cause**, **Bug Location**, and a **Code Fix** diff.

## Example crash trace

```text
FATAL EXCEPTION: main
Process: com.example.app, PID: 1234
java.lang.IllegalStateException: Fragment HomeFragment not attached to a context.
    at androidx.fragment.app.Fragment.requireContext(Fragment.java:1000)
    at com.example.app.ui.HomeFragment.onResume(HomeFragment.kt:42)
```

CrashFix AI skips the `androidx` framework frame, identifies
`HomeFragment.kt:42` as the crash site, reads that file from GitHub, and
diagnoses the lifecycle/attachment bug.

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and usage. |
| `/help` | Show available commands. |
| `/repo owner/repo [branch]` | Connect a GitHub repository. |

(Just send or upload a crash trace after connecting a repo.)

## Notes & limitations

- Repo selection is stored **in memory** per user — it resets when the bot
  restarts. (Swap in SQLite for persistence.)
- The agent **analyzes and proposes** a fix; it does not commit or open PRs.
- Access is **restricted to `TELEGRAM_ADMIN_IDS`** — only listed users can use
  the bot (see "Access control" above).
- Keep `.env` out of version control (already in `.gitignore`).
- `parser.py` shadows a same-named (removed) standard-library module locally —
  this is intentional and harmless; tooling may flag it as "deprecated module".

## Troubleshooting

- **Bot doesn't respond** — check `TELEGRAM_BOT_TOKEN` and that only one process
  is polling.
- **"Couldn't read the repository tree"** — verify the `owner/repo`, the branch,
  and that `GITHUB_TOKEN` can access the repo.
- **"Analysis failed"** — check `AI_BASE_URL`, the matching API key, and
  `AI_MODEL` for your chosen provider.
- **File not found in repo** — the branch may be wrong, or the file genuinely
  isn't in that repo/branch.
