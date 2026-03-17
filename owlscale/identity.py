"""
owlscale.identity — Agent context file generation and auto-refresh.

Each registered agent gets a persistent `.owlscale/agents/<agent-id>.md` that
tells the agent who it is, what tasks are pending, and how to work.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

AGENTS_DIR = "agents"
PENDING_STATUSES = {"draft", "ready", "dispatched", "in_progress", "returned"}


def _load_roster(owlscale_dir: Path) -> Dict[str, dict]:
    roster_path = owlscale_dir / "roster.json"
    if not roster_path.exists():
        return {}
    data = json.loads(roster_path.read_text(encoding="utf-8"))
    return data.get("agents", {})


def _load_state(owlscale_dir: Path) -> Dict[str, dict]:
    state_path = owlscale_dir / "state.json"
    if not state_path.exists():
        return {}
    data = json.loads(state_path.read_text(encoding="utf-8"))
    return data.get("tasks", {})


def _packet_path(owlscale_dir: Path, task_id: str) -> str:
    p = owlscale_dir / "packets" / f"{task_id}.md"
    rel = p.relative_to(owlscale_dir.parent) if p.is_absolute() else p
    return f".owlscale/packets/{task_id}.md"


def generate_agent_context(owlscale_dir: Path, agent_id: str) -> str:
    """Generate markdown context string for an agent. Returns the content."""
    roster = _load_roster(owlscale_dir)
    tasks = _load_state(owlscale_dir)

    agent_data = roster.get(agent_id, {})
    name = agent_data.get("name", agent_id)
    role = agent_data.get("role", "executor")
    project_path = str(owlscale_dir.parent.resolve())
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    # Collect pending tasks for this agent
    pending = [
        (tid, tdata)
        for tid, tdata in tasks.items()
        if tdata.get("assignee") == agent_id and tdata.get("status") in PENDING_STATUSES
    ]

    if pending:
        rows = "\n".join(
            f"| {tid} | {tdata.get('goal', '—')} | {tdata.get('status', '—')} "
            f"| {_packet_path(owlscale_dir, tid)} |"
            for tid, tdata in pending
        )
        tasks_section = (
            "| task-id | goal | 状态 | packet |\n"
            "|---------|------|------|--------|\n"
            f"{rows}"
        )
    else:
        tasks_section = "暂无任务。"

    role_desc = {
        "coordinator": "你的工作是分解任务、分发 Context Packet、审核 Return Packet。",
        "executor": "你的工作是按照 Context Packet 实现代码，完成后写 Return Packet 并运行 `owlscale return`。",
        "hub": "你的工作是路由和协调 agent 间的任务流转。",
    }.get(role, "你的工作是处理分配给你的任务。")

    constraints_section = "\n".join([
        f"- 只处理分配给 {agent_id} 的任务",
        "- 不修改 .owlscale/state.json 和 roster.json",
        "- Return Packet 必须填写完整才能 return",
        "- Scope 外的问题写入 Remaining Risks，不擅自扩展",
    ])

    return f"""# owlscale Agent: {agent_id}

**Project path**: {project_path}
**Role**: {role}
**Updated**: {now}

## 你是谁

你是 {agent_id}（{role}）。
{role_desc}

## 待处理任务

{tasks_section}

## 工作流程

1. `owlscale claim <task-id>` — 声明开始
2. 读取 `.owlscale/packets/<task-id>.md`
3. 完成工作，写 `.owlscale/returns/<task-id>.md`
4. `owlscale return <task-id>` — 提交

## 约束

{constraints_section}
"""


def refresh_agent_context(owlscale_dir: Path, agent_id: str) -> Path:
    """Write/overwrite .owlscale/agents/<agent-id>.md. Returns the path."""
    agents_dir = owlscale_dir / AGENTS_DIR
    agents_dir.mkdir(parents=True, exist_ok=True)
    context_path = agents_dir / f"{agent_id}.md"
    content = generate_agent_context(owlscale_dir, agent_id)
    context_path.write_text(content, encoding="utf-8")
    return context_path


def refresh_all_contexts(owlscale_dir: Path) -> None:
    """Refresh context files for all agents in roster."""
    roster = _load_roster(owlscale_dir)
    for agent_id in roster:
        refresh_agent_context(owlscale_dir, agent_id)


def get_agent_context(owlscale_dir: Path, agent_id: str) -> str:
    """Read and return the current context file for an agent. Returns '' if missing."""
    context_path = owlscale_dir / AGENTS_DIR / f"{agent_id}.md"
    if not context_path.exists():
        return ""
    return context_path.read_text(encoding="utf-8")
