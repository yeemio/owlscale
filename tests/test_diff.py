"""Tests for owlscale diff command."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
CLI_ENV = {**os.environ, "PYTHONPATH": PROJECT_ROOT}

from owlscale.core import init_project, pack_task, dispatch_task, add_agent, TaskError
from owlscale.models import Packet
from owlscale.diff import diff_packets, diff_task_packets, DiffResult


@pytest.fixture()
def workspace(tmp_path):
    return init_project(tmp_path)


@pytest.fixture()
def two_packets(workspace):
    """Create two packets with different content for comparison."""
    pack_task(workspace, "v1", "Build the widget", tags=["python"])
    pack_task(workspace, "v2", "Build the widget v2", tags=["python", "v2"])

    # Modify v2's body
    p2_path = workspace / "packets" / "v2.md"
    content = p2_path.read_text()
    packet = Packet.from_markdown(content)
    packet.body = packet.body.replace(
        "<!-- Describe the current state of the project/system -->",
        "Widget v1 is done, need v2 improvements."
    )
    p2_path.write_text(packet.to_markdown())
    return workspace


class TestDiffPackets:
    def test_identical_packets_no_changes(self, workspace):
        pack_task(workspace, "same1", "Same goal")
        pack_task(workspace, "same2", "Same goal")
        # Overwrite same2 with same1's content
        p1 = workspace / "packets" / "same1.md"
        p2 = workspace / "packets" / "same2.md"
        p2.write_text(p1.read_text())

        result = diff_packets(p1, p2)
        assert result.has_changes is False
        assert result.frontmatter_changes == []
        assert result.body_diff == ""

    def test_frontmatter_changes_detected(self, two_packets):
        result = diff_task_packets(two_packets, "v1", "v2")
        assert result.has_changes is True
        # goal changed: "Build the widget" → "Build the widget v2"
        fm_text = "\n".join(result.frontmatter_changes)
        assert "goal" in fm_text

    def test_body_changes_detected(self, two_packets):
        result = diff_task_packets(two_packets, "v1", "v2")
        assert result.has_changes is True
        assert "Widget v1 is done" in result.body_diff or len(result.body_diff) > 0

    def test_added_field_shown_as_plus(self, workspace):
        pack_task(workspace, "a", "Goal A")
        pack_task(workspace, "b", "Goal B", tags=["newtag"])
        result = diff_task_packets(workspace, "a", "b")
        fm_text = "\n".join(result.frontmatter_changes)
        assert "tags" in fm_text or "goal" in fm_text

    def test_nonexistent_packet_raises(self, workspace):
        pack_task(workspace, "exists", "Goal")
        with pytest.raises(TaskError, match="not found"):
            diff_task_packets(workspace, "exists", "ghost")

    def test_context_lines_parameter(self, two_packets):
        result = diff_task_packets(two_packets, "v1", "v2", context_lines=0)
        assert result.has_changes is True

    def test_diff_result_has_task_ids(self, two_packets):
        result = diff_task_packets(two_packets, "v1", "v2")
        assert result.task_id_a == "v1"
        assert result.task_id_b == "v2"

    def test_diff_dispatched_vs_draft(self, workspace):
        """Diff a draft and dispatched version of same task (frontmatter changes)."""
        add_agent(workspace, "bot", "Bot", "executor")
        pack_task(workspace, "orig", "Goal")
        # Copy original
        p_orig = workspace / "packets" / "orig.md"
        original_content = p_orig.read_text()

        # Dispatch modifies the packet
        dispatch_task(workspace, "orig", "bot")

        # Write the original as a separate file for comparison
        p_before = workspace / "packets" / "orig-before.md"
        p_before.write_text(original_content)

        result = diff_packets(p_before, p_orig)
        assert result.has_changes is True
        fm_text = "\n".join(result.frontmatter_changes)
        assert "status" in fm_text


class TestDiffCLI:
    def test_cli_diff_shows_changes(self, tmp_path):
        ws = init_project(tmp_path)
        pack_task(ws, "d1", "Goal one")
        pack_task(ws, "d2", "Goal two")

        result = subprocess.run(
            [sys.executable, "-m", "owlscale", "diff", "d1", "d2"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "Frontmatter changes:" in result.stdout or "Body changes:" in result.stdout

    def test_cli_diff_no_changes(self, tmp_path):
        ws = init_project(tmp_path)
        pack_task(ws, "s1", "Same")
        p1 = ws / "packets" / "s1.md"
        # Create s2 as exact copy
        pack_task(ws, "s2", "Same")
        (ws / "packets" / "s2.md").write_text(p1.read_text())

        result = subprocess.run(
            [sys.executable, "-m", "owlscale", "diff", "s1", "s2"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "No differences" in result.stdout
