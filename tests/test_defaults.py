"""Tests for owlscale init --register-defaults."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
CLI_ENV = {**os.environ, "PYTHONPATH": PROJECT_ROOT}

from owlscale.core import init_project, load_roster
from owlscale.defaults import detect_agents, register_defaults


@pytest.fixture()
def project(tmp_path):
    """A bare project directory (not yet initialized with owlscale)."""
    return tmp_path


class TestDetectAgents:
    def test_detects_claude_code(self, project):
        (project / ".claude").mkdir()
        found = detect_agents(project)
        ids = [a[0] for a in found]
        assert "claude-code" in ids

    def test_detects_copilot_instructions(self, project):
        (project / ".github").mkdir()
        (project / ".github" / "copilot-instructions.md").write_text("# hi")
        found = detect_agents(project)
        ids = [a[0] for a in found]
        assert "copilot" in ids

    def test_detects_copilot_dir(self, project):
        (project / "copilot").mkdir()
        found = detect_agents(project)
        ids = [a[0] for a in found]
        assert "copilot" in ids

    def test_detects_cursor(self, project):
        (project / ".cursor").mkdir()
        found = detect_agents(project)
        ids = [a[0] for a in found]
        assert "cursor" in ids

    def test_detects_cursorrules(self, project):
        (project / ".cursorrules").write_text("rules")
        found = detect_agents(project)
        ids = [a[0] for a in found]
        assert "cursor" in ids

    def test_detects_aider(self, project):
        (project / ".aider.chat.history.md").write_text("history")
        found = detect_agents(project)
        ids = [a[0] for a in found]
        assert "aider" in ids

    def test_deduplicates(self, project):
        # Both copilot markers present
        (project / "copilot").mkdir()
        (project / ".github").mkdir()
        (project / ".github" / "copilot-instructions.md").write_text("")
        found = detect_agents(project)
        ids = [a[0] for a in found]
        assert ids.count("copilot") == 1

    def test_no_agents(self, project):
        found = detect_agents(project)
        assert found == []

    def test_multiple_agents(self, project):
        (project / ".claude").mkdir()
        (project / "copilot").mkdir()
        (project / ".cursor").mkdir()
        found = detect_agents(project)
        ids = [a[0] for a in found]
        assert set(ids) == {"claude-code", "copilot", "cursor"}


class TestRegisterDefaults:
    def test_registers_detected(self, project):
        ws = init_project(project)
        (project / ".claude").mkdir()
        (project / "copilot").mkdir()
        registered = register_defaults(ws, project)
        ids = [a[0] for a in registered]
        assert "claude-code" in ids
        assert "copilot" in ids
        roster = load_roster(ws)
        assert "claude-code" in roster
        assert "copilot" in roster

    def test_skips_existing(self, project):
        ws = init_project(project)
        (project / ".claude").mkdir()
        # First call registers
        register_defaults(ws, project)
        # Second call skips
        registered = register_defaults(ws, project)
        assert registered == []

    def test_role_assignment(self, project):
        ws = init_project(project)
        (project / ".claude").mkdir()
        (project / "copilot").mkdir()
        register_defaults(ws, project)
        roster = load_roster(ws)
        assert roster["claude-code"].role == "coordinator"
        assert roster["copilot"].role == "executor"


class TestInitCLI:
    def test_init_with_register_defaults(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        (tmp_path / "copilot").mkdir()
        result = subprocess.run(
            [sys.executable, "-m", "owlscale", "init", "--register-defaults"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "Claude Code" in result.stdout
        assert "GitHub Copilot" in result.stdout

    def test_init_register_no_agents(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "owlscale", "init", "--register-defaults"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "No new agents detected" in result.stdout

    def test_init_without_flag_no_register(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        result = subprocess.run(
            [sys.executable, "-m", "owlscale", "init", "--yes", "--no-launch"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert result.returncode == 0
        # init-v2 auto-detects; workspace should be created successfully
        assert ".owlscale/" in result.stdout

    def test_register_on_existing_workspace(self, tmp_path):
        # Init first without flag
        subprocess.run(
            [sys.executable, "-m", "owlscale", "init"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        # Add a marker
        (tmp_path / ".cursor").mkdir()
        # Re-init with --register-defaults
        result = subprocess.run(
            [sys.executable, "-m", "owlscale", "init", "--register-defaults"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "Cursor" in result.stdout
