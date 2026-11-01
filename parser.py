"""
parser.py
=========

Parse raw Android/Java/Kotlin crash logs (logcat stack traces) into a
structured form the agent can reason about.

The key job here is to separate *framework* frames (android.*, java.*, ...)
from *application* frames, because the root cause almost always lives in the
topmost application frame — that is where we want the LLM to start looking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

# Package prefixes that belong to the platform / standard libraries rather than
# the developer's own application code. Frames in these packages are rarely the
# root cause, so we flag them as "framework" and skip over them when choosing a
# target frame.
FRAMEWORK_PREFIXES = (
    "android.",
    "androidx.",
    "com.android.",
    "java.",
    "javax.",
    "kotlin.",
    "kotlinx.",
    "dalvik.",
    "sun.",
    "libcore.",
)


@dataclass
class StackFrame:
    """A single line of a stack trace, e.g.

        at com.example.app.ui.HomeFragment.onResume(HomeFragment.kt:42)
    """

    class_name: str
    method_name: str
    file_name: Optional[str]
    line_number: Optional[int]
    is_framework: bool
    raw: str = ""  # the original source line, kept for display/debugging

    def __str__(self) -> str:  # pragma: no cover - cosmetic only
        location = ""
        if self.file_name:
            location = self.file_name
            if self.line_number is not None:
                location += f":{self.line_number}"
        return f"{self.class_name}.{self.method_name}({location})"


@dataclass
class ParsedCrash:
    """The structured result of parsing a raw crash log."""

    exception_type: Optional[str]
    exception_message: Optional[str]
    # The topmost *application* frame — the best place to start debugging.
    target_frame: Optional[StackFrame]
    all_frames: List[StackFrame] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.exception_type and not self.all_frames


# --- Regular expressions ----------------------------------------------------

# Matches the exception header line, e.g.:
#   java.lang.IllegalStateException: Fragment not attached to a context.
#   Caused by: java.lang.NullPointerException: Attempt to invoke ...
_EXCEPTION_RE = re.compile(
    r"^(?:Caused by:\s*)?"
    r"(?P<type>(?:[\w$]+\.)+[\w$]+(?:Exception|Error|Throwable))"
    r"(?::\s*(?P<message>.*))?$"
)

# Matches a stack frame line, e.g.:
#   at com.example.app.ui.HomeFragment.onResume(HomeFragment.kt:42)
#   at com.example.Foo.bar(Unknown Source)
#   at com.example.Foo.bar(Native Method)
_FRAME_RE = re.compile(
    r"^\s*at\s+"
    r"(?P<fqmethod>[\w$<>.]+)"            # fully-qualified class + method
    r"\((?P<location>[^)]*)\)\s*$"
)


def _is_framework(class_name: str) -> bool:
    """Return True if the class belongs to a platform/standard-library package."""
    return class_name.startswith(FRAMEWORK_PREFIXES)


def _parse_location(location: str) -> tuple[Optional[str], Optional[int]]:
    """Split the parenthesised part of a frame into (file_name, line_number).

    Handles forms like:
        HomeFragment.kt:42     -> ("HomeFragment.kt", 42)
        Unknown Source         -> (None, None)
        Native Method          -> (None, None)
    """
    location = location.strip()
    if not location or location in ("Unknown Source", "Native Method"):
        return None, None

    if ":" in location:
        file_part, _, line_part = location.rpartition(":")
        try:
            return file_part or None, int(line_part)
        except ValueError:
            return location, None
    return location, None


def _split_fqmethod(fqmethod: str) -> tuple[str, str]:
    """Split 'com.example.Foo.onResume' into ('com.example.Foo', 'onResume')."""
    class_name, _, method_name = fqmethod.rpartition(".")
    if not class_name:  # no dot found; unusual, but stay defensive
        return fqmethod, ""
    return class_name, method_name


def parse_android_crash(raw_log: str) -> ParsedCrash:
    """Parse a raw Android crash log into a :class:`ParsedCrash`.

    Strategy:
      * Walk the log line by line.
      * The first exception header we see is treated as the primary exception
        (``Caused by:`` lines further down refine the chain but we keep the
        first type/message as the headline).
      * Every ``at ...`` line becomes a :class:`StackFrame`.
      * ``target_frame`` is the first application (non-framework) frame.
    """
    exception_type: Optional[str] = None
    exception_message: Optional[str] = None
    all_frames: List[StackFrame] = []

    for line in raw_log.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        # Try to match a stack frame first (it's the most common line type).
        frame_match = _FRAME_RE.match(line)
        if frame_match:
            class_name, method_name = _split_fqmethod(frame_match.group("fqmethod"))
            file_name, line_number = _parse_location(frame_match.group("location"))
            all_frames.append(
                StackFrame(
                    class_name=class_name,
                    method_name=method_name,
                    file_name=file_name,
                    line_number=line_number,
                    is_framework=_is_framework(class_name),
                    raw=stripped,
                )
            )
            continue

        # Otherwise, see if this is an exception header. We only capture the
        # *first* one as the headline exception, but we still scan the rest in
        # case the first informative header appears after some noise.
        exc_match = _EXCEPTION_RE.match(stripped)
        if exc_match and exception_type is None:
            exception_type = exc_match.group("type")
            message = exc_match.group("message")
            exception_message = message.strip() if message else None

    # Choose the topmost application frame as the debugging target.
    target_frame = next((f for f in all_frames if not f.is_framework), None)

    return ParsedCrash(
        exception_type=exception_type,
        exception_message=exception_message,
        target_frame=target_frame,
        all_frames=all_frames,
    )


def format_parsed_summary(parsed: ParsedCrash) -> str:
    """Produce a short human-readable summary (handy for status messages)."""
    lines: List[str] = []
    if parsed.exception_type:
        header = parsed.exception_type
        if parsed.exception_message:
            header += f": {parsed.exception_message}"
        lines.append(header)
    if parsed.target_frame:
        lines.append(f"→ Likely in: {parsed.target_frame}")
    else:
        lines.append("→ No application frame identified (only framework frames).")
    return "\n".join(lines) if lines else "No exception detected in the log."
