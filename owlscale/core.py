"""Core business logic for owlscale."""

import json
from pathlib import Path
from typing import Optional, Dict, Any
import sys

from owlscale.models import (
    Agent, AgentRole, TaskState, TaskStatus, GlobalState,
    PacketFrontmatter, Packet, PacketType, now_iso8601
)


class OwlscaleError(Exception):
    """Base exception for owlscale operations."""
    pass


class WorkspaceError(OwlscaleError):
    """Workspace initialization or access error."""
    pass


class TaskError(OwlscaleError):
    """Task-related error."""
    pass


class AgentError(OwlscaleError):
    """Agent registration error."""
    pass


def get_workspace_root(start_path: Path = None) -> Path:
    """Find .owlscale/ directory (search up from current directory)."""
    if start_path is None:
        start_path = Path.cwd()

    current = start_path.resolve()
    while current != current.parent:
        owlscale_dir = current / ".owlscale"
        if owlscale_dir.exists() and owlscale_dir.is_dir():
            return owlscale_dir
        current = current.parent

    raise WorkspaceError(
        f"No .owlscale/ found. Run 'owlscale init' to initialize."
    )


def init_project(root_dir: Path = None) -> Path:
    """Initialize .owlscale/ directory structure in the specified directory."""
    if root_dir is None:
        root_dir = Path.cwd()
    else:
        root_dir = Path(root_dir).resolve()

    owlscale_dir = root_dir / ".owlscale"
    if owlscale_dir.exists():
        # Do not overwrite existing workspace.
        return owlscale_dir

    # Create directory structure
    (owlscale_dir / "packets").mkdir(parents=True)
    (owlscale_dir / "returns").mkdir(parents=True)
    (owlscale_dir / "log").mkdir(parents=True)
    (owlscale_dir / "templates").mkdir(parents=True)

    # Initialize state.json
    state = GlobalState()
    state_path = owlscale_dir / "state.json"
    state_path.write_text(json.dumps(state.to_dict(), indent=2))

    # Initialize roster.json
    roster_path = owlscale_dir / "roster.json"
    roster_path.write_text(json.dumps({"agents": {}}, indent=2))

    return owlscale_dir


def load_state(owlscale_dir: Path) -> GlobalState:
    """Load global state from state.json."""
    state_path = owlscale_dir / "state.json"
    if not state_path.exists():
        return GlobalState()
    data = json.loads(state_path.read_text())
    return GlobalState.from_dict(data)


def save_state(owlscale_dir: Path, state: GlobalState) -> None:
    """Save global state to state.json."""
    state_path = owlscale_dir / "state.json"
    state_path.write_text(json.dumps(state.to_dict(), indent=2))


def load_roster(owlscale_dir: Path) -> Dict[str, Agent]:
    """Load agent roster from roster.json."""
    roster_path = owlscale_dir / "roster.json"
    if not roster_path.exists():
        return {}
    data = json.loads(roster_path.read_text())
    return {
        agent_id: Agent.from_dict(agent_id, agent_data)
        for agent_id, agent_data in data.get("agents", {}).items()
    }


def save_roster(owlscale_dir: Path, agents: Dict[str, Agent]) -> None:
    """Save agent roster to roster.json."""
    roster_path = owlscale_dir / "roster.json"
    roster_data = {
        agent_id: agent.to_dict()
        for agent_id, agent in agents.items()
    }
    roster_path.write_text(json.dumps({"agents": roster_data}, indent=2))


def add_agent(owlscale_dir: Path, agent_id: str, name: str, role: str) -> Agent:
    """Register a new agent."""
    roster = load_roster(owlscale_dir)
    if agent_id in roster:
        raise AgentError(f"Agent '{agent_id}' already registered.")

    try:
        agent_role = AgentRole(role)
    except ValueError:
        raise AgentError(f"Invalid role '{role}'. Must be: {', '.join([r.value for r in AgentRole])}")

    agent = Agent(id=agent_id, name=name, role=agent_role)
    roster[agent_id] = agent
    save_roster(owlscale_dir, roster)
    return agent


def remove_agent(owlscale_dir: Path, agent_id: str) -> None:
    """Unregister an agent."""
    roster = load_roster(owlscale_dir)
    if agent_id not in roster:
        raise AgentError(f"Agent '{agent_id}' not found.")
    del roster[agent_id]
    save_roster(owlscale_dir, roster)


def list_agents(owlscale_dir: Path) -> Dict[str, Agent]:
    """List all registered agents."""
    return load_roster(owlscale_dir)


def pack_task(owlscale_dir: Path, task_id: str, goal: str, tags: list = None, parent: str = None, template: str = None) -> Path:
    """Create a Context Packet."""
    state = load_state(owlscale_dir)

    if task_id in state.tasks:
        raise TaskError(f"Task '{task_id}' already exists.")

    if tags is None:
        tags = []

    # Create task state
    now = now_iso8601()
    task_state = TaskState(status=TaskStatus.draft, created_at=now, parent=parent)
    state.tasks[task_id] = task_state
    save_state(owlscale_dir, state)

    # Create packet
    frontmatter = PacketFrontmatter(
        id=task_id,
        type=PacketType.context,
        goal=goal,
        status=TaskStatus.draft,
        created=now,
        parent=parent,
        tags=tags,
    )

    template_body = f"""## Goal

{goal}

## Current State

<!-- Describe the current state of the project/system -->

## Confirmed Findings

<!-- What have you verified so far? -->

## Relevant Files

<!-- List files that are relevant to this task -->

## Scope

**In scope:**
- 

**Out of scope:**
- 

## Constraints

<!-- Any limitations or requirements? -->

## Execution Plan

1. 

## Validation

<!-- How will the deliverable be verified? -->

## Expected Output

<!-- What is the expected result? -->

## Open Risks

<!-- What could go wrong? -->
"""

    if template:
        from owlscale.template import get_template
        template_body = get_template(owlscale_dir, template)

    packet = Packet(frontmatter=frontmatter, body=template_body)
    packet_path = owlscale_dir / "packets" / f"{task_id}.md"
    packet_path.write_text(packet.to_markdown())

    # Log the event
    _write_log(owlscale_dir, f"PACK   {task_id}")

    return packet_path


def dispatch_task(owlscale_dir: Path, task_id: str, agent_id: str) -> None:
    """Dispatch a task to an agent."""
    state = load_state(owlscale_dir)
    roster = load_roster(owlscale_dir)

    if task_id not in state.tasks:
        raise TaskError(f"Task '{task_id}' not found.")

    if agent_id not in roster:
        raise AgentError(f"Agent '{agent_id}' not registered.")

    task_state = state.tasks[task_id]
    if task_state.status not in [TaskStatus.draft, TaskStatus.ready]:
        raise TaskError(
            f"Cannot dispatch task in '{task_state.status.value}' state. "
            f"Task must be in 'draft' or 'ready' state."
        )

    # Update state
    now = now_iso8601()
    task_state.status = TaskStatus.dispatched
    task_state.assignee = agent_id
    task_state.dispatched_at = now
    save_state(owlscale_dir, state)

    # Update packet frontmatter
    packet_path = owlscale_dir / "packets" / f"{task_id}.md"
    goal = ""
    if packet_path.exists():
        packet = Packet.from_markdown(packet_path.read_text())
        packet.frontmatter.status = TaskStatus.dispatched
        packet.frontmatter.assignee = agent_id
        goal = packet.frontmatter.goal
        packet_path.write_text(packet.to_markdown())

    # Auto-generate return template
    _generate_return_template(owlscale_dir, task_id, goal)

    # Log the event
    _write_log(owlscale_dir, f"DISPATCH {task_id}  to={agent_id}")


def claim_task(owlscale_dir: Path, task_id: str) -> None:
    """Claim a dispatched task (transition: dispatched → in_progress)."""
    state = load_state(owlscale_dir)

    if task_id not in state.tasks:
        raise TaskError(f"Task '{task_id}' not found.")

    task_state = state.tasks[task_id]
    if task_state.status != TaskStatus.dispatched:
        raise TaskError(
            f"Cannot claim task in '{task_state.status.value}' state. "
            f"Task must be in 'dispatched' state."
        )

    # Update state
    task_state.status = TaskStatus.in_progress
    save_state(owlscale_dir, state)

    # Log the event
    _write_log(owlscale_dir, f"CLAIM   {task_id}")


def return_task(owlscale_dir: Path, task_id: str) -> None:
    """Mark task as returned (result submitted)."""
    state = load_state(owlscale_dir)

    if task_id not in state.tasks:
        raise TaskError(f"Task '{task_id}' not found.")

    task_state = state.tasks[task_id]
    if task_state.status not in [TaskStatus.dispatched, TaskStatus.in_progress]:
        raise TaskError(
            f"Cannot return task in '{task_state.status.value}' state. "
            f"Task must be in 'dispatched' or 'in_progress' state."
        )

    # Check return packet exists
    return_path = owlscale_dir / "returns" / f"{task_id}.md"
    if not return_path.exists():
        raise TaskError(
            f"Return packet not found: {return_path}\n"
            f"Please create the return packet first and place it at: {return_path}"
        )

    # Update state
    now = now_iso8601()
    task_state.status = TaskStatus.returned
    task_state.returned_at = now
    save_state(owlscale_dir, state)

    # Log the event
    _write_log(owlscale_dir, f"RETURN  {task_id}")


def accept_task(owlscale_dir: Path, task_id: str) -> None:
    """Accept a returned task."""
    state = load_state(owlscale_dir)

    if task_id not in state.tasks:
        raise TaskError(f"Task '{task_id}' not found.")

    task_state = state.tasks[task_id]
    if task_state.status != TaskStatus.returned:
        raise TaskError(
            f"Cannot accept task in '{task_state.status.value}' state. "
            f"Task must be in 'returned' state."
        )

    # Update state
    now = now_iso8601()
    task_state.status = TaskStatus.accepted
    task_state.accepted_at = now
    save_state(owlscale_dir, state)

    # Log the event
    _write_log(owlscale_dir, f"ACCEPT  {task_id}")


def reject_task(owlscale_dir: Path, task_id: str, reason: str = "") -> None:
    """Reject a returned task."""
    state = load_state(owlscale_dir)

    if task_id not in state.tasks:
        raise TaskError(f"Task '{task_id}' not found.")

    task_state = state.tasks[task_id]
    if task_state.status != TaskStatus.returned:
        raise TaskError(
            f"Cannot reject task in '{task_state.status.value}' state. "
            f"Task must be in 'returned' state."
        )

    # Update state
    now = now_iso8601()
    task_state.status = TaskStatus.rejected
    task_state.rejected_at = now
    save_state(owlscale_dir, state)

    # Log the event
    reason_part = f" reason={reason}" if reason else ""
    _write_log(owlscale_dir, f"REJECT  {task_id}{reason_part}")


def get_status(owlscale_dir: Path) -> GlobalState:
    """Get global task status."""
    return load_state(owlscale_dir)


def get_log(owlscale_dir: Path, task_id: str = None, limit: int = None) -> list:
    """Get operation log entries, optionally filtered."""
    log_dir = owlscale_dir / "log"
    log_files = sorted(log_dir.glob("*.log"))

    entries = []
    for log_file in log_files:
        for line in log_file.read_text().strip().split("\n"):
            if line.strip():
                entries.append(line)

    # Filter by task_id if specified
    if task_id:
        entries = [e for e in entries if f" {task_id}" in e or f" {task_id}\n" in e]

    # Reverse to show newest first
    entries.reverse()

    # Limit results if specified
    if limit:
        entries = entries[:limit]

    return entries


def _generate_return_template(owlscale_dir: Path, task_id: str, goal: str) -> Path:
    """Generate a Return Packet template for a dispatched task.

    Only creates the file if it doesn't already exist.
    """
    returns_dir = owlscale_dir / "returns"
    returns_dir.mkdir(parents=True, exist_ok=True)
    return_path = returns_dir / f"{task_id}.md"

    if return_path.exists():
        return return_path

    goal_line = goal if goal else "(no goal specified)"
    template = f"""# Return Packet: {task_id}

## Summary

{goal_line}

<!-- Describe what was done and the outcome -->

## Files Modified

<!-- List each file with a one-line explanation -->
- 

## Key Decisions

<!-- Document important decisions made during implementation -->
- 

## Tests Run

<!-- Paste test output summary or describe manual testing -->

## Remaining Risks

<!-- What could still go wrong? -->
- None identified

## Unfinished Items

<!-- What is left to do, if anything? -->
- None
"""
    return_path.write_text(template)
    return return_path


def _write_log(owlscale_dir: Path, message: str) -> None:
    """Append message to daily log file."""
    from datetime import date
    log_dir = owlscale_dir / "log"
    log_dir.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    log_file = log_dir / f"{today}.log"

    timestamp = now_iso8601()
    log_entry = f"{timestamp} {message}\n"

    with open(log_file, "a") as f:
        f.write(log_entry)
