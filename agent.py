"""
agent.py
========

The AI debugging agent. It takes a parsed crash plus the source snippet around
the crash line, then asks an Android-specialized LLM to diagnose the root cause
and propose a fix.

The agent supports *tool use*: the model can call ``read_additional_file`` to
pull in extra files (layouts, the manifest, related classes) before answering.
We run a proper tool-calling loop — feeding tool results back to the model and
letting it call more tools — until it produces a final answer.
"""

from __future__ import annotations

import json
from typing import List, Optional

from openai import AsyncOpenAI

from github_tools import GitHubInvestigator
from parser import ParsedCrash

# How many rounds of tool calls we allow before forcing a final answer. This
# prevents an accidental infinite loop if the model keeps asking for files.
MAX_TOOL_ROUNDS = 6

SYSTEM_PROMPT = """\
You are CrashFix AI, an expert Android engineer who specializes in debugging \
crashes in Kotlin and Java Android apps. You are given a parsed crash report \
and a snippet of the actual source code at the crash location, read directly \
from the developer's GitHub repository.

Diagnose the ROOT CAUSE precisely. Pay special attention to the bugs that most \
commonly cause Android crashes:
  * Lifecycle issues — using a Fragment/Activity/Context after it is destroyed, \
    accessing views after onDestroyView, requireContext()/requireActivity() when \
    not attached.
  * ViewBinding — accessing `binding` after onDestroyView without nulling it, or \
    a nullable binding dereferenced with `!!`.
  * Coroutines — launching on the wrong scope, updating UI after cancellation, \
    uncaught exceptions in a non-supervised scope, wrong dispatcher.
  * Null safety — Kotlin `!!`, unsafe casts, nullable platform types from Java, \
    findViewById returning null.
  * Resource / threading issues — updating UI off the main thread, missing \
    resources, index out of bounds.

If you need more context (a layout XML referenced by the code, \
AndroidManifest.xml, or another class/file), call the `read_additional_file` \
tool with just the file name. Only ask for files you genuinely need.

When you are confident, respond with GitHub-flavored Markdown using EXACTLY \
these sections:

## Root Cause
A clear, specific explanation of why the crash happens.

## Bug Location
The file and line number (e.g. `HomeFragment.kt:42`) where the bug lives.

## Code Fix
A unified diff (```diff fenced block) showing the minimal change that fixes the \
bug. Use `-` for removed lines and `+` for added lines with correct context. \
If a diff is impractical, show the corrected code block and explain what to \
change.

Keep the whole answer focused and concise. Do not invent code you have not \
seen — if something is uncertain, say so.
"""

# The JSON schema describing the tool the model may call.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_additional_file",
            "description": (
                "Read another file from the GitHub repository (e.g. a layout "
                "XML, AndroidManifest.xml, or a related Kotlin/Java class) to "
                "gather more context before diagnosing the crash. Provide just "
                "the file name; the full path is resolved automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": (
                            "The file name to read, e.g. 'fragment_home.xml', "
                            "'AndroidManifest.xml', or 'HomeViewModel.kt'."
                        ),
                    }
                },
                "required": ["filename"],
            },
        },
    }
]


class CrashFixAgent:
    """Drives the LLM conversation that diagnoses and fixes a crash."""

    def __init__(self, openai_client: AsyncOpenAI, model: str):
        self.client = openai_client
        self.model = model

    def _build_user_prompt(
        self, parsed: ParsedCrash, source_snippet: str, file_path: Optional[str]
    ) -> str:
        """Assemble the initial user message from the parsed crash + source."""
        parts: List[str] = []

        parts.append("# Crash Report")
        parts.append(f"**Exception:** {parsed.exception_type or 'unknown'}")
        if parsed.exception_message:
            parts.append(f"**Message:** {parsed.exception_message}")

        if parsed.target_frame:
            tf = parsed.target_frame
            parts.append(
                f"**Crash frame:** `{tf.class_name}.{tf.method_name}` "
                f"in `{tf.file_name}:{tf.line_number}`"
            )

        # Include a compact view of the application frames for extra context.
        app_frames = [f for f in parsed.all_frames if not f.is_framework]
        if app_frames:
            parts.append("\n**Application stack frames (top to bottom):**")
            for f in app_frames[:10]:
                parts.append(f"- {f}")

        parts.append("\n# Source at the crash location")
        if file_path:
            parts.append(f"File: `{file_path}`")
        parts.append("```")
        parts.append(source_snippet)
        parts.append("```")

        parts.append(
            "\nDiagnose the root cause and propose a fix. Request additional "
            "files with the tool if you need them."
        )
        return "\n".join(parts)

    async def analyze(
        self,
        parsed: ParsedCrash,
        source_snippet: str,
        investigator: GitHubInvestigator,
        file_path: Optional[str] = None,
    ) -> str:
        """Run the full tool-calling loop and return the final Markdown answer.

        Parameters
        ----------
        parsed:
            The structured crash from :func:`parser.parse_android_crash`.
        source_snippet:
            Numbered source around the crash line (from the investigator).
        investigator:
            Used to service ``read_additional_file`` tool calls.
        file_path:
            The resolved path of the crashing file, for display.
        """
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": self._build_user_prompt(parsed, source_snippet, file_path),
            },
        ]

        # Tool-calling loop: keep going until the model answers without asking
        # for more files, or we hit the safety cap.
        for _ in range(MAX_TOOL_ROUNDS):
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.2,
            )
            choice = response.choices[0]
            message = choice.message

            tool_calls = message.tool_calls or []
            if not tool_calls:
                # No tool requested — this is the final answer.
                return message.content or "(The model returned an empty response.)"

            # Append the assistant's tool-call message, then answer each call.
            messages.append(
                {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )

            for tc in tool_calls:
                result = await self._handle_tool_call(tc, investigator)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    }
                )

        # Safety cap reached: make one final request that forbids more tools so
        # we always return an answer rather than looping forever.
        final = await self.client.chat.completions.create(
            model=self.model,
            messages=messages
            + [
                {
                    "role": "user",
                    "content": (
                        "Stop requesting files and give your best diagnosis and "
                        "fix now, using the information gathered so far."
                    ),
                }
            ],
            temperature=0.2,
        )
        return final.choices[0].message.content or "(No diagnosis produced.)"

    async def _handle_tool_call(
        self, tool_call, investigator: GitHubInvestigator
    ) -> str:
        """Execute a single tool call and return its result as a string."""
        if tool_call.function.name != "read_additional_file":
            return f"(Unknown tool: {tool_call.function.name})"

        try:
            args = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError:
            return "(Could not parse tool arguments.)"

        filename = args.get("filename")
        if not filename:
            return "(No filename provided.)"

        content = await investigator.get_manifest_or_layout(filename)
        # Guard against flooding the context with a huge file.
        if len(content) > 8000:
            content = content[:8000] + "\n... (truncated)"
        return f"Contents of {filename}:\n{content}"
