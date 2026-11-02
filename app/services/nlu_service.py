"""
app.services.nlu_service
=======================

Lightweight natural-language intent routing for free-text Telegram messages.

The router is deliberately **rule-based and deterministic** so it works offline,
is unit-testable without a network/LLM, and never silently misfires an expensive
coding task. It maps a plain message like "analyze my repo for performance
issues" to an intent (``analyze``) plus the cleaned instruction, which the bot
then runs through the same service a slash command would use.

Intents returned: crash, review, bugfix, refactor, generate, explain, analyze,
test, build, ask (the default fallback — a general question about the repo).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

from app.modules.crashfix.parser import parse_android_crash


@dataclass
class Intent:
    name: str
    instruction: str


# Ordered (intent, keyword-patterns). First match wins, so put the more specific
# intents earlier. Patterns are matched case-insensitively against the message.
_RULES: List[Tuple[str, List[str]]] = [
    ("review", [r"\breview\b", r"code review", r"review (the|my|this) (diff|changes|pr|code)"]),
    ("bugfix", [r"\bfix\b", r"bug ?fix", r"null pointer", r"\bcrash(es)? in\b", r"resolve the (bug|issue|error)"]),
    ("refactor", [r"\brefactor\b", r"clean up", r"\bsimplify\b", r"restructure"]),
    ("generate", [r"\bgenerate\b(?!.*test)", r"\bimplement\b", r"\badd (a|an|the)\b", r"\bcreate (a|an|the)\b", r"\bwrite (a|an|the)\b"]),
    ("test", [r"\bgenerate tests?\b", r"\bwrite tests?\b", r"\bunit tests?\b", r"\brun tests?\b", r"\btest coverage\b"]),
    ("build", [r"\bbuild\b", r"\bgradle\b", r"\bcompile\b", r"assemble"]),
    ("explain", [r"\bexplain\b", r"what does .* do", r"how does .* work", r"\bwalk me through\b"]),
    ("analyze", [r"\banalyze\b", r"\banalyse\b", r"identify .* (issues|problems|bugs)", r"performance issues", r"security (issues|review)"]),
]


def _looks_like_stacktrace(text: str) -> bool:
    """Heuristic: does the message look like an Android/Java crash trace?"""
    if "\tat " in text or re.search(r"^\s*at\s+[\w$.]+\(", text, re.MULTILINE):
        parsed = parse_android_crash(text)
        return not parsed.is_empty
    if re.search(r"(Exception|Error|Throwable):", text) and "at " in text:
        return True
    return False


def classify(text: str) -> Intent:
    """Classify a free-text message into an :class:`Intent`."""
    cleaned = text.strip()
    if _looks_like_stacktrace(cleaned):
        return Intent("crash", cleaned)

    lowered = cleaned.lower()
    for intent_name, patterns in _RULES:
        for pat in patterns:
            if re.search(pat, lowered):
                return Intent(intent_name, cleaned)

    return Intent("ask", cleaned)
