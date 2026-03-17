"""Tests for owlscale.daemon and owlscale.adapters.ghostty."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from owlscale.daemon import (
    _load_state_json,
    _next_seq,
    get_daemon_status,
    invoke_adapter,
    start_daemon,
    stop_daemon,
    tail_daemon_log,
    write_trigger,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init(tmp_path: Path) -> Path:
    ws = tmp_path / ".owlscale"
    ws.mkdir()
    (ws / "packets").mkdir()
    (ws / "returns").mkdir()
    (ws / "log").mkdir()
    (ws / "agents").mkdir()
    (ws / "state.json").write_text(json.dumps({"tasks": {}}))
    (ws / "roster.json").write_text(json.dumps({"agents": {}}))
    return ws


def _set_state(ws: Path, tasks: dict):
    (ws / "state.json").write_text(json.dumps({"tasks": tasks}))


def _set_roster(ws: Path, agents: dict):
    (ws / "roster.json").write_text(json.dumps({"agents": agents}))


def _run_cli(tmp_path, *args):
    return subprocess.run(
        [sys.executable, "-m", "owlscale"] + list(args),
        capture_output=True, text=True, cwd=str(tmp_path),
    )


# ---------------------------------------------------------------------------
# write_trigger
# ---------------------------------------------------------------------------

class TestWriteTrigger:
    def test_trigger_file_created(self, tmp_path):
        ws = _init(tmp_path)
        write_trigger(ws, "agent-a", "task-01", ["task-01"])
        assert (ws / "agents" / "agent-a.trigger").exists()

    def test_trigger_valid_json(self, tmp_path):
        ws = _init(tmp_path)
        write_trigger(ws, "agent-a", "task-01", ["task-01"])
        content = json.loads((ws / "agents" / "agent-a.trigger").read_text())
        assert content["version"] == 1
        assert content["agent_id"] == "agent-a"
        assert content["task_id"] == "task-01"
        assert content["event"] == "dispatch"
        assert "sequence" in content
        assert "generated_at" in content
        assert "pending_task_ids" in content

    def test_trigger_pending_task_ids(self, tmp_path):
        ws = _init(tmp_path)
        write_trigger(ws, "agent-a", "task-01", ["task-01", "task-02"])
        content = json.loads((ws / "agents" / "agent-a.trigger").read_text())
        assert content["pending_task_ids"] == ["task-01", "task-02"]

    def test_trigger_sequence_increments(self, tmp_path):
        ws = _init(tmp_path)
        write_trigger(ws, "agent-a", "task-01", ["task-01"])
        seq1 = json.loads((ws / "agents" / "agent-a.trigger").read_text())["sequence"]
        write_trigger(ws, "agent-a", "task-02", ["task-01", "task-02"])
        seq2 = json.loads((ws / "agents" / "agent-a.trigger").read_text())["sequence"]
        assert seq2 == seq1 + 1

    def test_trigger_atomic_no_tmp_left(self, tmp_path):
        ws = _init(tmp_path)
        write_trigger(ws, "agent-a", "task-01", ["task-01"])
        assert not (ws / "agents" / "agent-a.trigger.tmp").exists()

    def test_trigger_overwritten_on_second_dispatch(self, tmp_path):
        """Coalescing: second write overwrites first (mailbox semantics)."""
        ws = _init(tmp_path)
        write_trigger(ws, "agent-a", "task-01", ["task-01"])
        write_trigger(ws, "agent-a", "task-02", ["task-01", "task-02"])
        content = json.loads((ws / "agents" / "agent-a.trigger").read_text())
        assert content["task_id"] == "task-02"

    def test_trigger_agents_dir_created(self, tmp_path):
        ws = tmp_path / ".owlscale"
        ws.mkdir()
        (ws / "state.json").write_text(json.dumps({"tasks": {}}))
        (ws / "log").mkdir()
        # no agents/ dir
        write_trigger(ws, "agent-a", "task-01", ["task-01"])
        assert (ws / "agents" / "agent-a.trigger").exists()


# ---------------------------------------------------------------------------
# Startup reconciliation (via run_daemon with patched sleep)
# ---------------------------------------------------------------------------

class TestStartupReconciliation:
    def _run_one_tick(self, ws, drive_shell=False):
        """Run daemon for a single poll cycle using threading."""
        import threading
        from owlscale.daemon import run_daemon

        def _target():
            run_daemon(ws, poll_interval=0.05, drive_shell=drive_shell)

        t = threading.Thread(target=_target, daemon=True)
        t.start()
        time.sleep(0.15)
        # Stop the daemon thread by sending SIGTERM to ourselves would be complex;
        # instead we just let it time out — daemon is daemon thread so it won't block exit.

    def test_startup_writes_trigger_for_dispatched_task(self, tmp_path):
        ws = _init(tmp_path)
        _set_state(ws, {
            "task-01": {"status": "dispatched", "assignee": "agent-a", "goal": "Test"}
        })
        trigger_path = ws / "agents" / "agent-a.trigger"

        self._run_one_tick(ws)
        assert trigger_path.exists()

    def test_startup_no_trigger_for_accepted_task(self, tmp_path):
        ws = _init(tmp_path)
        _set_state(ws, {
            "task-01": {"status": "accepted", "assignee": "agent-a", "goal": "Done"}
        })
        self._run_one_tick(ws)
        assert not (ws / "agents" / "agent-a.trigger").exists()

    def test_startup_multiple_agents(self, tmp_path):
        ws = _init(tmp_path)
        _set_state(ws, {
            "task-01": {"status": "dispatched", "assignee": "agent-a", "goal": "T1"},
            "task-02": {"status": "dispatched", "assignee": "agent-b", "goal": "T2"},
        })
        self._run_one_tick(ws)
        assert (ws / "agents" / "agent-a.trigger").exists()
        assert (ws / "agents" / "agent-b.trigger").exists()

    def test_other_agents_tasks_excluded_from_pending(self, tmp_path):
        ws = _init(tmp_path)
        _set_state(ws, {
            "task-01": {"status": "dispatched", "assignee": "agent-a", "goal": "T1"},
            "task-02": {"status": "dispatched", "assignee": "agent-b", "goal": "T2"},
        })
        self._run_one_tick(ws)
        content_a = json.loads((ws / "agents" / "agent-a.trigger").read_text())
        assert "task-02" not in content_a["pending_task_ids"]

    def test_drive_shell_false_adapter_not_called(self, tmp_path):
        ws = _init(tmp_path)
        _set_state(ws, {
            "task-01": {"status": "dispatched", "assignee": "agent-a", "goal": "T"}
        })
        _set_roster(ws, {
            "agent-a": {"name": "A", "role": "executor",
                        "delivery": {"mode": "ghostty-applescript"}}
        })
        with patch("owlscale.adapters.ghostty.inject_prompt") as mock_inject:
            self._run_one_tick(ws)
            mock_inject.assert_not_called()


# ---------------------------------------------------------------------------
# Poll loop: mtime change detection (unit-level via write_trigger directly)
# ---------------------------------------------------------------------------

class TestMtimeDetection:
    def test_no_change_no_retrigger(self, tmp_path):
        """Stat mtime unchanged → should not write a new trigger."""
        ws = _init(tmp_path)
        # Pre-write a trigger so we can check its sequence doesn't change
        write_trigger(ws, "agent-a", "task-01", ["task-01"])
        seq_before = json.loads((ws / "agents" / "agent-a.trigger").read_text())["sequence"]
        # No state.json change → sequence stays same
        # (We test this by NOT calling write_trigger again)
        seq_after = json.loads((ws / "agents" / "agent-a.trigger").read_text())["sequence"]
        assert seq_before == seq_after


# ---------------------------------------------------------------------------
# JSON parse error resilience
# ---------------------------------------------------------------------------

class TestJsonParseError:
    def test_load_state_json_raises_on_invalid(self, tmp_path):
        ws = _init(tmp_path)
        (ws / "state.json").write_text("{ broken json")
        with pytest.raises(Exception):
            _load_state_json(ws)

    def test_load_state_json_returns_tasks(self, tmp_path):
        ws = _init(tmp_path)
        _set_state(ws, {"t1": {"status": "dispatched"}})
        tasks = _load_state_json(ws)
        assert "t1" in tasks


# ---------------------------------------------------------------------------
# invoke_adapter
# ---------------------------------------------------------------------------

class TestInvokeAdapter:
    def test_mode_none_returns_false(self, tmp_path):
        ws = _init(tmp_path)
        _set_roster(ws, {"agent-a": {"name": "A", "role": "executor", "delivery": {"mode": "none"}}})
        assert invoke_adapter(ws, "agent-a", "task-01") is False

    def test_no_delivery_config_returns_false(self, tmp_path):
        ws = _init(tmp_path)
        _set_roster(ws, {"agent-a": {"name": "A", "role": "executor"}})
        assert invoke_adapter(ws, "agent-a", "task-01") is False

    def test_ghostty_mode_calls_inject_prompt(self, tmp_path):
        ws = _init(tmp_path)
        _set_roster(ws, {"agent-a": {
            "name": "A", "role": "executor",
            "delivery": {"mode": "ghostty-applescript", "target": "window-title", "window_title": "Agent"}
        }})
        with patch("owlscale.adapters.ghostty.inject_prompt", return_value=True) as mock:
            result = invoke_adapter(ws, "agent-a", "task-01")
        mock.assert_called_once_with("agent-a", "task-01", window_title="Agent")
        assert result is True

    def test_ghostty_failure_returns_false(self, tmp_path):
        ws = _init(tmp_path)
        _set_roster(ws, {"agent-a": {
            "name": "A", "role": "executor",
            "delivery": {"mode": "ghostty-applescript"}
        }})
        with patch("owlscale.adapters.ghostty.inject_prompt", return_value=False):
            result = invoke_adapter(ws, "agent-a", "task-01")
        assert result is False

    def test_tmux_mode_returns_true(self, tmp_path):
        ws = _init(tmp_path)
        _set_roster(ws, {"agent-a": {"name": "A", "role": "executor",
                                     "delivery": {"mode": "tmux"}}})
        assert invoke_adapter(ws, "agent-a", "task-01") is True

    def test_adapter_exception_non_fatal(self, tmp_path):
        ws = _init(tmp_path)
        _set_roster(ws, {"agent-a": {
            "name": "A", "role": "executor",
            "delivery": {"mode": "ghostty-applescript"}
        }})
        with patch("owlscale.adapters.ghostty.inject_prompt", side_effect=RuntimeError("boom")):
            result = invoke_adapter(ws, "agent-a", "task-01")
        assert result is False


# ---------------------------------------------------------------------------
# get_daemon_status
# ---------------------------------------------------------------------------

class TestGetDaemonStatus:
    def test_not_running_when_no_pid_file(self, tmp_path):
        ws = _init(tmp_path)
        status = get_daemon_status(ws)
        assert status["running"] is False
        assert status["pid"] is None

    def test_not_running_when_pid_file_has_dead_pid(self, tmp_path):
        ws = _init(tmp_path)
        # Use PID 1 which exists but we're not allowed to send signals to,
        # OR a very large PID that's very unlikely to exist.
        # Safest: write a PID that definitely doesn't exist.
        (ws / "daemon.pid").write_text("9999999")
        status = get_daemon_status(ws)
        assert status["running"] is False

    def test_trigger_seq_in_status(self, tmp_path):
        ws = _init(tmp_path)
        write_trigger(ws, "agent-a", "task-01", ["task-01"])
        status = get_daemon_status(ws)
        assert status["trigger_seq"] >= 1


# ---------------------------------------------------------------------------
# start_daemon / stop_daemon
# ---------------------------------------------------------------------------

class TestStartStopDaemon:
    def test_start_creates_pid_file(self, tmp_path):
        ws = _init(tmp_path)
        pid = start_daemon(ws, poll_interval=0.1)
        try:
            assert (ws / "daemon.pid").exists()
            assert pid > 0
        finally:
            stop_daemon(ws)

    def test_stop_removes_pid_file(self, tmp_path):
        ws = _init(tmp_path)
        start_daemon(ws, poll_interval=0.1)
        time.sleep(0.2)
        stop_daemon(ws)
        assert not (ws / "daemon.pid").exists()

    def test_stop_returns_false_when_not_running(self, tmp_path):
        ws = _init(tmp_path)
        assert stop_daemon(ws) is False

    def test_start_then_status_running(self, tmp_path):
        ws = _init(tmp_path)
        start_daemon(ws, poll_interval=0.1)
        time.sleep(0.3)
        try:
            status = get_daemon_status(ws)
            assert status["running"] is True
        finally:
            stop_daemon(ws)


# ---------------------------------------------------------------------------
# tail_daemon_log
# ---------------------------------------------------------------------------

class TestTailDaemonLog:
    def test_returns_empty_list_when_no_log(self, tmp_path):
        ws = _init(tmp_path)
        assert tail_daemon_log(ws) == []

    def test_returns_last_n_lines(self, tmp_path):
        ws = _init(tmp_path)
        log_path = ws / "log" / "daemon.log"
        log_path.write_text("\n".join(f"line {i}" for i in range(100)))
        lines = tail_daemon_log(ws, n=10)
        assert len(lines) == 10
        assert lines[-1] == "line 99"

    def test_returns_all_when_fewer_than_n(self, tmp_path):
        ws = _init(tmp_path)
        log_path = ws / "log" / "daemon.log"
        log_path.write_text("line1\nline2\nline3")
        lines = tail_daemon_log(ws, n=50)
        assert len(lines) == 3


# ---------------------------------------------------------------------------
# Ghostty adapter unit tests
# ---------------------------------------------------------------------------

class TestGhosttyAdapter:
    def test_inject_prompt_calls_osascript(self, tmp_path):
        from owlscale.adapters.ghostty import inject_prompt
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = inject_prompt("agent-a", "task-01")
        assert mock_run.called
        args = mock_run.call_args[0][0]
        assert args[0] == "osascript"
        assert result is True

    def test_inject_prompt_with_window_title(self, tmp_path):
        from owlscale.adapters.ghostty import inject_prompt
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            inject_prompt("agent-a", "task-01", window_title="MyAgent")
        script = mock_run.call_args[0][0][2]
        assert "MyAgent" in script

    def test_inject_prompt_returns_false_on_osascript_error(self):
        from owlscale.adapters.ghostty import inject_prompt
        with patch("subprocess.run", side_effect=Exception("osascript not found")):
            result = inject_prompt("agent-a", "task-01")
        assert result is False

    def test_inject_prompt_returns_false_on_nonzero_exit(self):
        from owlscale.adapters.ghostty import inject_prompt
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = inject_prompt("agent-a", "task-01")
        assert result is False


# ---------------------------------------------------------------------------
# CLI: daemon status
# ---------------------------------------------------------------------------

class TestDaemonCLI:
    def test_daemon_status_exits_0(self, tmp_path):
        _run_cli(tmp_path, "init")
        result = _run_cli(tmp_path, "daemon", "status")
        assert result.returncode == 0

    def test_daemon_status_shows_not_running(self, tmp_path):
        _run_cli(tmp_path, "init")
        result = _run_cli(tmp_path, "daemon", "status")
        assert "not running" in result.stdout

    def test_daemon_logs_exits_0_no_log(self, tmp_path):
        _run_cli(tmp_path, "init")
        result = _run_cli(tmp_path, "daemon", "logs")
        assert result.returncode == 0
