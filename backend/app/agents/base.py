import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.core.logger import get_logger


request_logger = get_logger("app.request.agents")
BASE_DIR = Path(__file__).parent
AGENT_LIMITS_PATH = BASE_DIR / "agent_limits.json"


class AgentType(str, Enum):
    CHIEF = "chief"
    TEAM_LEAD = "team_lead"
    WORKER = "worker"


class AgentSkill(BaseModel):
    id: str = Field(..., description="Skill ID")
    name: str = Field(..., description="Skill name")
    description: str = Field(..., description="Skill description")
    enabled: bool = Field(default=True, description="Whether the skill is enabled")


class AgentTool(BaseModel):
    id: str = Field(..., description="Tool ID")
    name: str = Field(..., description="Tool name")
    description: str = Field(..., description="Tool description")


class AgentManifest(BaseModel):
    name: str = Field(..., description="Agent name")
    display_name: str = Field(..., description="Display name")
    description: str = Field(..., description="Agent description")
    version: str = Field(..., description="Version")
    agent_type: AgentType = Field(..., description="Agent type")
    max_instances: int = Field(default=1, description="Maximum instance count")
    skills: List[AgentSkill] = Field(default_factory=list, description="Skills")
    tools: List[AgentTool] = Field(default_factory=list, description="Tools")


class AgentState(BaseModel):
    agent_id: str = Field(..., description="Agent ID")
    agent_name: str = Field(..., description="Agent name")
    current_task: Optional[str] = Field(default=None, description="Current task")
    status: str = Field(default="idle", description="Current status")
    thinking_blocks: List[Dict[str, Any]] = Field(default_factory=list, description="Thinking blocks")


def load_agent_limits() -> Dict[str, int]:
    if not AGENT_LIMITS_PATH.exists():
        return {}

    try:
        with open(AGENT_LIMITS_PATH, "r", encoding="utf-8") as f:
            raw_limits = json.load(f)
    except Exception as exc:
        logger.warning("Failed to load agent limits config: %s", exc)
        return {}

    limits: Dict[str, int] = {}
    for agent_type, value in raw_limits.items():
        try:
            parsed_value = int(value)
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid agent limit for %s: %r", agent_type, value)
            continue
        if parsed_value < 1:
            logger.warning("Ignoring non-positive agent limit for %s: %r", agent_type, value)
            continue
        limits[str(agent_type)] = parsed_value
    return limits


def get_agent_limit(agent_type: str) -> Optional[int]:
    return load_agent_limits().get(agent_type)


def load_manifest(agent_type: str) -> Optional[AgentManifest]:
    manifest_path = BASE_DIR / agent_type / "manifest.json"
    if not manifest_path.exists():
        return None

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        configured_limit = get_agent_limit(agent_type)
        if configured_limit is not None:
            data["max_instances"] = configured_limit
        return AgentManifest(**data)
    except Exception as exc:
        logger.warning("Failed to load manifest for %s: %s", agent_type, exc)
        return None


def get_all_agent_types() -> List[str]:
    agent_dirs: List[str] = []
    for item in BASE_DIR.iterdir():
        if item.is_dir() and not item.name.startswith("__") and (item / "manifest.json").exists():
            agent_dirs.append(item.name)
    return agent_dirs


class AgentManager:
    _instance: Optional["AgentManager"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self.llm: Optional[Any] = None
            self.agent_pools: Dict[str, List[Any]] = {}
            self.agent_counts: Dict[str, int] = {}
            self._initialized = True

    def initialize(self, llm: Any) -> None:
        self.llm = llm
        self.agent_pools = {}
        self.agent_counts = {}

        for agent_type in ["forge"]:
            manifest = load_manifest(agent_type)
            if manifest:
                self.agent_counts[agent_type] = 0
                self.agent_pools[agent_type] = []

        request_logger.info("Initialized agent manager with agent types: %s", list(self.agent_counts.keys()))

    def _reserve_agent(self, agent: Any) -> Any:
        agent.state.status = "reserved"
        agent.state.current_task = None
        return agent

    async def get_agent(self, agent_type: str):
        if self.llm is None:
            raise RuntimeError("AgentManager not initialized. Call initialize() first.")

        if agent_type == "serana":
            configured_limit = get_agent_limit("serana")
            if configured_limit is not None and configured_limit != 1:
                request_logger.warning(
                    "Serana uses a singleton implementation; configured limit %s is ignored.",
                    configured_limit,
                )
            from .serana import SeranaAgent

            return SeranaAgent(self.llm)

        manifest = load_manifest(agent_type)
        if not manifest:
            raise ValueError(f"Unknown agent type: {agent_type}")

        available = [
            agent
            for agent in self.agent_pools.get(agent_type, [])
            if agent.state.status == "idle"
        ]
        if available:
            request_logger.info("Reusing idle %s agent: %s", agent_type, available[0].state.agent_id)
            return self._reserve_agent(available[0])

        current_count = self.agent_counts.get(agent_type, 0)
        if current_count >= manifest.max_instances:
            raise RuntimeError(f"Max instances reached for {agent_type}: {manifest.max_instances}")

        if agent_type == "forge":
            from .forge import ForgeAgent

            agent = ForgeAgent(self.llm)
        else:
            raise ValueError(f"Unknown agent type: {agent_type}")

        self.agent_pools.setdefault(agent_type, []).append(agent)
        self.agent_counts[agent_type] = self.agent_counts.get(agent_type, 0) + 1
        request_logger.info("Created new %s agent. Total instances: %s", agent_type, self.agent_counts[agent_type])
        return self._reserve_agent(agent)

    def get_all_agents_status(self) -> List[Dict[str, Any]]:
        statuses: List[Dict[str, Any]] = []

        if self.llm:
            try:
                from .serana import SeranaAgent

                serana = SeranaAgent(self.llm)
                status = serana.get_status()
                statuses.append(
                    {
                        "id": status.agent_id,
                        "name": status.agent_name,
                        "type": "serana",
                        "status": status.status,
                        "current_task": status.current_task,
                    }
                )
            except Exception as exc:
                request_logger.warning("Error getting Serana status: %s", exc)

        for agent_type, agents in self.agent_pools.items():
            for agent in agents:
                status = agent.get_status()
                statuses.append(
                    {
                        "id": status.agent_id,
                        "name": status.agent_name,
                        "type": agent_type,
                        "status": status.status,
                        "current_task": status.current_task,
                    }
                )

        return statuses

    def get_manifest(self, agent_type: str) -> Optional[AgentManifest]:
        return load_manifest(agent_type)
