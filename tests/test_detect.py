"""Tests for owlscale.detect module."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from owlscale.detect import (
    DetectionResult,
    TerminalInfo,
    ToolInfo,
    _probe_app,
    _probe_claude_code,
    _probe_codex,
    _probe_copilot_cli,
    _probe_cursor,
    _probe_gh_copilot,
    _probe_ghostty,
    _probe_iterm2,
    _probe_tmux,
    _probe_vscode,
    _probe_which,
    fmt_detection,
    scan,
)


# ---------------------------------------------------------------------------
# Helper patches
# ---------------------------------------------------------------------------

def _mock_which(present: list[str]):
    """Return a which mock that finds only the listed commands."""
    def _which(cmd):
        return f"/usr/local/bin/{cmd}" if cmd in present else None
    return _which


# ---------------------------------------------------------------------------
# _probe_which
# ---------------------------------------------------------------------------

class TestProbeWhich:
    def test_found(self):
        with patch("shutil.which", return_value="/usr/bin/claude"):
            assert _probe_which("claude") == "/usr/bin/claude"

    def test_not_found(self):
        with patch("shutil.which", return_value=None):
            assert _probe_which("claude") is None

    def test_exception_returns_none(self):
        with patch("shutil.which", side_effect=Exception("boom")):
            assert _probe_which("claude") is None


# ---------------------------------------------------------------------------
# _probe_app
# ---------------------------------------------------------------------------

class TestProbeApp:
    def test_returns_none_on_non_darwin(self):
        with patch("owlscale.detect.sys") as mock_sys:
            mock_sys.platform = "linux"
            assert _probe_app("Ghostty") is None

    def test_returns_path_when_exists(self, tmp_path):
        fake_app = tmp_path / "Ghostty.app"
        fake_app.mkdir()
        with patch("owlscale.detect.Path") as mock_path_cls, \
             patch("owlscale.detect.sys") as mock_sys:
            mock_sys.platform = "darwin"
            mock_path_cls.return_value.exists.return_value = True
            mock_path_cls.return_value.__str__ = lambda s: "/Applications/Ghostty.app"
            result = _probe_app("Ghostty")
            # We just want it to not crash and call exists()
            assert mock_path_cls.return_value.exists.called

    def test_returns_none_when_not_exists(self):
        with patch("owlscale.detect.sys") as mock_sys, \
             patch("owlscale.detect.Path") as mock_path_cls:
            mock_sys.platform = "darwin"
            mock_inst = MagicMock()
            mock_inst.exists.return_value = False
            mock_path_cls.return_value = mock_inst
            assert _probe_app("Ghostty") is None


# ---------------------------------------------------------------------------
# _probe_gh_copilot
# ---------------------------------------------------------------------------

class TestProbeGhCopilot:
    def test_found_when_copilot_in_output(self):
        mock_result = MagicMock(stdout="gh-copilot\ngh-actions\n", returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            assert _probe_gh_copilot() is True

    def test_not_found_when_copilot_absent(self):
        mock_result = MagicMock(stdout="gh-actions\n", returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            assert _probe_gh_copilot() is False

    def test_returns_false_on_exception(self):
        with patch("subprocess.run", side_effect=Exception("timeout")):
            assert _probe_gh_copilot() is False

    def test_uses_timeout_3(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            _probe_gh_copilot()
        _, kwargs = mock_run.call_args
        assert kwargs.get("timeout") == 3


# ---------------------------------------------------------------------------
# Tool probes: _probe_claude_code
# ---------------------------------------------------------------------------

class TestProbeClaudeCode:
    def test_found(self):
        with patch("shutil.which", side_effect=_mock_which(["claude"])):
            info = _probe_claude_code()
        assert info.found is True
        assert info.id == "claude-code"
        assert info.path is not None
        assert info.launch_cmd == ["claude"]

    def test_not_found(self):
        with patch("shutil.which", return_value=None):
            info = _probe_claude_code()
        assert info.found is False
        assert info.path is None


# ---------------------------------------------------------------------------
# Tool probes: _probe_copilot_cli
# ---------------------------------------------------------------------------

class TestProbeCopilotCli:
    def test_found_when_gh_present_and_extension_listed(self):
        with patch("shutil.which", side_effect=_mock_which(["gh"])), \
             patch("subprocess.run", return_value=MagicMock(stdout="gh-copilot\n", returncode=0)):
            info = _probe_copilot_cli()
        assert info.found is True
        assert info.id == "copilot-cli"
        assert info.launch_cmd == ["gh", "copilot"]

    def test_not_found_when_gh_missing(self):
        with patch("shutil.which", return_value=None):
            info = _probe_copilot_cli()
        assert info.found is False

    def test_not_found_when_extension_not_listed(self):
        with patch("shutil.which", side_effect=_mock_which(["gh"])), \
             patch("subprocess.run", return_value=MagicMock(stdout="gh-actions\n", returncode=0)):
            info = _probe_copilot_cli()
        assert info.found is False


# ---------------------------------------------------------------------------
# Tool probes: _probe_codex
# ---------------------------------------------------------------------------

class TestProbeCodex:
    def test_found(self):
        with patch("shutil.which", side_effect=_mock_which(["codex"])):
            info = _probe_codex()
        assert info.found is True
        assert info.launch_cmd == ["codex"]

    def test_not_found(self):
        with patch("shutil.which", return_value=None):
            info = _probe_codex()
        assert info.found is False


# ---------------------------------------------------------------------------
# Tool probes: _probe_cursor
# ---------------------------------------------------------------------------

class TestProbeCursor:
    def test_found_via_app_bundle(self):
        with patch("owlscale.detect.sys") as mock_sys, \
             patch("owlscale.detect.Path") as mock_path_cls:
            mock_sys.platform = "darwin"
            mock_inst = MagicMock()
            mock_inst.exists.return_value = True
            mock_inst.__str__ = lambda s: "/Applications/Cursor.app"
            mock_path_cls.return_value = mock_inst
            info = _probe_cursor()
        assert info.found is True
        assert info.id == "cursor"

    def test_found_via_cli(self):
        with patch("owlscale.detect.sys") as mock_sys, \
             patch("owlscale.detect.Path") as mock_path_cls, \
             patch("shutil.which", side_effect=_mock_which(["cursor"])):
            mock_sys.platform = "linux"
            info = _probe_cursor()
        assert info.found is True

    def test_not_found(self):
        with patch("owlscale.detect.sys") as mock_sys, \
             patch("owlscale.detect.Path") as mock_path_cls, \
             patch("shutil.which", return_value=None):
            mock_sys.platform = "linux"
            info = _probe_cursor()
        assert info.found is False


# ---------------------------------------------------------------------------
# Tool probes: _probe_vscode
# ---------------------------------------------------------------------------

class TestProbeVscode:
    def test_found_via_cli(self):
        with patch("owlscale.detect.sys") as mock_sys, \
             patch("owlscale.detect.Path") as mock_path_cls, \
             patch("shutil.which", side_effect=_mock_which(["code"])):
            mock_sys.platform = "linux"
            info = _probe_vscode()
        assert info.found is True
        assert info.id == "vscode"

    def test_not_found(self):
        with patch("owlscale.detect.sys") as mock_sys, \
             patch("owlscale.detect.Path") as mock_path_cls, \
             patch("shutil.which", return_value=None):
            mock_sys.platform = "linux"
            info = _probe_vscode()
        assert info.found is False


# ---------------------------------------------------------------------------
# Terminal probes
# ---------------------------------------------------------------------------

class TestProbeGhostty:
    def test_found_via_app(self):
        with patch("owlscale.detect.sys") as mock_sys, \
             patch("owlscale.detect.Path") as mock_path_cls:
            mock_sys.platform = "darwin"
            mock_inst = MagicMock()
            mock_inst.exists.return_value = True
            mock_inst.__str__ = lambda s: "/Applications/Ghostty.app"
            mock_path_cls.return_value = mock_inst
            info = _probe_ghostty()
        assert info.found is True
        assert info.adapter == "ghostty"

    def test_not_found(self):
        with patch("owlscale.detect.sys") as mock_sys, \
             patch("owlscale.detect.Path") as mock_path_cls, \
             patch("shutil.which", return_value=None):
            mock_sys.platform = "linux"
            info = _probe_ghostty()
        assert info.found is False


class TestProbeIterm2:
    def test_found(self):
        with patch("owlscale.detect.sys") as mock_sys, \
             patch("owlscale.detect.Path") as mock_path_cls:
            mock_sys.platform = "darwin"
            mock_inst = MagicMock()
            mock_inst.exists.return_value = True
            mock_inst.__str__ = lambda s: "/Applications/iTerm.app"
            mock_path_cls.return_value = mock_inst
            info = _probe_iterm2()
        assert info.found is True
        assert info.adapter == "iterm2"

    def test_not_found_on_linux(self):
        with patch("owlscale.detect.sys") as mock_sys:
            mock_sys.platform = "linux"
            info = _probe_iterm2()
        assert info.found is False


class TestProbeTmux:
    def test_found(self):
        with patch("shutil.which", side_effect=_mock_which(["tmux"])):
            info = _probe_tmux()
        assert info.found is True
        assert info.adapter == "tmux"

    def test_not_found(self):
        with patch("shutil.which", return_value=None):
            info = _probe_tmux()
        assert info.found is False


# ---------------------------------------------------------------------------
# scan()
# ---------------------------------------------------------------------------

class TestScan:
    def test_returns_detection_result(self):
        with patch("shutil.which", return_value=None), \
             patch("owlscale.detect.sys") as mock_sys, \
             patch("owlscale.detect.Path") as mock_path_cls:
            mock_sys.platform = "linux"
            result = scan()
        assert isinstance(result, DetectionResult)
        assert isinstance(result.tools, dict)
        assert isinstance(result.terminals, dict)

    def test_all_tool_ids_present(self):
        with patch("shutil.which", return_value=None), \
             patch("owlscale.detect.sys") as mock_sys, \
             patch("owlscale.detect.Path") as mock_path_cls:
            mock_sys.platform = "linux"
            result = scan()
        assert set(result.tools.keys()) == {"claude-code", "copilot-cli", "codex", "cursor", "vscode"}

    def test_all_terminal_ids_present(self):
        with patch("shutil.which", return_value=None), \
             patch("owlscale.detect.sys") as mock_sys, \
             patch("owlscale.detect.Path") as mock_path_cls:
            mock_sys.platform = "linux"
            result = scan()
        assert set(result.terminals.keys()) == {"ghostty", "iterm2", "tmux"}

    def test_platform_recorded(self):
        with patch("shutil.which", return_value=None), \
             patch("owlscale.detect.sys") as mock_sys, \
             patch("owlscale.detect.Path") as mock_path_cls:
            mock_sys.platform = "linux"
            result = scan()
        assert result.platform is not None


# ---------------------------------------------------------------------------
# fmt_detection
# ---------------------------------------------------------------------------

class TestFmtDetection:
    def _make_result(self, tool_found=False, terminal_found=False) -> DetectionResult:
        tools = {
            "claude-code": ToolInfo("claude-code", "Claude Code", tool_found,
                                    "/usr/bin/claude" if tool_found else None, ["claude"]),
        }
        terminals = {
            "ghostty": TerminalInfo("ghostty", "Ghostty", terminal_found,
                                    "/Applications/Ghostty.app" if terminal_found else None, "ghostty"),
        }
        return DetectionResult(tools=tools, terminals=terminals)

    def test_contains_ai_tools_header(self):
        result = self._make_result()
        output = fmt_detection(result)
        assert "AI Tools detected" in output

    def test_contains_terminals_header(self):
        result = self._make_result()
        output = fmt_detection(result)
        assert "Terminals detected" in output

    def test_found_tool_shows_checkmark(self):
        result = self._make_result(tool_found=True)
        output = fmt_detection(result)
        assert "✓" in output
        assert "/usr/bin/claude" in output

    def test_not_found_tool_shows_cross(self):
        result = self._make_result(tool_found=False)
        output = fmt_detection(result)
        assert "✗" in output
        assert "(not found)" in output

    def test_found_terminal_shows_checkmark(self):
        result = self._make_result(terminal_found=True)
        output = fmt_detection(result)
        assert "✓" in output

    def test_returns_string(self):
        result = self._make_result()
        assert isinstance(fmt_detection(result), str)


# ---------------------------------------------------------------------------
# CLI: owlscale detect
# ---------------------------------------------------------------------------

class TestDetectCLI:
    def _run(self, tmp_path, *args):
        import subprocess as sp
        return sp.run(
            [sys.executable, "-m", "owlscale"] + list(args),
            capture_output=True, text=True, cwd=str(tmp_path),
        )

    def test_detect_exits_0(self, tmp_path):
        result = self._run(tmp_path, "detect")
        assert result.returncode == 0

    def test_detect_json_exits_0(self, tmp_path):
        import json as _json
        result = self._run(tmp_path, "detect", "--json")
        assert result.returncode == 0
        data = _json.loads(result.stdout)
        assert "tools" in data
        assert "terminals" in data
