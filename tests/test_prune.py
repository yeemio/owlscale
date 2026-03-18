"""Tests for owlscale prune command."""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
CLI_ENV = {**os.environ, "PYTHONPATH": PROJECT_ROOT}

from owlscale.core import (
    init_project, add_agent, pack_task, dispatch_task,
    return_task, accept_task, reject_task, load_state, save_state,
)
from owlscale.models import TaskStatus
from owlscale.prune import prune_workspace, PruneResult, purge_workspace


def _make_completed_task(workspace, task_id, agent_id, status=TaskStatus.accepted, days_ago=60):
    """Helper: create, dispatch, return, then accept/reject a task with backdated timestamp."""
    pack_task(workspace, task_id, f"Goal for {task_id}")
    dispatch_task(workspace, task_id, agent_id)
    ret = workspace / "returns" / f"{task_id}.md"
    ret.write_text(f"# Done {task_id}")
    return_task(workspace, task_id)

    state = load_state(workspace)
    task = state.tasks[task_id]

    old_ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()

    if status == TaskStatus.accepted:
        accept_task(workspace, task_id)
        state = load_state(workspace)
        state.tasks[task_id].accepted_at = old_ts
    else:
        reject_task(workspace, task_id, reason="bad")
        state = load_state(workspace)
        state.tasks[task_id].rejected_at = old_ts

    save_state(workspace, state)


@pytest.fixture()
def workspace(tmp_path):
    ws = init_project(tmp_path)
    add_agent(ws, "bot", "Bot", "executor")
    return ws


class TestPruneWorkspace:
    def test_archives_old_accepted_task(self, workspace):
        _make_completed_task(workspace, "old-1", "bot", days_ago=60)
        result = prune_workspace(workspace, days=30)
        assert "old-1" in result.archived
        assert not (workspace / "packets" / "old-1.md").exists()

    def test_archives_old_rejected_task(self, workspace):
        _make_completed_task(workspace, "old-rej", "bot", status=TaskStatus.rejected, days_ago=45)
        result = prune_workspace(workspace, days=30)
        assert "old-rej" in result.archived

    def test_skips_recent_task(self, workspace):
        _make_completed_task(workspace, "recent", "bot", days_ago=5)
        result = prune_workspace(workspace, days=30)
        assert "recent" in result.skipped
        assert (workspace / "packets" / "recent.md").exists()

    def test_skips_non_completed_tasks(self, workspace):
        pack_task(workspace, "draft-t", "Draft task")
        result = prune_workspace(workspace, days=0)
        assert "draft-t" in result.skipped

    def test_removes_from_state(self, workspace):
        _make_completed_task(workspace, "gone", "bot", days_ago=60)
        prune_workspace(workspace, days=30)
        state = load_state(workspace)
        assert "gone" not in state.tasks

    def test_mixed_ages(self, workspace):
        _make_completed_task(workspace, "keep-me", "bot", days_ago=5)
        _make_completed_task(workspace, "archive-me", "bot", days_ago=90)
        result = prune_workspace(workspace, days=30)
        assert "archive-me" in result.archived
        assert "keep-me" in result.skipped

    def test_archive_directory_created(self, workspace):
        _make_completed_task(workspace, "arc-1", "bot", days_ago=60)
        prune_workspace(workspace, days=30)
        archives = list((workspace / "archive").glob("**/*.md"))
        assert len(archives) >= 1

    def test_archive_grouped_by_month(self, workspace):
        _make_completed_task(workspace, "old-a", "bot", days_ago=60)
        prune_workspace(workspace, days=30)
        month_dirs = list((workspace / "archive").iterdir())
        assert len(month_dirs) >= 1
        # Month dirs should be YYYY-MM format
        for d in month_dirs:
            assert len(d.name) == 7 and d.name[4] == "-"

    def test_return_file_also_moved(self, workspace):
        _make_completed_task(workspace, "with-ret", "bot", days_ago=60)
        prune_workspace(workspace, days=30)
        assert not (workspace / "returns" / "with-ret.md").exists()

    def test_missing_return_file_no_error(self, workspace):
        _make_completed_task(workspace, "no-ret", "bot", days_ago=60)
        # Remove return file before pruning
        ret = workspace / "returns" / "no-ret.md"
        if ret.exists():
            ret.unlink()
        result = prune_workspace(workspace, days=30)
        assert "no-ret" in result.archived

    def test_dry_run_no_files_moved(self, workspace):
        _make_completed_task(workspace, "dry-1", "bot", days_ago=60)
        result = prune_workspace(workspace, days=30, dry_run=True)
        assert result.dry_run is True
        assert "dry-1" in result.archived
        # Files should still exist
        assert (workspace / "packets" / "dry-1.md").exists()
        # State unchanged
        state = load_state(workspace)
        assert "dry-1" in state.tasks

    def test_days_zero_archives_all_completed(self, workspace):
        _make_completed_task(workspace, "new-1", "bot", days_ago=1)
        result = prune_workspace(workspace, days=0)
        assert "new-1" in result.archived

    def test_empty_workspace_no_error(self, workspace):
        result = prune_workspace(workspace, days=30)
        assert result.archived == []

    def test_purge_alias_matches_prune_behavior(self, workspace):
        _make_completed_task(workspace, "purge-me", "bot", days_ago=60)
        result = purge_workspace(workspace, days=30)
        assert "purge-me" in result.archived


class TestPruneCLI:
    def test_dry_run_exits_zero(self, tmp_path):
        ws = init_project(tmp_path)
        add_agent(ws, "bot", "Bot", "executor")
        _make_completed_task(ws, "old", "bot", days_ago=90)
        r = subprocess.run(
            [sys.executable, "-m", "owlscale", "prune", "--dry-run"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert r.returncode == 0
        assert "old" in r.stdout

    def test_dry_run_does_not_archive(self, tmp_path):
        ws = init_project(tmp_path)
        add_agent(ws, "bot", "Bot", "executor")
        _make_completed_task(ws, "old", "bot", days_ago=90)
        subprocess.run(
            [sys.executable, "-m", "owlscale", "prune", "--dry-run"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert (ws / "packets" / "old.md").exists()

    def test_force_archives_without_prompt(self, tmp_path):
        ws = init_project(tmp_path)
        add_agent(ws, "bot", "Bot", "executor")
        _make_completed_task(ws, "old2", "bot", days_ago=90)
        r = subprocess.run(
            [sys.executable, "-m", "owlscale", "prune", "--force"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert r.returncode == 0
        assert "Archived" in r.stdout
        assert not (ws / "packets" / "old2.md").exists()

    def test_no_tasks_message(self, tmp_path):
        init_project(tmp_path)
        r = subprocess.run(
            [sys.executable, "-m", "owlscale", "prune", "--dry-run"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert r.returncode == 0
        assert "No completed tasks" in r.stdout

    def test_custom_days(self, tmp_path):
        ws = init_project(tmp_path)
        add_agent(ws, "bot", "Bot", "executor")
        _make_completed_task(ws, "recent", "bot", days_ago=5)
        r = subprocess.run(
            [sys.executable, "-m", "owlscale", "prune", "--days", "1", "--force"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert r.returncode == 0
        assert not (ws / "packets" / "recent.md").exists()

    def test_purge_alias_archives_without_prompt(self, tmp_path):
        ws = init_project(tmp_path)
        add_agent(ws, "bot", "Bot", "executor")
        _make_completed_task(ws, "old-purge", "bot", days_ago=90)
        r = subprocess.run(
            [sys.executable, "-m", "owlscale", "purge", "--apply"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert r.returncode == 0
        assert "APPLY" in r.stdout
        assert not (ws / "packets" / "old-purge.md").exists()
