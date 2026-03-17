"""Tests for owlscale stats command."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
CLI_ENV = {**os.environ, "PYTHONPATH": PROJECT_ROOT}

from owlscale.core import (
    init_project, add_agent, pack_task, dispatch_task,
    claim_task, return_task, accept_task, reject_task,
    load_state, save_state,
)
from owlscale.models import TaskStatus
from owlscale.stats import compute_stats, AgentStats, SystemStats


@pytest.fixture()
def workspace(tmp_path):
    return init_project(tmp_path)


@pytest.fixture()
def workspace_with_history(workspace):
    """Workspace with realistic task history across multiple agents."""
    add_agent(workspace, "alpha", "Alpha Bot", "executor")
    add_agent(workspace, "beta", "Beta Bot", "executor")
    add_agent(workspace, "idle", "Idle Bot", "executor")

    # Alpha: 2 accepted, 1 rejected
    for i in range(3):
        tid = f"a-{i}"
        pack_task(workspace, tid, f"Alpha task {i}")
        dispatch_task(workspace, tid, "alpha")
        (workspace / "returns" / f"{tid}.md").write_text(f"# Done {i}")
        return_task(workspace, tid)

    accept_task(workspace, "a-0")
    accept_task(workspace, "a-1")
    reject_task(workspace, "a-2", reason="needs fixes")

    # Beta: 1 accepted, in_progress on another
    pack_task(workspace, "b-0", "Beta task 0")
    dispatch_task(workspace, "b-0", "beta")
    (workspace / "returns" / "b-0.md").write_text("# Done")
    return_task(workspace, "b-0")
    accept_task(workspace, "b-0")

    pack_task(workspace, "b-1", "Beta task 1")
    dispatch_task(workspace, "b-1", "beta")
    claim_task(workspace, "b-1")

    # idle: no tasks
    return workspace


class TestComputeStats:
    def test_total_tasks(self, workspace_with_history):
        stats = compute_stats(workspace_with_history)
        assert stats.total_tasks == 5

    def test_by_status(self, workspace_with_history):
        stats = compute_stats(workspace_with_history)
        assert stats.by_status["accepted"] == 3
        assert stats.by_status["rejected"] == 1
        assert stats.by_status["in_progress"] == 1

    def test_alpha_pass_rate(self, workspace_with_history):
        stats = compute_stats(workspace_with_history)
        alpha = stats.agents["alpha"]
        assert alpha.total_tasks == 3
        assert alpha.accepted == 2
        assert alpha.rejected == 1
        assert alpha.pass_rate == pytest.approx(2 / 3)
        assert alpha.rework_rate == pytest.approx(1 / 3)

    def test_beta_stats(self, workspace_with_history):
        stats = compute_stats(workspace_with_history)
        beta = stats.agents["beta"]
        assert beta.total_tasks == 2
        assert beta.accepted == 1
        assert beta.in_progress == 1
        assert beta.pass_rate == 1.0

    def test_idle_agent_included(self, workspace_with_history):
        stats = compute_stats(workspace_with_history)
        assert "idle" in stats.agents
        idle = stats.agents["idle"]
        assert idle.total_tasks == 0
        assert idle.pass_rate is None

    def test_empty_workspace(self, workspace):
        stats = compute_stats(workspace)
        assert stats.total_tasks == 0
        assert stats.by_status == {}

    def test_to_dict_roundtrip(self, workspace_with_history):
        stats = compute_stats(workspace_with_history)
        d = stats.to_dict()
        assert d["total_tasks"] == 5
        assert "alpha" in d["agents"]
        assert d["agents"]["alpha"]["pass_rate"] == pytest.approx(2 / 3)

    def test_duration_computed_from_timestamps(self, workspace):
        """Duration is computed from dispatched_at to accepted_at."""
        add_agent(workspace, "dur-bot", "Bot", "executor")
        pack_task(workspace, "dur-1", "Duration test")
        dispatch_task(workspace, "dur-1", "dur-bot")

        # Manually set timestamps for deterministic test
        state = load_state(workspace)
        state.tasks["dur-1"].dispatched_at = "2026-01-01T00:00:00+00:00"
        state.tasks["dur-1"].accepted_at = "2026-01-01T02:30:00+00:00"
        state.tasks["dur-1"].status = TaskStatus.accepted
        save_state(workspace, state)

        stats = compute_stats(workspace)
        agent = stats.agents["dur-bot"]
        assert agent.avg_duration_hours == pytest.approx(2.5)


class TestStatsCLI:
    def test_cli_stats_human(self, tmp_path):
        ws = init_project(tmp_path)
        add_agent(ws, "bot", "Bot", "executor")
        pack_task(ws, "t1", "Task")
        dispatch_task(ws, "t1", "bot")
        (ws / "returns" / "t1.md").write_text("# Done")
        return_task(ws, "t1")
        accept_task(ws, "t1")

        result = subprocess.run(
            [sys.executable, "-m", "owlscale", "stats"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "Total tasks: 1" in result.stdout
        assert "bot" in result.stdout
        assert "pass=" in result.stdout

    def test_cli_stats_json(self, tmp_path):
        ws = init_project(tmp_path)
        add_agent(ws, "bot", "Bot", "executor")
        pack_task(ws, "t1", "Task")

        result = subprocess.run(
            [sys.executable, "-m", "owlscale", "stats", "--json"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["total_tasks"] == 1

    def test_cli_stats_empty(self, tmp_path):
        init_project(tmp_path)
        result = subprocess.run(
            [sys.executable, "-m", "owlscale", "stats"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "Total tasks: 0" in result.stdout
