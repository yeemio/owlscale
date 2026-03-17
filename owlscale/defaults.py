"""Auto-detect AI coding agents in a project and register defaults."""

from pathlib import Path
from typing import List, Tuple

from owlscale.core import add_agent, load_roster, AgentError


# (marker_path_or_glob, agent_id, agent_name, role)
AGENT_SIGNATURES: list[tuple[str, str, str, str]] = [
    (".claude", "claude-code", "Claude Code", "coordinator"),
    (".github/copilot-instructions.md", "copilot", "GitHub Copilot", "executor"),
    ("copilot/", "copilot", "GitHub Copilot", "executor"),
    (".cursor", "cursor", "Cursor", "executor"),
    (".cursorignore", "cursor", "Cursor", "executor"),
    (".cursorrules", "cursor", "Cursor", "executor"),
    (".aider.chat.history.md", "aider", "Aider", "executor"),
    (".aider.conf.yml", "aider", "Aider", "executor"),
    (".continue", "continue-dev", "Continue", "executor"),
    (".codeium", "codeium", "Codeium", "executor"),
]


def detect_agents(project_root: Path) -> List[Tuple[str, str, str]]:
    """Detect AI agents present in the project directory.

    Returns list of (agent_id, agent_name, role) tuples, deduplicated.
    """
    seen = set()
    detected = []

    for marker, agent_id, name, role in AGENT_SIGNATURES:
        if agent_id in seen:
            continue
        marker_path = project_root / marker
        if marker_path.exists():
            seen.add(agent_id)
            detected.append((agent_id, name, role))

    return detected


def register_defaults(owlscale_dir: Path, project_root: Path) -> List[Tuple[str, str, str]]:
    """Detect agents and register those not already in the roster.

    Returns list of (agent_id, name, role) that were registered.
    """
    detected = detect_agents(project_root)
    roster = load_roster(owlscale_dir)
    registered = []

    for agent_id, name, role in detected:
        if agent_id not in roster:
            try:
                add_agent(owlscale_dir, agent_id, name, role)
                registered.append((agent_id, name, role))
            except AgentError:
                pass

    return registered
