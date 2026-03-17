"""Data models for owlscale (using dataclasses and Enum)."""

from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime
from typing import Optional, Dict, Any
import json


class TaskStatus(str, Enum):
    """Task lifecycle states."""
    draft = "draft"
    ready = "ready"
    dispatched = "dispatched"
    in_progress = "in_progress"
    returned = "returned"
    accepted = "accepted"
    rejected = "rejected"


class PacketType(str, Enum):
    """Packet types."""
    context = "context"
    return_packet = "return"
    patch = "patch"


class AgentRole(str, Enum):
    """Agent roles in the system."""
    coordinator = "coordinator"
    executor = "executor"
    hub = "hub"


@dataclass
class Agent:
    """Agent registration entry."""
    id: str
    name: str
    role: AgentRole
    strengths: list[str] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)
    tool: Optional[str] = None
    delivery: Dict[str, Any] = field(default_factory=dict)
    launch: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "name": self.name,
            "role": self.role.value,
            "strengths": self.strengths,
            "constraints": self.constraints,
        }
        if self.tool is not None:
            result["tool"] = self.tool
        if self.delivery:
            result["delivery"] = self.delivery
        if self.launch:
            result["launch"] = self.launch
        return result

    @staticmethod
    def from_dict(agent_id: str, data: Dict[str, Any]) -> "Agent":
        tool = data.get("tool")
        delivery = data.get("delivery", {})
        launch = data.get("launch", {})
        return Agent(
            id=agent_id,
            name=data.get("name", agent_id),
            role=AgentRole(data.get("role", "executor")),
            strengths=data.get("strengths", []),
            constraints=data.get("constraints", {}),
            tool=tool if isinstance(tool, str) else None,
            delivery=delivery if isinstance(delivery, dict) else {},
            launch=launch if isinstance(launch, dict) else {},
        )


@dataclass
class TaskState:
    """State of a single task in state.json."""
    status: TaskStatus
    assignee: Optional[str] = None
    created_at: Optional[str] = None
    dispatched_at: Optional[str] = None
    returned_at: Optional[str] = None
    accepted_at: Optional[str] = None
    rejected_at: Optional[str] = None
    parent: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {"status": self.status.value}
        for key in ["assignee", "created_at", "dispatched_at", "returned_at", "accepted_at", "rejected_at", "parent"]:
            val = getattr(self, key)
            if val is not None:
                result[key] = val
        return result

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "TaskState":
        return TaskState(
            status=TaskStatus(data.get("status", "draft")),
            assignee=data.get("assignee"),
            created_at=data.get("created_at"),
            dispatched_at=data.get("dispatched_at"),
            returned_at=data.get("returned_at"),
            accepted_at=data.get("accepted_at"),
            rejected_at=data.get("rejected_at"),
            parent=data.get("parent"),
        )


@dataclass
class GlobalState:
    """Global state in state.json."""
    version: int = 1
    tasks: Dict[str, TaskState] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "tasks": {task_id: state.to_dict() for task_id, state in self.tasks.items()},
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "GlobalState":
        return GlobalState(
            version=data.get("version", 1),
            tasks={
                task_id: TaskState.from_dict(task_data)
                for task_id, task_data in data.get("tasks", {}).items()
            },
        )


@dataclass
class PacketFrontmatter:
    """YAML frontmatter for a Packet."""
    id: str
    type: PacketType
    goal: str
    status: TaskStatus
    assignee: Optional[str] = None
    created: Optional[str] = None
    parent: Optional[str] = None
    tags: list[str] = field(default_factory=list)

    def to_yaml_dict(self) -> Dict[str, Any]:
        result = {
            "id": self.id,
            "type": self.type.value,
            "goal": self.goal,
            "status": self.status.value,
        }
        if self.assignee is not None:
            result["assignee"] = self.assignee
        if self.created is not None:
            result["created"] = self.created
        if self.parent is not None:
            result["parent"] = self.parent
        if self.tags:
            result["tags"] = self.tags
        return result

    @staticmethod
    def from_yaml_dict(data: Dict[str, Any]) -> "PacketFrontmatter":
        return PacketFrontmatter(
            id=data.get("id", ""),
            type=PacketType(data.get("type", "context")),
            goal=data.get("goal", ""),
            status=TaskStatus(data.get("status", "draft")),
            assignee=data.get("assignee"),
            created=data.get("created"),
            parent=data.get("parent"),
            tags=data.get("tags", []),
        )


@dataclass
class Packet:
    """Complete Packet (frontmatter + body)."""
    frontmatter: PacketFrontmatter
    body: str

    def to_markdown(self) -> str:
        """Convert to markdown with YAML frontmatter."""
        import yaml
        yaml_dict = self.frontmatter.to_yaml_dict()
        yaml_str = yaml.dump(yaml_dict, default_flow_style=False, sort_keys=False)
        return f"---\n{yaml_str}---\n\n{self.body}"

    @staticmethod
    def from_markdown(content: str) -> "Packet":
        """Parse markdown with YAML frontmatter."""
        import yaml
        lines = content.split("\n")
        if not lines[0].strip() == "---":
            raise ValueError("Invalid packet format: missing opening ---")

        end_idx = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break

        if end_idx == -1:
            raise ValueError("Invalid packet format: missing closing ---")

        yaml_content = "\n".join(lines[1:end_idx])
        frontmatter_dict = yaml.safe_load(yaml_content) or {}
        frontmatter = PacketFrontmatter.from_yaml_dict(frontmatter_dict)

        body = "\n".join(lines[end_idx + 1:]).lstrip("\n")
        return Packet(frontmatter=frontmatter, body=body)


def now_iso8601() -> str:
    """Return current time in ISO 8601 with timezone."""
    return datetime.now().astimezone().isoformat()
