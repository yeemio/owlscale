"""Task routing logic for owlscale — auto-route tasks to best-fit agents."""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from owlscale.core import (
    load_roster, load_state, TaskError, AgentError,
)
from owlscale.models import Agent, AgentRole, Packet, TaskStatus


@dataclass
class RouteCandidate:
    """A scored agent candidate for task routing."""
    agent_id: str
    agent: Agent
    score: float
    reasons: list[str]


def _extract_tags_and_keywords(owlscale_dir: Path, task_id: str) -> list[str]:
    """Extract tags and goal keywords from a task's packet."""
    packet_path = owlscale_dir / "packets" / f"{task_id}.md"
    keywords: list[str] = []

    if packet_path.exists():
        packet = Packet.from_markdown(packet_path.read_text())
        keywords.extend(t.lower() for t in packet.frontmatter.tags)
        # Extract meaningful words from goal (>3 chars, lowered)
        for word in packet.frontmatter.goal.split():
            cleaned = word.strip(".,;:!?()\"'").lower()
            if len(cleaned) > 3:
                keywords.append(cleaned)

    return keywords


def _score_agent(agent: Agent, keywords: list[str], state_tasks: dict) -> RouteCandidate:
    """Score an agent for a task based on strengths and current load."""
    score = 0.0
    reasons = []

    # Only executors and hubs can receive tasks
    if agent.role == AgentRole.coordinator:
        return RouteCandidate(agent.id, agent, -1.0, ["coordinator cannot receive tasks"])

    # Strength matching: each matching strength adds points
    agent_strengths = [s.lower() for s in agent.strengths]
    matched = set()
    for kw in keywords:
        for strength in agent_strengths:
            if kw in strength or strength in kw:
                matched.add(strength)

    if matched:
        score += len(matched) * 10.0
        reasons.append(f"strengths match: {', '.join(sorted(matched))}")

    # Base score for being available
    score += 5.0

    # Penalize agents with high in-progress load
    active_count = sum(
        1 for ts in state_tasks.values()
        if ts.assignee == agent.id
        and ts.status in [TaskStatus.dispatched, TaskStatus.in_progress]
    )
    if active_count > 0:
        penalty = active_count * 3.0
        score -= penalty
        reasons.append(f"load penalty: {active_count} active task(s)")

    # Bonus for agents with good track record (accepted tasks)
    accepted = sum(
        1 for ts in state_tasks.values()
        if ts.assignee == agent.id and ts.status == TaskStatus.accepted
    )
    if accepted > 0:
        score += min(accepted * 2.0, 10.0)
        reasons.append(f"track record: {accepted} accepted")

    return RouteCandidate(agent.id, agent, score, reasons)


def route_task(
    owlscale_dir: Path,
    task_id: str,
    top_n: int = 3,
) -> list[RouteCandidate]:
    """Score and rank agents for a task. Returns candidates sorted by score (desc).

    Does NOT dispatch — caller decides which agent to use.
    """
    state = load_state(owlscale_dir)
    roster = load_roster(owlscale_dir)

    if task_id not in state.tasks:
        raise TaskError(f"Task '{task_id}' not found.")

    if not roster:
        raise AgentError("No agents registered. Run 'owlscale roster add' first.")

    keywords = _extract_tags_and_keywords(owlscale_dir, task_id)

    candidates = []
    for agent_id, agent in roster.items():
        candidate = _score_agent(agent, keywords, state.tasks)
        if candidate.score >= 0:
            candidates.append(candidate)

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:top_n]
