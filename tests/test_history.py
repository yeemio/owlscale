"""Tests for owlscale history module."""

import json
import sys
import os
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
CLI_ENV = {**os.environ, "PYTHONPATH": PROJECT_ROOT}

from owlscale.history import (
    filter_log_entries_since, get_task_history, HistoryEvent, TaskHistory, _parse_log_line,
    _events_from_state, parse_duration
)
from owlscale.core import (
    init_project, pack_task, dispatch_task, add_agent,
    claim_task, return_task, accept_task, reject_task,
)
from datetime import datetime, timedelta, timezone


def init_ws(tmp_path: Path) -> Path:
    return init_project(tmp_path)


def _run(tmp_path, *args):
    return subprocess.run(
        [sys.executable, "-m", "owlscale"] + list(args),
        capture_output=True, text=True, env=CLI_ENV, cwd=tmp_path,
    )


# ---------------------------------------------------------------------------
# TestParseLogLine
# ---------------------------------------------------------------------------

class TestParseLogLine:
    def test_pack_line(self):
        line = "2024-01-01T00:00:00Z PACK   task-1"
        result = _parse_log_line(line)
        assert result is not None
        ts, action, task_id, extra = result
        assert action == "PACK"
        assert task_id == "task-1"

    def test_dispatch_line_with_extra(self):
        line = "2024-01-01T00:01:00Z DISPATCH task-1  to=agent-a"
        result = _parse_log_line(line)
        assert result is not None
        ts, action, task_id, extra = result
        assert action == "DISPATCH"
        assert task_id == "task-1"
        assert "agent-a" in extra

    def test_invalid_line_returns_none(self):
        assert _parse_log_line("") is None
        assert _parse_log_line("not a log line") is None

    def test_accept_line(self):
        line = "2024-01-01T00:05:00Z ACCEPT  task-1"
        result = _parse_log_line(line)
        assert result is not None
        _, action, tid, _ = result
        assert action == "ACCEPT"
        assert tid == "task-1"


class TestParseDuration:
    def test_minutes(self):
        assert parse_duration("30m") == timedelta(minutes=30)

    def test_invalid(self):
        with pytest.raises(ValueError):
            parse_duration("yesterday")


class TestFilterLogEntriesSince:
    def test_filters_to_recent_entries(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        entries = [
            f"{(now - timedelta(hours=2)).isoformat()} PACK t1",
            f"{(now - timedelta(minutes=10)).isoformat()} RETURN t1",
        ]
        filtered = filter_log_entries_since(entries, timedelta(minutes=30))
        assert filtered == [entries[1]]


# ---------------------------------------------------------------------------
# TestHistoryEvent
# ---------------------------------------------------------------------------

class TestHistoryEvent:
    def test_ordering(self):
        e1 = HistoryEvent(timestamp="2024-01-01T00:00:00Z", action="PACK")
        e2 = HistoryEvent(timestamp="2024-01-02T00:00:00Z", action="DISPATCH")
        assert e1 < e2


# ---------------------------------------------------------------------------
# TestGetTaskHistory
# ---------------------------------------------------------------------------

class TestGetTaskHistory:
    def test_missing_task_raises(self, tmp_path):
        ws = init_ws(tmp_path)
        with pytest.raises(KeyError, match="t1"):
            get_task_history(ws, "t1")

    def test_returns_task_history(self, tmp_path):
        ws = init_ws(tmp_path)
        pack_task(ws, "t1", "Do something")
        result = get_task_history(ws, "t1")
        assert isinstance(result, TaskHistory)
        assert result.task_id == "t1"

    def test_has_pack_event(self, tmp_path):
        ws = init_ws(tmp_path)
        pack_task(ws, "t1", "Do something")
        history = get_task_history(ws, "t1")
        actions = [e.action for e in history.events]
        assert "PACK" in actions

    def test_events_sorted_oldest_first(self, tmp_path):
        ws = init_ws(tmp_path)
        add_agent(ws, "agent-a", "Agent A", "executor")
        pack_task(ws, "t1", "Do something")
        dispatch_task(ws, "t1", "agent-a")
        history = get_task_history(ws, "t1")
        timestamps = [e.timestamp for e in history.events]
        assert timestamps == sorted(timestamps)

    def test_dispatch_event_present(self, tmp_path):
        ws = init_ws(tmp_path)
        add_agent(ws, "agent-a", "Agent A", "executor")
        pack_task(ws, "t1", "Do something")
        dispatch_task(ws, "t1", "agent-a")
        history = get_task_history(ws, "t1")
        actions = [e.action for e in history.events]
        assert "DISPATCH" in actions

    def test_accept_event_present(self, tmp_path):
        ws = init_ws(tmp_path)
        add_agent(ws, "agent-a", "Agent A", "executor")
        pack_task(ws, "t1", "Do something")
        dispatch_task(ws, "t1", "agent-a")
        claim_task(ws, "t1")
        return_path = ws / "returns" / "t1.md"
        return_path.write_text("# Return\n\nDone.")
        return_task(ws, "t1")
        accept_task(ws, "t1")
        history = get_task_history(ws, "t1")
        actions = [e.action for e in history.events]
        assert "ACCEPT" in actions

    def test_return_preview_present(self, tmp_path):
        ws = init_ws(tmp_path)
        add_agent(ws, "agent-a", "Agent A", "executor")
        pack_task(ws, "t1", "Do something")
        dispatch_task(ws, "t1", "agent-a")
        claim_task(ws, "t1")
        return_path = ws / "returns" / "t1.md"
        return_path.write_text("# Return\n\nImplemented feature X.\n\nDetails here.")
        return_task(ws, "t1")
        history = get_task_history(ws, "t1")
        assert history.return_preview is not None
        assert "Return" in history.return_preview

    def test_no_return_file_gives_none(self, tmp_path):
        ws = init_ws(tmp_path)
        pack_task(ws, "t1", "Something")
        history = get_task_history(ws, "t1")
        assert history.return_preview is None

    def test_events_contain_dispatch_detail(self, tmp_path):
        ws = init_ws(tmp_path)
        add_agent(ws, "agent-a", "Agent A", "executor")
        pack_task(ws, "t1", "Do something")
        dispatch_task(ws, "t1", "agent-a")
        history = get_task_history(ws, "t1")
        dispatch_event = next((e for e in history.events if e.action == "DISPATCH"), None)
        assert dispatch_event is not None

    def test_return_preview_first_three_lines(self, tmp_path):
        ws = init_ws(tmp_path)
        add_agent(ws, "agent-a", "Agent A", "executor")
        pack_task(ws, "t1", "Do something")
        dispatch_task(ws, "t1", "agent-a")
        claim_task(ws, "t1")
        return_path = ws / "returns" / "t1.md"
        lines = ["Line 1", "Line 2", "Line 3", "Line 4", "Line 5"]
        return_path.write_text("\n".join(lines))
        return_task(ws, "t1")
        history = get_task_history(ws, "t1")
        preview_lines = history.return_preview.splitlines()
        assert len(preview_lines) <= 3


# ---------------------------------------------------------------------------
# TestHistoryCli
# ---------------------------------------------------------------------------

class TestHistoryCli:
    def test_history_output(self, tmp_path):
        ws = init_ws(tmp_path)
        pack_task(ws, "t1", "Do something")
        result = _run(tmp_path, "history", "t1")
        assert result.returncode == 0
        assert "t1" in result.stdout
        assert "PACK" in result.stdout

    def test_history_json(self, tmp_path):
        ws = init_ws(tmp_path)
        pack_task(ws, "t1", "Do something")
        result = _run(tmp_path, "history", "t1", "--json")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["task_id"] == "t1"
        assert "events" in data

    def test_missing_task_fails(self, tmp_path):
        init_ws(tmp_path)
        result = _run(tmp_path, "history", "nonexistent")
        assert result.returncode != 0

    def test_log_since_filters_entries(self, tmp_path):
        ws = init_ws(tmp_path)
        pack_task(ws, "t1", "Do something")
        result = _run(tmp_path, "log", "--task", "t1", "--since", "7d")
        assert result.returncode == 0
        assert "PACK" in result.stdout

    def test_log_since_rejects_invalid_duration(self, tmp_path):
        init_ws(tmp_path)
        result = _run(tmp_path, "log", "--since", "invalid")
        assert result.returncode != 0
        assert "invalid duration" in result.stderr
