"""Prune completed tasks from the owlscale workspace."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

from owlscale.core import load_state, save_state
from owlscale.models import TaskStatus


@dataclass
class PruneResult:
    archived: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    dry_run: bool = False


def _parse_ts(ts: str | None) -> datetime | None:
    """Parse ISO 8601 timestamp to UTC-aware datetime, or None."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _archive_dir(owlscale_dir: Path, completion_ts: datetime) -> Path:
    """Return archive subdirectory for a given completion timestamp."""
    month = completion_ts.strftime("%Y-%m")
    return owlscale_dir / "archive" / month


def prune_workspace(owlscale_dir: Path, days: int = 30, dry_run: bool = False) -> PruneResult:
    """Archive completed tasks older than `days` days.

    Moves packets and return files to .owlscale/archive/YYYY-MM/ and removes
    them from state.json. Log files are never touched.
    """
    result = PruneResult(dry_run=dry_run)
    state = load_state(owlscale_dir)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    to_archive: list[tuple[str, datetime]] = []

    for task_id, task_state in state.tasks.items():
        if task_state.status not in (TaskStatus.accepted, TaskStatus.rejected):
            result.skipped.append(task_id)
            continue

        ts = _parse_ts(task_state.accepted_at) or _parse_ts(task_state.rejected_at)
        if ts is None:
            result.skipped.append(task_id)
            continue

        if ts <= cutoff:
            to_archive.append((task_id, ts))
        else:
            result.skipped.append(task_id)

    for task_id, completion_ts in to_archive:
        dest_dir = _archive_dir(owlscale_dir, completion_ts)

        if not dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)
            # Move packet
            packet = owlscale_dir / "packets" / f"{task_id}.md"
            if packet.exists():
                shutil.move(str(packet), str(dest_dir / packet.name))
            # Move return file (may not exist)
            ret = owlscale_dir / "returns" / f"{task_id}.md"
            if ret.exists():
                shutil.move(str(ret), str(dest_dir / ret.name))
            # Remove from state
            del state.tasks[task_id]

        result.archived.append(task_id)

    if not dry_run and to_archive:
        save_state(owlscale_dir, state)

    return result
