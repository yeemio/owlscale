"""Tests for owlscale.identity module."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from owlscale.identity import (
    generate_agent_context,
    get_agent_context,
    refresh_agent_context,
    refresh_all_contexts,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init(tmp_path: Path):
    """Create minimal .owlscale/ workspace."""
    ws = tmp_path / ".owlscale"
    ws.mkdir()
    (ws / "packets").mkdir()
    (ws / "returns").mkdir()
    (ws / "log").mkdir()
    (ws / "state.json").write_text(json.dumps({"tasks": {}}), encoding="utf-8")
    (ws / "roster.json").write_text(json.dumps({"agents": {}}), encoding="utf-8")
    return ws


def _add_agent(ws: Path, agent_id: str, name: str, role: str):
    roster_path = ws / "roster.json"
    data = json.loads(roster_path.read_text())
    data["agents"][agent_id] = {"name": name, "role": role}
    roster_path.write_text(json.dumps(data), encoding="utf-8")


def _add_task(ws: Path, task_id: str, assignee: str, status: str, goal: str = ""):
    state_path = ws / "state.json"
    data = json.loads(state_path.read_text())
    data["tasks"][task_id] = {"status": status, "assignee": assignee, "goal": goal}
    state_path.write_text(json.dumps(data), encoding="utf-8")


def _run(tmp_path, *args):
    return subprocess.run(
        [sys.executable, "-m", "owlscale"] + list(args),
        capture_output=True, text=True, cwd=str(tmp_path)
    )


def init_owlscale(tmp_path: Path):
    result = _run(tmp_path, "init")
    assert result.returncode == 0, result.stderr
    return tmp_path / ".owlscale"


# ---------------------------------------------------------------------------
# generate_agent_context
# ---------------------------------------------------------------------------

class TestGenerateAgentContext:
    def test_contains_agent_id(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "copilot-opus", "Copilot", "executor")
        content = generate_agent_context(ws, "copilot-opus")
        assert "copilot-opus" in content

    def test_contains_role(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "cc-opus", "Claude Code", "coordinator")
        content = generate_agent_context(ws, "cc-opus")
        assert "coordinator" in content

    def test_contains_project_path(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "a1", "Agent1", "executor")
        content = generate_agent_context(ws, "a1")
        assert str(tmp_path.resolve()) in content

    def test_contains_updated_timestamp(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "a1", "Agent1", "executor")
        content = generate_agent_context(ws, "a1")
        assert "Updated" in content

    def test_pending_task_appears(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "copilot-opus", "Copilot", "executor")
        _add_task(ws, "task-01", "copilot-opus", "dispatched", "Add auth")
        content = generate_agent_context(ws, "copilot-opus")
        assert "task-01" in content
        assert "Add auth" in content

    def test_no_pending_tasks_shows_message(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "copilot-opus", "Copilot", "executor")
        content = generate_agent_context(ws, "copilot-opus")
        assert "暂无任务" in content

    def test_accepted_task_not_in_pending(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "copilot-opus", "Copilot", "executor")
        _add_task(ws, "task-done", "copilot-opus", "accepted", "Old task")
        content = generate_agent_context(ws, "copilot-opus")
        assert "task-done" not in content

    def test_rejected_task_not_in_pending(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "copilot-opus", "Copilot", "executor")
        _add_task(ws, "task-rej", "copilot-opus", "rejected", "Rejected task")
        content = generate_agent_context(ws, "copilot-opus")
        assert "task-rej" not in content

    def test_other_agents_tasks_excluded(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "agent-a", "A", "executor")
        _add_agent(ws, "agent-b", "B", "executor")
        _add_task(ws, "task-b", "agent-b", "dispatched", "B's task")
        content = generate_agent_context(ws, "agent-a")
        assert "task-b" not in content

    def test_in_progress_task_appears(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "copilot-opus", "Copilot", "executor")
        _add_task(ws, "task-wip", "copilot-opus", "in_progress", "WIP task")
        content = generate_agent_context(ws, "copilot-opus")
        assert "task-wip" in content

    def test_returned_task_appears(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "copilot-opus", "Copilot", "executor")
        _add_task(ws, "task-ret", "copilot-opus", "returned", "Returned task")
        content = generate_agent_context(ws, "copilot-opus")
        assert "task-ret" in content

    def test_contains_workflow_section(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "a1", "Agent1", "executor")
        content = generate_agent_context(ws, "a1")
        assert "工作流程" in content
        assert "owlscale claim" in content

    def test_contains_constraints_section(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "a1", "Agent1", "executor")
        content = generate_agent_context(ws, "a1")
        assert "约束" in content

    def test_unknown_agent_uses_defaults(self, tmp_path):
        ws = _init(tmp_path)
        # Agent not in roster — still generates (gracefully)
        content = generate_agent_context(ws, "unknown-bot")
        assert "unknown-bot" in content

    def test_coordinator_role_description(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "cc-opus", "Claude", "coordinator")
        content = generate_agent_context(ws, "cc-opus")
        assert "coordinator" in content


# ---------------------------------------------------------------------------
# refresh_agent_context
# ---------------------------------------------------------------------------

class TestRefreshAgentContext:
    def test_creates_file(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "copilot-opus", "Copilot", "executor")
        path = refresh_agent_context(ws, "copilot-opus")
        assert path.exists()

    def test_creates_agents_dir_if_missing(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "copilot-opus", "Copilot", "executor")
        agents_dir = ws / "agents"
        assert not agents_dir.exists()
        refresh_agent_context(ws, "copilot-opus")
        assert agents_dir.exists()

    def test_returns_correct_path(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "copilot-opus", "Copilot", "executor")
        path = refresh_agent_context(ws, "copilot-opus")
        assert path == ws / "agents" / "copilot-opus.md"

    def test_overwrites_existing_file(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "copilot-opus", "Copilot", "executor")
        path = refresh_agent_context(ws, "copilot-opus")
        old_content = path.read_text()
        # Add a task and refresh again
        _add_task(ws, "new-task", "copilot-opus", "dispatched", "New work")
        refresh_agent_context(ws, "copilot-opus")
        new_content = path.read_text()
        assert "new-task" in new_content
        assert new_content != old_content

    def test_file_content_is_markdown(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "a1", "Agent1", "executor")
        path = refresh_agent_context(ws, "a1")
        content = path.read_text()
        assert content.startswith("# owlscale Agent:")


# ---------------------------------------------------------------------------
# refresh_all_contexts
# ---------------------------------------------------------------------------

class TestRefreshAllContexts:
    def test_creates_file_for_each_agent(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "agent-a", "A", "executor")
        _add_agent(ws, "agent-b", "B", "coordinator")
        refresh_all_contexts(ws)
        assert (ws / "agents" / "agent-a.md").exists()
        assert (ws / "agents" / "agent-b.md").exists()

    def test_empty_roster_is_noop(self, tmp_path):
        ws = _init(tmp_path)
        # No agents — should not raise
        refresh_all_contexts(ws)

    def test_no_roster_file_is_noop(self, tmp_path):
        ws = _init(tmp_path)
        (ws / "roster.json").unlink()
        # Should not raise
        refresh_all_contexts(ws)


# ---------------------------------------------------------------------------
# get_agent_context
# ---------------------------------------------------------------------------

class TestGetAgentContext:
    def test_returns_content_after_refresh(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "copilot-opus", "Copilot", "executor")
        refresh_agent_context(ws, "copilot-opus")
        content = get_agent_context(ws, "copilot-opus")
        assert "copilot-opus" in content

    def test_returns_empty_string_if_missing(self, tmp_path):
        ws = _init(tmp_path)
        result = get_agent_context(ws, "nobody")
        assert result == ""

    def test_returns_string(self, tmp_path):
        ws = _init(tmp_path)
        _add_agent(ws, "a1", "A", "executor")
        refresh_agent_context(ws, "a1")
        result = get_agent_context(ws, "a1")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# CLI: whoami
# ---------------------------------------------------------------------------

class TestWhoamiCLI:
    def test_whoami_agent_id_prints_context(self, tmp_path):
        ws = init_owlscale(tmp_path)
        result = _run(tmp_path, "roster", "add", "copilot-opus", "--name", "Copilot", "--role", "executor")
        assert result.returncode == 0
        result = _run(tmp_path, "whoami", "copilot-opus")
        assert result.returncode == 0
        assert "copilot-opus" in result.stdout

    def test_whoami_all_refreshes_all_agents(self, tmp_path):
        ws = init_owlscale(tmp_path)
        _run(tmp_path, "roster", "add", "agent-a", "--name", "A", "--role", "executor")
        _run(tmp_path, "roster", "add", "agent-b", "--name", "B", "--role", "coordinator")
        result = _run(tmp_path, "whoami", "--all")
        assert result.returncode == 0
        assert (tmp_path / ".owlscale" / "agents" / "agent-a.md").exists()
        assert (tmp_path / ".owlscale" / "agents" / "agent-b.md").exists()

    def test_whoami_unknown_agent_still_works(self, tmp_path):
        init_owlscale(tmp_path)
        result = _run(tmp_path, "whoami", "nobody")
        assert result.returncode == 0
        assert "nobody" in result.stdout
