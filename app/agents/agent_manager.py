"""
app.agents.agent_manager
========================

Registry and selection for coding agents. Handlers ask the manager for an agent
by name (or the configured default) and get back a :class:`CodingAgent`. The
manager also reports availability for the ``/agents`` command.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from app.agents.base import AgentStatus, CodingAgent
from app.agents.claude_agent import ClaudeCodeAgent
from app.agents.codex_agent import CodexAgent
from app.core.config import settings


class AgentManager:
    def __init__(self) -> None:
        self._agents: Dict[str, CodingAgent] = {
            "claude": ClaudeCodeAgent(),
            "codex": CodexAgent(),
        }

    @property
    def names(self) -> List[str]:
        return list(self._agents.keys())

    def get(self, name: Optional[str] = None) -> CodingAgent:
        """Return the named agent, falling back to the configured default."""
        key = (name or settings.default_agent or "claude").strip().lower()
        if key not in self._agents:
            key = "claude"
        return self._agents[key]

    def resolve_name(self, name: Optional[str]) -> str:
        key = (name or settings.default_agent or "claude").strip().lower()
        return key if key in self._agents else "claude"

    async def statuses(self) -> List[AgentStatus]:
        return [await agent.get_status() for agent in self._agents.values()]


# Module-level singleton.
agent_manager = AgentManager()
