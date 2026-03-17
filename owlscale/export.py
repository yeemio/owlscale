"""Training-data export helpers for owlscale."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from owlscale.core import get_log, load_state
from owlscale.models import Packet, TaskStatus


_EXPORTABLE_STATUSES = {
    "accepted": TaskStatus.accepted,
    "rejected": TaskStatus.rejected,
}


def _normalize_status_filter(status_filter: Optional[str]) -> Optional[set[str]]:
    if status_filter in (None, "all"):
        return None
    if status_filter not in _EXPORTABLE_STATUSES:
        raise ValueError("status_filter must be one of: accepted, rejected, all")
    return {status_filter}


def _load_context_packet(packet_path: Path) -> dict:
    if not packet_path.exists():
        return {"goal": None, "body": None}

    packet = Packet.from_markdown(packet_path.read_text())
    return {
        "goal": packet.frontmatter.goal,
        "body": packet.body,
    }


def _load_return_packet(return_path: Path) -> dict:
    if not return_path.exists():
        return {"body": None}

    content = return_path.read_text()
    if content.startswith("---"):
        try:
            return {"body": Packet.from_markdown(content).body}
        except ValueError:
            pass
    return {"body": content}


def _calculate_duration_hours(dispatched_at: Optional[str], returned_at: Optional[str]) -> Optional[float]:
    if not dispatched_at or not returned_at:
        return None

    dispatched = datetime.fromisoformat(dispatched_at)
    returned = datetime.fromisoformat(returned_at)
    return (returned - dispatched).total_seconds() / 3600


def _build_lifecycle(task_state, outcome: str) -> dict:
    lifecycle = {
        "created_at": task_state.created_at,
        "dispatched_at": task_state.dispatched_at,
        "returned_at": task_state.returned_at,
    }

    terminal_key = f"{outcome}_at"
    lifecycle[terminal_key] = getattr(task_state, terminal_key)
    return lifecycle


def export_training_data(
    owlscale_dir: Path,
    output_path: Path = None,
    status_filter: str = None,
) -> list[dict]:
    """Export accepted/rejected task cycles as JSONL-ready records."""
    allowed_outcomes = _normalize_status_filter(status_filter)
    state = load_state(owlscale_dir)

    records = []
    for task_id in sorted(state.tasks):
        task_state = state.tasks[task_id]
        outcome = task_state.status.value

        if outcome not in _EXPORTABLE_STATUSES:
            continue
        if allowed_outcomes is not None and outcome not in allowed_outcomes:
            continue

        records.append(
            {
                "task_id": task_id,
                "outcome": outcome,
                "context_packet": _load_context_packet(owlscale_dir / "packets" / f"{task_id}.md"),
                "return_packet": _load_return_packet(owlscale_dir / "returns" / f"{task_id}.md"),
                "routing": {
                    "assignee": task_state.assignee,
                    "dispatched_at": task_state.dispatched_at,
                    "returned_at": task_state.returned_at,
                    "duration_hours": _calculate_duration_hours(
                        task_state.dispatched_at,
                        task_state.returned_at,
                    ),
                },
                "lifecycle": _build_lifecycle(task_state, outcome),
                "log_events": get_log(owlscale_dir, task_id=task_id),
            }
        )

    if output_path is not None:
        output_lines = [json.dumps(record, ensure_ascii=False) for record in records]
        Path(output_path).write_text("\n".join(output_lines) + ("\n" if output_lines else ""))

    return records
