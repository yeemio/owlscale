"""Task discovery helpers for owlscale agents."""

from __future__ import annotations

import json
import time
from pathlib import Path

from owlscale.core import load_state
from owlscale.models import Packet, TaskStatus


def _load_state_with_retry(owlscale_dir: Path):
    try:
        return load_state(owlscale_dir)
    except json.JSONDecodeError:
        time.sleep(0.05)
        return load_state(owlscale_dir)


def find_pending_tasks(owlscale_dir: Path, agent_id: str) -> list[tuple[str, Path]]:
    """Return dispatched tasks assigned to the given agent."""
    state = _load_state_with_retry(owlscale_dir)

    pending = []
    for task_id in sorted(state.tasks):
        task_state = state.tasks[task_id]
        if task_state.assignee != agent_id:
            continue
        if task_state.status != TaskStatus.dispatched:
            continue
        pending.append((task_id, owlscale_dir / "packets" / f"{task_id}.md"))
    return pending


def _print_task(packet_path: Path) -> dict:
    packet_markdown = packet_path.read_text() if packet_path.exists() else ""

    goal = ""
    assignee = None
    if packet_markdown:
        try:
            packet = Packet.from_markdown(packet_markdown)
            goal = packet.frontmatter.goal
            assignee = packet.frontmatter.assignee
        except ValueError:
            pass

    task_id = packet_path.stem
    print(f"=== NEW TASK: {task_id} ===")
    print(f"Assigned to: {assignee or ''}")
    print(f"Goal: {goal}")
    print()
    print("--- PACKET START ---")
    if packet_markdown:
        print(packet_markdown, end="" if packet_markdown.endswith("\n") else "\n")
    print("--- PACKET END ---")

    return {
        "task_id": task_id,
        "packet_path": packet_path,
        "assignee": assignee,
        "goal": goal,
        "packet_markdown": packet_markdown,
    }


def watch_once(owlscale_dir: Path, agent_id: str) -> list[dict]:
    """Check once, print any newly assigned dispatched tasks, and return them."""
    pending = find_pending_tasks(owlscale_dir, agent_id)
    found = []
    for _, packet_path in pending:
        found.append(_print_task(packet_path))
    return found


def watch_poll(owlscale_dir: Path, agent_id: str, interval: int = 30):
    """Continuously poll for new dispatched tasks without duplicate prints."""
    seen_task_ids: set[str] = set()

    try:
        while True:
            for task_id, packet_path in find_pending_tasks(owlscale_dir, agent_id):
                if task_id in seen_task_ids:
                    continue
                _print_task(packet_path)
                seen_task_ids.add(task_id)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped watching.")
