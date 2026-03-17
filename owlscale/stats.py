"""Flywheel metrics for owlscale — per-agent stats and system health."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from owlscale.core import load_state, load_roster
from owlscale.models import TaskStatus


@dataclass
class AgentStats:
    """Per-agent statistics."""
    agent_id: str
    total_tasks: int = 0
    accepted: int = 0
    rejected: int = 0
    in_progress: int = 0
    dispatched: int = 0
    returned: int = 0
    pass_rate: Optional[float] = None
    rework_rate: Optional[float] = None
    avg_duration_hours: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "total_tasks": self.total_tasks,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "in_progress": self.in_progress,
            "dispatched": self.dispatched,
            "returned": self.returned,
            "pass_rate": self.pass_rate,
            "rework_rate": self.rework_rate,
            "avg_duration_hours": self.avg_duration_hours,
        }


@dataclass
class SystemStats:
    """System-wide statistics."""
    total_tasks: int = 0
    by_status: Dict[str, int] = field(default_factory=dict)
    agents: Dict[str, AgentStats] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "total_tasks": self.total_tasks,
            "by_status": self.by_status,
            "agents": {k: v.to_dict() for k, v in self.agents.items()},
        }


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    """Parse ISO 8601 timestamp, return None on failure."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _compute_duration_hours(dispatched_at: Optional[str], end_at: Optional[str]) -> Optional[float]:
    """Compute duration in hours between dispatch and completion."""
    start = _parse_iso(dispatched_at)
    end = _parse_iso(end_at)
    if start and end:
        delta = (end - start).total_seconds()
        if delta >= 0:
            return delta / 3600.0
    return None


def compute_stats(owlscale_dir: Path) -> SystemStats:
    """Compute flywheel metrics from state.json."""
    state = load_state(owlscale_dir)
    roster = load_roster(owlscale_dir)

    system = SystemStats(total_tasks=len(state.tasks))

    # Count by status
    for task_state in state.tasks.values():
        status_val = task_state.status.value
        system.by_status[status_val] = system.by_status.get(status_val, 0) + 1

    # Per-agent stats
    agent_durations: Dict[str, list[float]] = {}

    for task_id, task_state in state.tasks.items():
        assignee = task_state.assignee
        if not assignee:
            continue

        if assignee not in system.agents:
            system.agents[assignee] = AgentStats(agent_id=assignee)

        agent = system.agents[assignee]
        agent.total_tasks += 1

        if task_state.status == TaskStatus.accepted:
            agent.accepted += 1
            dur = _compute_duration_hours(task_state.dispatched_at, task_state.accepted_at)
            if dur is not None:
                agent_durations.setdefault(assignee, []).append(dur)
        elif task_state.status == TaskStatus.rejected:
            agent.rejected += 1
            dur = _compute_duration_hours(task_state.dispatched_at, task_state.rejected_at)
            if dur is not None:
                agent_durations.setdefault(assignee, []).append(dur)
        elif task_state.status == TaskStatus.in_progress:
            agent.in_progress += 1
        elif task_state.status == TaskStatus.dispatched:
            agent.dispatched += 1
        elif task_state.status == TaskStatus.returned:
            agent.returned += 1

    # Compute derived metrics
    for agent_id, agent in system.agents.items():
        completed = agent.accepted + agent.rejected
        if completed > 0:
            agent.pass_rate = agent.accepted / completed
            agent.rework_rate = agent.rejected / completed

        durations = agent_durations.get(agent_id, [])
        if durations:
            agent.avg_duration_hours = sum(durations) / len(durations)

    # Include agents from roster that have no tasks yet
    for agent_id in roster:
        if agent_id not in system.agents:
            system.agents[agent_id] = AgentStats(agent_id=agent_id)

    return system
