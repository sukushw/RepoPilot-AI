"""
app.services.crash_analysis_service
==================================

The preserved CrashFix AI pipeline, now a service inside RepoPilot. It keeps the
original, working approach: parse the trace → locate the file via the GitHub REST
API → fetch the source around the crash line → let the Android-specialized
``CrashFixAgent`` diagnose and propose a fix (with its tool-calling loop for
layouts/manifest).

This path intentionally does NOT clone the repo or use the CLI coding agents —
it works directly off GitHub, exactly as before. After analysis, the user can ask
a coding agent to *apply* the suggested fix (that goes through the coding
workflow + approval), which keeps diagnosis fast and modification gated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from openai import AsyncOpenAI

from app.core.config import settings
from app.database.models import Repository
from app.integrations.github.rest import GitHubInvestigator
from app.modules.crashfix.agent import CrashFixAgent
from app.modules.crashfix.parser import format_parsed_summary, parse_android_crash


@dataclass
class CrashAnalysisResult:
    ok: bool
    summary: str
    report: str = ""
    file_path: Optional[str] = None
    line: Optional[int] = None
    error: Optional[str] = None


def _llm_client() -> AsyncOpenAI:
    # GitHub Models uses GITHUB_TOKEN as the API key.
    return AsyncOpenAI(base_url=settings.ai_base_url, api_key=settings.github_token)


async def analyze_crash(repo: Repository, raw_log: str) -> CrashAnalysisResult:
    """Run the full crash diagnosis for ``raw_log`` against ``repo``."""
    if not settings.has_github_token:
        return CrashAnalysisResult(
            ok=False,
            summary="",
            error="GITHUB_TOKEN is not configured, so I can't read source code.",
        )

    parsed = parse_android_crash(raw_log)
    if parsed.is_empty or parsed.target_frame is None:
        return CrashAnalysisResult(
            ok=False,
            summary=format_parsed_summary(parsed),
            error=(
                "I couldn't find an application stack frame. Make sure you pasted "
                "a full Android stack trace including the `at com.yourapp...` lines."
            ),
        )

    tf = parsed.target_frame
    investigator = GitHubInvestigator(
        token=settings.github_token,
        repo=repo.ref,
        default_branch=repo.default_branch,
    )

    file_path = await investigator.find_file_path(tf.file_name or "")
    if not file_path:
        return CrashAnalysisResult(
            ok=False,
            summary=format_parsed_summary(parsed),
            error=(
                f"I couldn't find `{tf.file_name}` in `{repo.ref}` "
                f"(branch `{repo.default_branch}`). Check the branch/file."
            ),
        )

    target_line = tf.line_number or 1
    snippet = await investigator.get_source_snippet(file_path, target_line)

    agent = CrashFixAgent(openai_client=_llm_client(), model=settings.ai_model)
    report = await agent.analyze(
        parsed=parsed,
        source_snippet=snippet,
        investigator=investigator,
        file_path=file_path,
    )

    return CrashAnalysisResult(
        ok=True,
        summary=format_parsed_summary(parsed),
        report=report,
        file_path=file_path,
        line=target_line,
    )
