"""History — assemble a complete task event timeline from logs and state timestamps."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

_DURATION_RE = re.compile(r'^(\d+)(m|h|d)$')


def parse_duration(s: str) -> timedelta:
    """Parse a duration string like '30m', '2h', '7d' into a timedelta."""
    m = _DURATION_RE.match(s.strip())
    if not m:
        raise ValueError(f"invalid duration '{s}' — use e.g. 30m, 2h, 7d")
    value, unit = int(m.group(1)), m.group(2)
    if unit == 'm':
        return timedelta(minutes=value)
    if unit == 'h':
        return timedelta(hours=value)
    return timedelta(days=value)


def _parse_timestamp(timestamp: str) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp into a UTC-aware datetime."""
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def filter_log_entries_since(entries: List[str], since: timedelta) -> List[str]:
    """Return only log entries newer than the given relative duration."""
    cutoff = datetime.now(timezone.utc) - since
    filtered: List[str] = []
    for entry in entries:
        parsed = _parse_log_line(entry)
        if not parsed:
            continue
        ts, _, _, _ = parsed
        dt = _parse_timestamp(ts)
        if dt is None or dt < cutoff:
            continue
        filtered.append(entry)
    return filtered


_LOG_RE = re.compile(
    r"^(?P<ts>[^\s]+)\s+(?P<action>[A-Z]+)\s+(?P<task_id>\S+)(?:\s+(?P<extra>.*))?$"
)

_STATE_ACTION_MAP = {
    "created_at": "PACK",
    "dispatched_at": "DISPATCH",
    "returned_at": "RETURN",
    "accepted_at": "ACCEPT",
    "rejected_at": "REJECT",
}


@dataclass
class HistoryEvent:
    """A single event in a task's timeline."""
    timestamp: str
    action: str
    detail: str = ""

    def __lt__(self, other: "HistoryEvent") -> bool:
        return self.timestamp < other.timestamp


@dataclass
class TaskHistory:
    """Complete timeline for one task."""
    task_id: str
    events: List[HistoryEvent] = field(default_factory=list)
    return_preview: Optional[str] = None


def _parse_log_line(line: str) -> Optional[tuple[str, str, str, str]]:
    """Parse a log line.

    Returns (timestamp, action, task_id, extra) or None.
    """
    m = _LOG_RE.match(line.strip())
    if not m:
        return None
    return m.group("ts"), m.group("action").strip(), m.group("task_id").strip(), (m.group("extra") or "").strip()


def _events_from_state(task_id: str, task_state) -> List[HistoryEvent]:
    """Generate HistoryEvent list from TaskState timestamp fields."""
    events = []
    for field_name, action in _STATE_ACTION_MAP.items():
        ts = getattr(task_state, field_name, None)
        if ts:
            events.append(HistoryEvent(timestamp=ts, action=action))
    # Add claimed/in_progress if applicable (no dedicated timestamp, use approximation)
    return events


def _return_preview(owlscale_dir: Path, task_id: str) -> Optional[str]:
    """Return first 3 non-blank lines of return file, or None."""
    return_path = owlscale_dir / "returns" / f"{task_id}.md"
    if not return_path.exists():
        return None
    lines = [l for l in return_path.read_text().splitlines() if l.strip()]
    return "\n".join(lines[:3]) if lines else None


def get_task_history(owlscale_dir: Path, task_id: str) -> TaskHistory:
    """Assemble complete task timeline from log entries and state timestamps.

    Events are sorted oldest-first.
    Raises KeyError if task_id not found in state.
    """
    from owlscale.core import load_state, get_log

    state = load_state(owlscale_dir)
    if task_id not in state.tasks:
        raise KeyError(f"Task '{task_id}' not found")

    task_state = state.tasks[task_id]
    seen_actions: dict[str, bool] = {}

    # Build events from log lines
    log_entries = get_log(owlscale_dir, task_id=task_id)
    log_events: List[HistoryEvent] = []
    for line in log_entries:
        parsed = _parse_log_line(line)
        if not parsed:
            continue
        ts, action, tid, extra = parsed
        if tid != task_id:
            continue
        detail = extra
        log_events.append(HistoryEvent(timestamp=ts, action=action, detail=detail))

    # Fill in any state-timestamp events not present in log
    state_events = _events_from_state(task_id, task_state)
    log_action_set = {e.action for e in log_events}
    for ev in state_events:
        if ev.action not in log_action_set:
            log_events.append(ev)

    # Sort oldest first
    log_events.sort()

    return TaskHistory(
        task_id=task_id,
        events=log_events,
        return_preview=_return_preview(owlscale_dir, task_id),
    )
