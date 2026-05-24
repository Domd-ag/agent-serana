"""
Backend agent system.

Includes the three primary agent roles:
- Serana: chief singleton agent
- Aide: coordination agent
- Forge: worker agent
"""

from .aide import AideAgent
from .base import (
    AgentManifest,
    AgentManager,
    AgentSkill,
    AgentState,
    AgentTool,
    AgentType,
    get_all_agent_types,
    load_manifest,
)
from .forge import ForgeAgent
from .serana import SeranaAgent


__all__ = [
    "AgentType",
    "AgentSkill",
    "AgentTool",
    "AgentManifest",
    "AgentState",
    "load_manifest",
    "get_all_agent_types",
    "AgentManager",
    "SeranaAgent",
    "AideAgent",
    "ForgeAgent",
]
