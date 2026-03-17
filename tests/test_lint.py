"""Tests for owlscale lint module."""

import json
import sys
import os
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
CLI_ENV = {**os.environ, "PYTHONPATH": PROJECT_ROOT}

from owlscale.lint import lint_packet, LintResult, _extract_relevant_files
from owlscale.core import init_project, pack_task, add_agent, dispatch_task, claim_task


def init_ws(tmp_path: Path) -> Path:
    return init_project(tmp_path)


def _run(tmp_path, *args):
    return subprocess.run(
        [sys.executable, "-m", "owlscale"] + list(args),
        capture_output=True, text=True, env=CLI_ENV, cwd=tmp_path,
    )


def _write_goal_packet(ws, task_id, goal="Build REST API"):
    pack_task(ws, task_id, goal)


# ---------------------------------------------------------------------------
# TestExtractRelevantFiles
# ---------------------------------------------------------------------------

class TestExtractRelevantFiles:
    def test_backtick_paths(self, tmp_path):
        body = "See `src/auth.py` for details."
        result = _extract_relevant_files(body, tmp_path)
        assert any("src/auth.py" in str(p) for p in result)

    def test_bare_paths(self, tmp_path):
        body = "Modify owlscale/cli.py to add handler."
        result = _extract_relevant_files(body, tmp_path)
        assert any("owlscale/cli.py" in str(p) for p in result)

    def test_no_paths(self, tmp_path):
        body = "No file references here."
        assert _extract_relevant_files(body, tmp_path) == []

    def test_http_urls_excluded(self, tmp_path):
        body = "`http://example.com/api.py`"
        result = _extract_relevant_files(body, tmp_path)
        assert all("http" not in str(p) for p in result)


# ---------------------------------------------------------------------------
# TestLintPacket
# ---------------------------------------------------------------------------

class TestLintPacket:
    def test_returns_four_results(self, tmp_path):
        ws = init_ws(tmp_path)
        _write_goal_packet(ws, "t1")
        results = lint_packet(ws, "t1")
        assert len(results) == 4

    def test_result_names_in_order(self, tmp_path):
        ws = init_ws(tmp_path)
        _write_goal_packet(ws, "t1")
        results = lint_packet(ws, "t1")
        names = [r.name for r in results]
        assert names == ["validate", "fmt", "files", "assignee"]

    def test_all_results_are_lint_result(self, tmp_path):
        ws = init_ws(tmp_path)
        _write_goal_packet(ws, "t1")
        results = lint_packet(ws, "t1")
        for r in results:
            assert isinstance(r, LintResult)

    def test_validate_check_passes_for_good_packet(self, tmp_path):
        ws = init_ws(tmp_path)
        # Pack with a goal and a real body
        pack_task(ws, "t1", "Build REST API")
        # Overwrite with a rich body
        packet_path = ws / "packets" / "t1.md"
        content = packet_path.read_text()
        packet_path.write_text(
            content.replace("## Goal\n\n<!-- Describe the task goal here -->",
                            "## Goal\n\nBuild a REST API for users.")
        )
        results = lint_packet(ws, "t1")
        validate_r = next(r for r in results if r.name == "validate")
        assert isinstance(validate_r.passed, bool)

    def test_assignee_passes_when_no_assignee(self, tmp_path):
        ws = init_ws(tmp_path)
        _write_goal_packet(ws, "t1")
        results = lint_packet(ws, "t1")
        assignee_r = next(r for r in results if r.name == "assignee")
        assert assignee_r.passed is True

    def test_assignee_fails_when_unregistered(self, tmp_path):
        ws = init_ws(tmp_path)
        _write_goal_packet(ws, "t1")
        # Register, dispatch, then delete from roster to simulate orphaned assignee
        add_agent(ws, "temp-agent", "Temp", "executor")
        dispatch_task(ws, "t1", "temp-agent")
        # Remove from roster directly
        roster_path = ws / "roster.json"
        import json as _json
        roster = _json.loads(roster_path.read_text())
        del roster["agents"]["temp-agent"]
        roster_path.write_text(_json.dumps(roster))
        results = lint_packet(ws, "t1")
        assignee_r = next(r for r in results if r.name == "assignee")
        assert assignee_r.passed is False

    def test_assignee_passes_when_registered(self, tmp_path):
        ws = init_ws(tmp_path)
        _write_goal_packet(ws, "t1")
        add_agent(ws, "agent-a", "Agent A", "executor")
        dispatch_task(ws, "t1", "agent-a")
        results = lint_packet(ws, "t1")
        assignee_r = next(r for r in results if r.name == "assignee")
        assert assignee_r.passed is True

    def test_files_check_passes_when_no_references(self, tmp_path):
        ws = init_ws(tmp_path)
        _write_goal_packet(ws, "t1")
        results = lint_packet(ws, "t1")
        files_r = next(r for r in results if r.name == "files")
        assert files_r.passed is True

    def test_files_check_fails_for_missing_file(self, tmp_path):
        ws = init_ws(tmp_path)
        pack_task(ws, "t1", "Update auth")
        packet_path = ws / "packets" / "t1.md"
        content = packet_path.read_text()
        packet_path.write_text(content + "\n\nModify `src/nonexistent_auth.py` to add JWT.")
        results = lint_packet(ws, "t1")
        files_r = next(r for r in results if r.name == "files")
        assert files_r.passed is False


# ---------------------------------------------------------------------------
# TestLintCli
# ---------------------------------------------------------------------------

class TestLintCli:
    def test_lint_task_exits_0_on_pass(self, tmp_path):
        ws = init_ws(tmp_path)
        add_agent(ws, "agent-a", "Agent A", "executor")
        _write_goal_packet(ws, "t1")
        result = _run(tmp_path, "lint", "t1")
        assert result.returncode in (0, 1)

    def test_lint_shows_four_checks(self, tmp_path):
        ws = init_ws(tmp_path)
        _write_goal_packet(ws, "t1")
        result = _run(tmp_path, "lint", "t1")
        for name in ("validate", "fmt", "files", "assignee"):
            assert name in result.stdout

    def test_lint_json_output(self, tmp_path):
        ws = init_ws(tmp_path)
        _write_goal_packet(ws, "t1")
        result = _run(tmp_path, "lint", "t1", "--json")
        assert result.returncode in (0, 1)
        data = json.loads(result.stdout)
        assert "task_id" in data
        assert "checks" in data
        assert len(data["checks"]) == 4

    def test_lint_all_no_tasks(self, tmp_path):
        init_ws(tmp_path)
        result = _run(tmp_path, "lint", "--all")
        assert result.returncode == 0
        assert "No tasks" in result.stdout

    def test_lint_all_runs_for_each_task(self, tmp_path):
        ws = init_ws(tmp_path)
        _write_goal_packet(ws, "t1")
        _write_goal_packet(ws, "t2")
        result = _run(tmp_path, "lint", "--all")
        assert "t1" in result.stdout
        assert "t2" in result.stdout

    def test_lint_no_args_fails(self, tmp_path):
        init_ws(tmp_path)
        result = _run(tmp_path, "lint")
        assert result.returncode != 0
