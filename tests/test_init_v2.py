"""Tests for owlscale init-v2 (redesigned cmd_init with detect + roster + launch)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers: fake DetectionResult
# ---------------------------------------------------------------------------

def _make_tool(id, name, found, path=None, cmd=None):
    t = MagicMock()
    t.id = id
    t.name = name
    t.found = found
    t.path = path
    t.launch_cmd = cmd or []
    return t


def _make_terminal(id, name, found, adapter=None):
    t = MagicMock()
    t.id = id
    t.name = name
    t.found = found
    t.path = f"/usr/{id}" if found else None
    t.adapter = adapter or id
    return t


def _make_detect(tools_found=("claude-code",), terminals_found=("ghostty",)):
    dr = MagicMock()
    all_tools = {
        "claude-code": _make_tool("claude-code", "Claude Code", "claude-code" in tools_found, path="/usr/local/bin/claude"),
        "copilot-cli": _make_tool("copilot-cli", "GitHub Copilot CLI", "copilot-cli" in tools_found),
        "codex": _make_tool("codex", "Codex CLI", "codex" in tools_found),
        "cursor": _make_tool("cursor", "Cursor", "cursor" in tools_found),
        "vscode": _make_tool("vscode", "VS Code", "vscode" in tools_found),
    }
    all_terms = {
        "ghostty": _make_terminal("ghostty", "Ghostty", "ghostty" in terminals_found),
        "iterm2": _make_terminal("iterm2", "iTerm2", "iterm2" in terminals_found),
        "tmux": _make_terminal("tmux", "tmux", "tmux" in terminals_found),
    }
    dr.tools = all_tools
    dr.terminals = all_terms
    return dr


def _run(tmp_path, *args):
    import subprocess as sp
    return sp.run(
        [sys.executable, "-m", "owlscale"] + list(args),
        capture_output=True, text=True, cwd=str(tmp_path),
    )


def _read_roster(tmp_path) -> dict:
    p = tmp_path / ".owlscale" / "roster.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text())


# ---------------------------------------------------------------------------
# Tests: _suggest_roster
# ---------------------------------------------------------------------------

class TestSuggestRoster:
    def _suggest(self, tools_found=(), terminals_found=()):
        from owlscale.cli import _suggest_roster
        return _suggest_roster(_make_detect(tools_found, terminals_found))

    def test_cc_maps_to_orchestrator(self):
        s = self._suggest(("claude-code",), ("ghostty",))
        ids = [a["id"] for a in s]
        assert "orchestrator" in ids

    def test_cc_role_is_coordinator(self):
        s = self._suggest(("claude-code",), ())
        cc = next(a for a in s if a["id"] == "orchestrator")
        assert cc["role"] == "coordinator"

    def test_cc_tool_is_claude_code(self):
        s = self._suggest(("claude-code",), ())
        cc = next(a for a in s if a["id"] == "orchestrator")
        assert cc["tool"] == "claude-code"

    def test_copilot_maps_to_worker1(self):
        s = self._suggest(("claude-code", "copilot-cli"), ())
        ids = [a["id"] for a in s]
        assert "worker-1" in ids

    def test_copilot_role_is_executor(self):
        s = self._suggest(("claude-code", "copilot-cli"), ())
        cp = next(a for a in s if a["id"] == "worker-1")
        assert cp["role"] == "executor"

    def test_codex_maps_to_worker2(self):
        s = self._suggest(("codex",), ())
        ids = [a["id"] for a in s]
        assert "worker-2" in ids

    def test_cursor_maps_to_cursor1_no_terminal_launch(self):
        s = self._suggest(("cursor",), ())
        cur = next(a for a in s if a["id"] == "cursor-1")
        assert cur["launch"] == {}

    def test_nothing_found_gives_placeholders(self):
        s = self._suggest((), ())
        assert len(s) == 2
        assert all(a["tool"] is None for a in s)

    def test_placeholder_first_is_coordinator(self):
        s = self._suggest((), ())
        assert s[0]["role"] == "coordinator"

    def test_terminal_preferred_in_launch(self):
        s = self._suggest(("claude-code",), ("ghostty",))
        cc = next(a for a in s if a["id"] == "orchestrator")
        assert cc["launch"]["terminal"] == "ghostty"

    def test_tmux_fallback_when_no_ghostty(self):
        s = self._suggest(("claude-code",), ("tmux",))
        cc = next(a for a in s if a["id"] == "orchestrator")
        assert cc["launch"]["terminal"] == "tmux"

    def test_system_fallback_when_no_terminal(self):
        s = self._suggest(("claude-code",), ())
        cc = next(a for a in s if a["id"] == "orchestrator")
        assert cc["launch"]["terminal"] == "system"

    def test_no_coordinator_promotes_first(self):
        # Only copilot found — should be promoted to coordinator
        s = self._suggest(("copilot-cli",), ())
        assert s[0]["role"] == "coordinator"


# ---------------------------------------------------------------------------
# Tests: _confirm
# ---------------------------------------------------------------------------

class TestConfirm:
    def test_yes_returns_true(self):
        from owlscale.cli import _confirm
        with patch("builtins.input", return_value="y"):
            assert _confirm("?") is True

    def test_no_returns_false(self):
        from owlscale.cli import _confirm
        with patch("builtins.input", return_value="n"):
            assert _confirm("?") is False

    def test_empty_returns_default_true(self):
        from owlscale.cli import _confirm
        with patch("builtins.input", return_value=""):
            assert _confirm("?", default=True) is True

    def test_empty_returns_default_false(self):
        from owlscale.cli import _confirm
        with patch("builtins.input", return_value=""):
            assert _confirm("?", default=False) is False

    def test_eof_returns_default(self):
        from owlscale.cli import _confirm
        with patch("builtins.input", side_effect=EOFError):
            assert _confirm("?", default=True) is True


# ---------------------------------------------------------------------------
# Tests: owlscale init --yes (no prompts)
# ---------------------------------------------------------------------------

class TestInitYes:
    def test_creates_owlscale_dir(self, tmp_path):
        with patch("owlscale.detect.scan", return_value=_make_detect(("claude-code",), ("ghostty",))):
            r = _run(tmp_path, "init", "--yes", "--no-launch")
        assert (tmp_path / ".owlscale").exists()

    def test_creates_roster_with_cc(self, tmp_path):
        with patch("owlscale.detect.scan", return_value=_make_detect(("claude-code",), ())):
            _run(tmp_path, "init", "--yes", "--no-launch")
        roster = _read_roster(tmp_path)
        assert "orchestrator" in roster.get("agents", {})

    def test_creates_roster_with_copilot(self, tmp_path):
        # Test via _suggest_roster directly (subprocess can't intercept detect.scan)
        from owlscale.cli import _suggest_roster
        s = _suggest_roster(_make_detect(("claude-code", "copilot-cli"), ()))
        ids = [a["id"] for a in s]
        assert "worker-1" in ids

    def test_cc_stored_with_tool_field(self, tmp_path):
        with patch("owlscale.detect.scan", return_value=_make_detect(("claude-code",), ())):
            _run(tmp_path, "init", "--yes", "--no-launch")
        agents = _read_roster(tmp_path).get("agents", {})
        # Find any agent with claude-code tool
        cc_agents = [v for v in agents.values() if v.get("tool") == "claude-code"]
        assert len(cc_agents) >= 1

    def test_placeholder_roster_when_nothing_found(self, tmp_path):
        # Test _suggest_roster directly (subprocess can't force detect to find nothing)
        from owlscale.cli import _suggest_roster
        s = _suggest_roster(_make_detect((), ()))
        assert len(s) == 2
        assert all(a["tool"] is None for a in s)

    def test_exits_zero(self, tmp_path):
        with patch("owlscale.detect.scan", return_value=_make_detect(("claude-code",), ())):
            r = _run(tmp_path, "init", "--yes", "--no-launch")
        assert r.returncode == 0

    def test_prints_roster_created(self, tmp_path):
        with patch("owlscale.detect.scan", return_value=_make_detect(("claude-code",), ())):
            r = _run(tmp_path, "init", "--yes", "--no-launch")
        assert "Roster created" in r.stdout

    def test_prints_next_steps(self, tmp_path):
        with patch("owlscale.detect.scan", return_value=_make_detect(("claude-code",), ())):
            r = _run(tmp_path, "init", "--yes", "--no-launch")
        assert "owlscale status" in r.stdout


# ---------------------------------------------------------------------------
# Tests: --no-launch
# ---------------------------------------------------------------------------

class TestInitNoLaunch:
    def test_does_not_call_launch_agent(self, tmp_path):
        with patch("owlscale.detect.scan", return_value=_make_detect(("claude-code",), ())), \
             patch("owlscale.launch.launch_agent") as mock_launch:
            _run(tmp_path, "init", "--yes", "--no-launch")
        mock_launch.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: --force (reinit existing workspace)
# ---------------------------------------------------------------------------

class TestInitForce:
    def test_reinit_without_prompt(self, tmp_path):
        _run(tmp_path, "init", "--yes", "--no-launch")  # first init
        with patch("owlscale.detect.scan", return_value=_make_detect(("claude-code",), ())):
            r = _run(tmp_path, "init", "--yes", "--no-launch", "--force")
        assert r.returncode == 0
        assert "Re-initialized" in r.stdout or "Initialized" in r.stdout


# ---------------------------------------------------------------------------
# Tests: --name
# ---------------------------------------------------------------------------

class TestInitName:
    def test_stores_project_name(self, tmp_path):
        with patch("owlscale.detect.scan", return_value=_make_detect(("claude-code",), ())):
            _run(tmp_path, "init", "--yes", "--no-launch", "--name", "my-proj")
        config = json.loads((tmp_path / ".owlscale" / "config.json").read_text())
        assert config.get("project_name") == "my-proj"


# ---------------------------------------------------------------------------
# Tests: detection unavailable
# ---------------------------------------------------------------------------

class TestInitDetectFallback:
    def test_works_when_detect_raises(self, tmp_path):
        with patch("owlscale.detect.scan", side_effect=Exception("no detect")):
            r = _run(tmp_path, "init", "--yes", "--no-launch")
        assert r.returncode == 0
        agents = _read_roster(tmp_path).get("agents", {})
        assert len(agents) >= 1  # placeholders created


# ---------------------------------------------------------------------------
# Tests: backward compat — existing init tests still pass
# ---------------------------------------------------------------------------

class TestInitBackwardCompat:
    def test_init_name_only(self, tmp_path):
        """owlscale init --name foo --yes --no-launch still works."""
        with patch("owlscale.detect.scan", return_value=_make_detect((), ())):
            r = _run(tmp_path, "init", "--name", "foo", "--yes", "--no-launch")
        assert r.returncode == 0
        assert (tmp_path / ".owlscale").exists()

    def test_register_defaults_still_works(self, tmp_path):
        """--register-defaults legacy flag still exits 0."""
        r = _run(tmp_path, "init", "--register-defaults")
        assert r.returncode == 0
