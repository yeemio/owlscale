"""Tests for the owlscale CLI and core logic (S01–S09)."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

# Ensure the project root is always on PYTHONPATH for subprocess calls so that
# `python -m owlscale` works even when the package is not pip-installed.
PROJECT_ROOT = str(Path(__file__).parent.parent)
CLI_ENV = {**os.environ, "PYTHONPATH": PROJECT_ROOT}

from owlscale.core import (
    OwlscaleError,
    AgentError,
    TaskError,
    WorkspaceError,
    accept_task,
    add_agent,
    claim_task,
    dispatch_task,
    get_log,
    get_status,
    get_workspace_root,
    init_project,
    list_agents,
    pack_task,
    reject_task,
    remove_agent,
    return_task,
)
from owlscale.models import AgentRole, GlobalState, Packet, TaskStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(tmp_path):
    """Return a fresh .owlscale/ workspace inside a temporary directory."""
    owlscale_dir = init_project(tmp_path)
    return owlscale_dir


@pytest.fixture()
def workspace_with_agent(workspace):
    """Workspace that already has a single executor agent registered."""
    add_agent(workspace, "bot", "Test Bot", "executor")
    return workspace


# ---------------------------------------------------------------------------
# S01 — project scaffold
# ---------------------------------------------------------------------------


class TestS01Scaffold:
    def test_help_exits_zero(self):
        """owlscale --help must return exit code 0."""
        result = subprocess.run(
            [sys.executable, "-m", "owlscale", "--help"],
            capture_output=True,
            env=CLI_ENV,
            text=True,
        )
        assert result.returncode == 0
        assert "usage: owlscale" in result.stdout.lower()

    def test_version_exits_zero(self):
        """owlscale --version must return exit code 0 and print version."""
        result = subprocess.run(
            [sys.executable, "-m", "owlscale", "--version"],
            capture_output=True,
            env=CLI_ENV,
            text=True,
        )
        assert result.returncode == 0
        assert "owlscale" in result.stdout.lower()

    def test_module_importable(self):
        """The owlscale package must expose __version__."""
        import owlscale

        assert hasattr(owlscale, "__version__")
        assert owlscale.__version__


# ---------------------------------------------------------------------------
# S02 — `owlscale init`
# ---------------------------------------------------------------------------


class TestS02Init:
    def test_creates_directory_structure(self, tmp_path):
        owlscale_dir = init_project(tmp_path)

        assert owlscale_dir.is_dir()
        assert (owlscale_dir / "packets").is_dir()
        assert (owlscale_dir / "returns").is_dir()
        assert (owlscale_dir / "log").is_dir()
        assert (owlscale_dir / "templates").is_dir()

    def test_creates_state_json(self, tmp_path):
        owlscale_dir = init_project(tmp_path)
        state_path = owlscale_dir / "state.json"

        assert state_path.exists()
        data = json.loads(state_path.read_text())
        assert data["version"] == 1
        assert data["tasks"] == {}

    def test_creates_roster_json(self, tmp_path):
        owlscale_dir = init_project(tmp_path)
        roster_path = owlscale_dir / "roster.json"

        assert roster_path.exists()
        data = json.loads(roster_path.read_text())
        assert data["agents"] == {}

    def test_idempotent_on_existing_workspace(self, tmp_path):
        """Re-running init on an existing workspace must not raise and not overwrite."""
        owlscale_dir = init_project(tmp_path)
        # Modify state to confirm it is preserved
        state_path = owlscale_dir / "state.json"
        original = state_path.read_text()

        owlscale_dir2 = init_project(tmp_path)

        assert owlscale_dir == owlscale_dir2
        assert state_path.read_text() == original

    def test_cli_init_creates_workspace(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "owlscale", "init"],
            capture_output=True,
            env=CLI_ENV,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert (tmp_path / ".owlscale").is_dir()

    def test_cli_init_already_exists_does_not_error(self, tmp_path):
        init_project(tmp_path)
        result = subprocess.run(
            [sys.executable, "-m", "owlscale", "init"],
            capture_output=True,
            env=CLI_ENV,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "already exists" in result.stdout


# ---------------------------------------------------------------------------
# S03 — `owlscale roster`
# ---------------------------------------------------------------------------


class TestS03Roster:
    def test_add_agent_persists_to_roster_json(self, workspace):
        add_agent(workspace, "cc-opus", "Claude Code Opus", "coordinator")
        data = json.loads((workspace / "roster.json").read_text())
        assert "cc-opus" in data["agents"]
        assert data["agents"]["cc-opus"]["role"] == "coordinator"

    def test_list_agents_returns_registered_agents(self, workspace):
        add_agent(workspace, "a1", "Agent One", "executor")
        add_agent(workspace, "a2", "Agent Two", "hub")
        agents = list_agents(workspace)
        assert "a1" in agents
        assert "a2" in agents

    def test_remove_agent_deletes_from_roster(self, workspace):
        add_agent(workspace, "temp", "Temp Agent", "executor")
        remove_agent(workspace, "temp")
        agents = list_agents(workspace)
        assert "temp" not in agents

    def test_add_duplicate_agent_raises(self, workspace):
        add_agent(workspace, "dup", "Dup", "executor")
        with pytest.raises(AgentError, match="already registered"):
            add_agent(workspace, "dup", "Dup", "executor")

    def test_remove_nonexistent_agent_raises(self, workspace):
        with pytest.raises(AgentError, match="not found"):
            remove_agent(workspace, "ghost")

    def test_cli_roster_list_empty(self, tmp_path):
        init_project(tmp_path)
        result = subprocess.run(
            [sys.executable, "-m", "owlscale", "roster", "list"],
            capture_output=True,
            env=CLI_ENV,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "No agents" in result.stdout

    def test_cli_roster_add_and_list(self, tmp_path):
        init_project(tmp_path)
        subprocess.run(
            [sys.executable, "-m", "owlscale", "roster", "add", "mybot", "--name", "My Bot", "--role", "executor"],
            capture_output=True,
            env=CLI_ENV,
            text=True,
            cwd=str(tmp_path),
            check=True,
        )
        result = subprocess.run(
            [sys.executable, "-m", "owlscale", "roster", "list"],
            capture_output=True,
            env=CLI_ENV,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "mybot" in result.stdout


# ---------------------------------------------------------------------------
# S04 — `owlscale pack`
# ---------------------------------------------------------------------------


class TestS04Pack:
    def test_pack_creates_packet_file(self, workspace_with_agent):
        packet_path = pack_task(workspace_with_agent, "t-001", "Do something")
        assert packet_path.exists()
        assert packet_path.name == "t-001.md"

    def test_packet_has_valid_yaml_frontmatter(self, workspace_with_agent):
        pack_task(workspace_with_agent, "t-002", "Another goal")
        content = (workspace_with_agent / "packets" / "t-002.md").read_text()
        packet = Packet.from_markdown(content)
        assert packet.frontmatter.id == "t-002"
        assert packet.frontmatter.goal == "Another goal"
        assert packet.frontmatter.status == TaskStatus.draft

    def test_pack_updates_state_json(self, workspace_with_agent):
        pack_task(workspace_with_agent, "t-003", "Goal")
        state = get_status(workspace_with_agent)
        assert "t-003" in state.tasks
        assert state.tasks["t-003"].status == TaskStatus.draft

    def test_pack_writes_log_entry(self, workspace_with_agent):
        pack_task(workspace_with_agent, "t-004", "Goal")
        entries = get_log(workspace_with_agent)
        assert any("PACK" in e and "t-004" in e for e in entries)

    def test_pack_with_tags(self, workspace_with_agent):
        pack_task(workspace_with_agent, "t-005", "Tagged goal", tags=["arch", "v0"])
        content = (workspace_with_agent / "packets" / "t-005.md").read_text()
        packet = Packet.from_markdown(content)
        assert "arch" in packet.frontmatter.tags
        assert "v0" in packet.frontmatter.tags

    def test_pack_duplicate_task_raises(self, workspace_with_agent):
        pack_task(workspace_with_agent, "t-dup", "Goal")
        with pytest.raises(TaskError, match="already exists"):
            pack_task(workspace_with_agent, "t-dup", "Other goal")

    def test_cli_pack_creates_packet(self, tmp_path):
        init_project(tmp_path)
        result = subprocess.run(
            [sys.executable, "-m", "owlscale", "pack", "my-task", "--goal", "Build stuff"],
            capture_output=True,
            env=CLI_ENV,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert (tmp_path / ".owlscale" / "packets" / "my-task.md").exists()


# ---------------------------------------------------------------------------
# S05 — `owlscale dispatch`
# ---------------------------------------------------------------------------


class TestS05Dispatch:
    def test_dispatch_updates_state(self, workspace_with_agent):
        pack_task(workspace_with_agent, "d-001", "Goal")
        dispatch_task(workspace_with_agent, "d-001", "bot")

        state = get_status(workspace_with_agent)
        task = state.tasks["d-001"]
        assert task.status == TaskStatus.dispatched
        assert task.assignee == "bot"
        assert task.dispatched_at is not None

    def test_dispatch_updates_packet_frontmatter(self, workspace_with_agent):
        pack_task(workspace_with_agent, "d-002", "Goal")
        dispatch_task(workspace_with_agent, "d-002", "bot")

        content = (workspace_with_agent / "packets" / "d-002.md").read_text()
        packet = Packet.from_markdown(content)
        assert packet.frontmatter.status == TaskStatus.dispatched
        assert packet.frontmatter.assignee == "bot"

    def test_dispatch_writes_log_entry(self, workspace_with_agent):
        pack_task(workspace_with_agent, "d-003", "Goal")
        dispatch_task(workspace_with_agent, "d-003", "bot")

        entries = get_log(workspace_with_agent)
        assert any("DISPATCH" in e and "d-003" in e and "bot" in e for e in entries)

    def test_dispatch_unknown_task_raises(self, workspace_with_agent):
        with pytest.raises(TaskError, match="not found"):
            dispatch_task(workspace_with_agent, "ghost-task", "bot")

    def test_dispatch_unknown_agent_raises(self, workspace_with_agent):
        pack_task(workspace_with_agent, "d-004", "Goal")
        with pytest.raises(AgentError, match="not registered"):
            dispatch_task(workspace_with_agent, "d-004", "unknown-agent")

    def test_dispatch_already_dispatched_raises(self, workspace_with_agent):
        pack_task(workspace_with_agent, "d-005", "Goal")
        dispatch_task(workspace_with_agent, "d-005", "bot")
        with pytest.raises(TaskError, match="dispatch"):
            dispatch_task(workspace_with_agent, "d-005", "bot")


# ---------------------------------------------------------------------------
# S06 — `owlscale return`
# ---------------------------------------------------------------------------


class TestS06Return:
    def _setup_dispatched_task(self, workspace, task_id="r-001"):
        add_agent(workspace, "agent-r", "Return Bot", "executor")
        pack_task(workspace, task_id, "Goal")
        dispatch_task(workspace, task_id, "agent-r")
        return task_id

    def test_return_without_packet_raises(self, workspace):
        self._setup_dispatched_task(workspace)
        # dispatch now auto-generates a return template; remove it to test this case
        return_path = workspace / "returns" / "r-001.md"
        if return_path.exists():
            return_path.unlink()
        with pytest.raises(TaskError, match="Return packet not found"):
            return_task(workspace, "r-001")

    def test_return_with_packet_updates_state(self, workspace):
        self._setup_dispatched_task(workspace)
        (workspace / "returns" / "r-001.md").write_text("# Done\nAll good.")
        return_task(workspace, "r-001")

        state = get_status(workspace)
        assert state.tasks["r-001"].status == TaskStatus.returned
        assert state.tasks["r-001"].returned_at is not None

    def test_return_writes_log_entry(self, workspace):
        self._setup_dispatched_task(workspace)
        (workspace / "returns" / "r-001.md").write_text("# Done")
        return_task(workspace, "r-001")

        entries = get_log(workspace)
        assert any("RETURN" in e and "r-001" in e for e in entries)

    def test_return_on_draft_task_raises(self, workspace):
        add_agent(workspace, "agent-r2", "Bot", "executor")
        pack_task(workspace, "r-draft", "Goal")
        with pytest.raises(TaskError):
            return_task(workspace, "r-draft")


# ---------------------------------------------------------------------------
# S07 — `owlscale accept / reject`
# ---------------------------------------------------------------------------


class TestS07AcceptReject:
    def _make_returned_task(self, workspace, task_id):
        add_agent(workspace, f"agent-{task_id}", "Bot", "executor")
        pack_task(workspace, task_id, "Goal")
        dispatch_task(workspace, task_id, f"agent-{task_id}")
        (workspace / "returns" / f"{task_id}.md").write_text("# Done")
        return_task(workspace, task_id)

    def test_accept_sets_status_accepted(self, workspace):
        self._make_returned_task(workspace, "a-001")
        accept_task(workspace, "a-001")

        state = get_status(workspace)
        assert state.tasks["a-001"].status == TaskStatus.accepted
        assert state.tasks["a-001"].accepted_at is not None

    def test_accept_writes_log_entry(self, workspace):
        self._make_returned_task(workspace, "a-002")
        accept_task(workspace, "a-002")

        entries = get_log(workspace)
        assert any("ACCEPT" in e and "a-002" in e for e in entries)

    def test_reject_sets_status_rejected(self, workspace):
        self._make_returned_task(workspace, "a-003")
        reject_task(workspace, "a-003", reason="needs work")

        state = get_status(workspace)
        assert state.tasks["a-003"].status == TaskStatus.rejected
        assert state.tasks["a-003"].rejected_at is not None

    def test_reject_writes_reason_to_log(self, workspace):
        self._make_returned_task(workspace, "a-004")
        reject_task(workspace, "a-004", reason="too slow")

        entries = get_log(workspace)
        assert any("REJECT" in e and "a-004" in e and "too slow" in e for e in entries)

    def test_accept_non_returned_task_raises(self, workspace):
        add_agent(workspace, "agent-nr", "Bot", "executor")
        pack_task(workspace, "a-005", "Goal")
        with pytest.raises(TaskError):
            accept_task(workspace, "a-005")

    def test_reject_non_returned_task_raises(self, workspace):
        add_agent(workspace, "agent-nr2", "Bot", "executor")
        pack_task(workspace, "a-006", "Goal")
        with pytest.raises(TaskError):
            reject_task(workspace, "a-006")


# ---------------------------------------------------------------------------
# S08 — `owlscale status`
# ---------------------------------------------------------------------------


class TestS08Status:
    def test_status_empty_when_no_tasks(self, workspace):
        state = get_status(workspace)
        assert state.tasks == {}

    def test_status_reflects_current_state(self, workspace):
        add_agent(workspace, "s-bot", "Bot", "executor")
        pack_task(workspace, "s-001", "Goal")
        dispatch_task(workspace, "s-001", "s-bot")

        state = get_status(workspace)
        assert state.tasks["s-001"].status == TaskStatus.dispatched

    def test_cli_status_empty(self, tmp_path):
        init_project(tmp_path)
        result = subprocess.run(
            [sys.executable, "-m", "owlscale", "status"],
            capture_output=True,
            env=CLI_ENV,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "No tasks" in result.stdout

    def test_cli_status_shows_tasks(self, tmp_path):
        init_project(tmp_path)
        subprocess.run(
            [sys.executable, "-m", "owlscale", "pack", "my-task", "--goal", "G"],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
            env=CLI_ENV,
        )
        result = subprocess.run(
            [sys.executable, "-m", "owlscale", "status"],
            capture_output=True,
            env=CLI_ENV,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "my-task" in result.stdout


# ---------------------------------------------------------------------------
# S09 — `owlscale log`
# ---------------------------------------------------------------------------


class TestS09Log:
    def test_log_empty_when_no_operations(self, workspace):
        entries = get_log(workspace)
        assert entries == []

    def test_log_records_operations_in_reverse_order(self, workspace):
        add_agent(workspace, "l-bot", "Bot", "executor")
        pack_task(workspace, "l-001", "Goal")
        dispatch_task(workspace, "l-001", "l-bot")

        entries = get_log(workspace)
        # Newest first: DISPATCH then PACK
        assert "DISPATCH" in entries[0]
        assert "PACK" in entries[1]

    def test_log_filter_by_task_id(self, workspace):
        add_agent(workspace, "l-bot2", "Bot", "executor")
        pack_task(workspace, "l-002", "Goal")
        pack_task(workspace, "l-003", "Other goal")

        entries = get_log(workspace, task_id="l-002")
        assert all("l-002" in e for e in entries)
        assert not any("l-003" in e for e in entries)

    def test_log_limit(self, workspace):
        add_agent(workspace, "l-bot3", "Bot", "executor")
        for i in range(5):
            pack_task(workspace, f"l-{i:03d}", f"Goal {i}")

        entries = get_log(workspace, limit=3)
        assert len(entries) == 3

    def test_cli_log_empty(self, tmp_path):
        init_project(tmp_path)
        result = subprocess.run(
            [sys.executable, "-m", "owlscale", "log"],
            capture_output=True,
            env=CLI_ENV,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "No log entries" in result.stdout

    def test_cli_log_shows_entries(self, tmp_path):
        init_project(tmp_path)
        subprocess.run(
            [sys.executable, "-m", "owlscale", "pack", "x-task", "--goal", "Impl"],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
            env=CLI_ENV,
        )
        result = subprocess.run(
            [sys.executable, "-m", "owlscale", "log"],
            capture_output=True,
            env=CLI_ENV,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "PACK" in result.stdout
        assert "x-task" in result.stdout


# ---------------------------------------------------------------------------
# S10 — `owlscale claim`
# ---------------------------------------------------------------------------


class TestS10Claim:
    def _setup_dispatched_task(self, workspace, task_id="c-001"):
        add_agent(workspace, "claim-bot", "Claim Bot", "executor")
        pack_task(workspace, task_id, "Goal for claim")
        dispatch_task(workspace, task_id, "claim-bot")
        return task_id

    def test_claim_updates_state_to_in_progress(self, workspace):
        self._setup_dispatched_task(workspace)
        claim_task(workspace, "c-001")

        state = get_status(workspace)
        assert state.tasks["c-001"].status == TaskStatus.in_progress

    def test_claim_non_dispatched_task_raises(self, workspace):
        add_agent(workspace, "claim-bot2", "Bot", "executor")
        pack_task(workspace, "c-draft", "Goal")
        with pytest.raises(TaskError, match="dispatched"):
            claim_task(workspace, "c-draft")

    def test_claim_already_in_progress_raises(self, workspace):
        self._setup_dispatched_task(workspace, "c-dup")
        claim_task(workspace, "c-dup")
        with pytest.raises(TaskError, match="in_progress"):
            claim_task(workspace, "c-dup")

    def test_claim_unknown_task_raises(self, workspace):
        with pytest.raises(TaskError, match="not found"):
            claim_task(workspace, "ghost")

    def test_claim_writes_log_entry(self, workspace):
        self._setup_dispatched_task(workspace, "c-log")
        claim_task(workspace, "c-log")

        entries = get_log(workspace)
        assert any("CLAIM" in e and "c-log" in e for e in entries)

    def test_cli_claim_works(self, tmp_path):
        init_project(tmp_path)
        subprocess.run(
            [sys.executable, "-m", "owlscale", "roster", "add", "bot", "--name", "Bot", "--role", "executor"],
            cwd=str(tmp_path), check=True, capture_output=True, env=CLI_ENV,
        )
        subprocess.run(
            [sys.executable, "-m", "owlscale", "pack", "ct-1", "--goal", "Test"],
            cwd=str(tmp_path), check=True, capture_output=True, env=CLI_ENV,
        )
        subprocess.run(
            [sys.executable, "-m", "owlscale", "dispatch", "ct-1", "bot"],
            cwd=str(tmp_path), check=True, capture_output=True, env=CLI_ENV,
        )
        result = subprocess.run(
            [sys.executable, "-m", "owlscale", "claim", "ct-1"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "Claimed" in result.stdout

    def test_full_lifecycle_with_claim(self, workspace):
        """pack → dispatch → claim → return → accept."""
        add_agent(workspace, "lc-bot", "LC Bot", "executor")
        pack_task(workspace, "lc-001", "Full lifecycle")
        dispatch_task(workspace, "lc-001", "lc-bot")
        claim_task(workspace, "lc-001")

        state = get_status(workspace)
        assert state.tasks["lc-001"].status == TaskStatus.in_progress

        # Return should work from in_progress
        (workspace / "returns" / "lc-001.md").write_text("# Done\nAll good.")
        return_task(workspace, "lc-001")
        state = get_status(workspace)
        assert state.tasks["lc-001"].status == TaskStatus.returned

        accept_task(workspace, "lc-001")
        state = get_status(workspace)
        assert state.tasks["lc-001"].status == TaskStatus.accepted


# ---------------------------------------------------------------------------
# S11 — Return Packet template generation
# ---------------------------------------------------------------------------


class TestS11ReturnTemplate:
    def test_dispatch_generates_return_template(self, workspace_with_agent):
        pack_task(workspace_with_agent, "rt-001", "My goal")
        dispatch_task(workspace_with_agent, "rt-001", "bot")

        return_path = workspace_with_agent / "returns" / "rt-001.md"
        assert return_path.exists()

    def test_template_has_required_sections(self, workspace_with_agent):
        pack_task(workspace_with_agent, "rt-002", "Some goal")
        dispatch_task(workspace_with_agent, "rt-002", "bot")

        content = (workspace_with_agent / "returns" / "rt-002.md").read_text()
        assert "## Summary" in content
        assert "## Files Modified" in content
        assert "## Key Decisions" in content
        assert "## Tests Run" in content
        assert "## Remaining Risks" in content
        assert "## Unfinished Items" in content

    def test_template_contains_goal(self, workspace_with_agent):
        pack_task(workspace_with_agent, "rt-003", "Build the widget")
        dispatch_task(workspace_with_agent, "rt-003", "bot")

        content = (workspace_with_agent / "returns" / "rt-003.md").read_text()
        assert "Build the widget" in content

    def test_existing_return_file_not_overwritten(self, workspace_with_agent):
        pack_task(workspace_with_agent, "rt-004", "Goal")
        # Pre-create a return file
        return_path = workspace_with_agent / "returns" / "rt-004.md"
        return_path.write_text("# My custom return\nCustom content.")

        dispatch_task(workspace_with_agent, "rt-004", "bot")

        # Should NOT be overwritten
        content = return_path.read_text()
        assert "Custom content." in content
        assert "## Summary" not in content

    def test_template_contains_task_id_in_title(self, workspace_with_agent):
        pack_task(workspace_with_agent, "rt-005", "A goal")
        dispatch_task(workspace_with_agent, "rt-005", "bot")

        content = (workspace_with_agent / "returns" / "rt-005.md").read_text()
        assert "rt-005" in content


# ---------------------------------------------------------------------------
# Workspace discovery
# ---------------------------------------------------------------------------


class TestWorkspaceDiscovery:
    def test_get_workspace_root_finds_parent(self, tmp_path):
        init_project(tmp_path)
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        found = get_workspace_root(nested)
        assert found == tmp_path / ".owlscale"

    def test_get_workspace_root_raises_when_not_found(self, tmp_path):
        with pytest.raises(WorkspaceError, match="No .owlscale"):
            get_workspace_root(tmp_path)
