"""Tests for owlscale.launch module."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from owlscale.launch import (
    _launch_ghostty,
    _launch_iterm2,
    _launch_system_terminal,
    _launch_tmux,
    build_env,
    infer_launch_config,
    launch_agent,
)
from owlscale.models import Agent, AgentRole


# ---------------------------------------------------------------------------
# Helper: create a minimal Agent
# ---------------------------------------------------------------------------

def _agent(
    agent_id="copilot-opus",
    name="Copilot",
    role="executor",
    tool=None,
    launch=None,
) -> Agent:
    return Agent(
        id=agent_id,
        name=name,
        role=AgentRole(role),
        tool=tool,
        launch=launch or {},
    )


def _init(tmp_path: Path) -> Path:
    ws = tmp_path / ".owlscale"
    ws.mkdir()
    return ws


# ---------------------------------------------------------------------------
# build_env
# ---------------------------------------------------------------------------

class TestBuildEnv:
    def test_injects_owlscale_agent(self, tmp_path):
        ws = _init(tmp_path)
        agent = _agent("copilot-opus")
        env = build_env(agent, ws)
        assert env["OWLSCALE_AGENT"] == "copilot-opus"

    def test_injects_owlscale_dir(self, tmp_path):
        ws = _init(tmp_path)
        agent = _agent("copilot-opus")
        env = build_env(agent, ws)
        assert env["OWLSCALE_DIR"] == str(ws.resolve())

    def test_inherits_os_environ(self, tmp_path):
        ws = _init(tmp_path)
        agent = _agent()
        env = build_env(agent, ws)
        # PATH should be inherited
        assert "PATH" in env

    def test_agent_launch_env_merged(self, tmp_path):
        ws = _init(tmp_path)
        agent = _agent(launch={"env": {"MY_VAR": "hello"}})
        env = build_env(agent, ws)
        assert env["MY_VAR"] == "hello"

    def test_agent_launch_env_overrides(self, tmp_path):
        ws = _init(tmp_path)
        agent = _agent(launch={"env": {"OWLSCALE_AGENT": "override"}})
        env = build_env(agent, ws)
        # agent.launch["env"] is merged after the defaults
        assert env["OWLSCALE_AGENT"] == "override"

    def test_no_launch_env_no_crash(self, tmp_path):
        ws = _init(tmp_path)
        agent = _agent(launch={})
        env = build_env(agent, ws)
        assert "OWLSCALE_AGENT" in env


# ---------------------------------------------------------------------------
# infer_launch_config
# ---------------------------------------------------------------------------

class TestInferLaunchConfig:
    def _mock_detect(self, found_terminals: list[str]):
        """Create a fake DetectionResult with specified terminals found."""
        from dataclasses import dataclass, field
        from typing import Optional

        @dataclass
        class TerminalInfo:
            id: str
            name: str
            found: bool
            path: Optional[str] = None
            adapter: Optional[str] = None

        @dataclass
        class DetectionResult:
            tools: dict
            terminals: dict

        terminals = {}
        for tid in ["ghostty", "iterm2", "tmux"]:
            terminals[tid] = TerminalInfo(
                id=tid, name=tid.capitalize(),
                found=(tid in found_terminals),
                path=f"/usr/{tid}" if tid in found_terminals else None,
                adapter=tid,
            )
        return DetectionResult(tools={}, terminals=terminals)

    def test_maps_claude_code_to_claude_cmd(self, tmp_path):
        agent = _agent(tool="claude-code")
        config = infer_launch_config(agent, self._mock_detect(["ghostty"]))
        assert config["cmd"] == ["claude"]

    def test_maps_codex_to_codex_cmd(self, tmp_path):
        agent = _agent(tool="codex")
        config = infer_launch_config(agent, self._mock_detect([]))
        assert config["cmd"] == ["codex"]

    def test_maps_copilot_cli(self, tmp_path):
        agent = _agent(tool="copilot-cli")
        config = infer_launch_config(agent, self._mock_detect([]))
        assert config["cmd"] == ["gh", "copilot"]

    def test_unknown_tool_yields_empty_cmd(self, tmp_path):
        agent = _agent(tool="unknown-tool")
        config = infer_launch_config(agent, self._mock_detect([]))
        assert config["cmd"] == []

    def test_picks_ghostty_first(self, tmp_path):
        agent = _agent(tool="claude-code")
        config = infer_launch_config(agent, self._mock_detect(["ghostty", "tmux"]))
        assert config["terminal"] == "ghostty"

    def test_falls_back_to_tmux(self, tmp_path):
        agent = _agent(tool="claude-code")
        config = infer_launch_config(agent, self._mock_detect(["tmux"]))
        assert config["terminal"] == "tmux"

    def test_falls_back_to_system_when_nothing_found(self, tmp_path):
        agent = _agent(tool="claude-code")
        config = infer_launch_config(agent, self._mock_detect([]))
        assert config["terminal"] == "system"

    def test_window_title_is_agent_id(self, tmp_path):
        agent = _agent("my-agent", tool="claude-code")
        config = infer_launch_config(agent, self._mock_detect([]))
        assert config["window_title"] == "my-agent"

    def test_no_detect_result_still_returns_config(self, tmp_path):
        """When detect_result is None and detect.scan() raises, config is still returned."""
        agent = _agent(tool="claude-code")
        # Pass detect_result=None; launch.py will try importing detect and fall back gracefully
        config = infer_launch_config(agent, detect_result=None)
        assert "terminal" in config
        assert "cmd" in config


# ---------------------------------------------------------------------------
# _launch_ghostty
# ---------------------------------------------------------------------------

class TestLaunchGhostty:
    def test_calls_osascript(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = _launch_ghostty(["claude"], {"OWLSCALE_AGENT": "a", "OWLSCALE_DIR": "/ws"})
        assert mock_run.called
        assert result is True

    def test_returns_false_on_nonzero_exit(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = _launch_ghostty(["claude"], {})
        assert result is False

    def test_returns_false_on_exception(self):
        with patch("subprocess.run", side_effect=Exception("no osascript")):
            result = _launch_ghostty(["claude"], {})
        assert result is False

    def test_script_contains_cmd(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            _launch_ghostty(["claude"], {"OWLSCALE_AGENT": "cc", "OWLSCALE_DIR": "/ws"})
        script = mock_run.call_args[0][0][2]
        assert "claude" in script


# ---------------------------------------------------------------------------
# _launch_iterm2
# ---------------------------------------------------------------------------

class TestLaunchIterm2:
    def test_calls_osascript(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = _launch_iterm2(["claude"], {"OWLSCALE_AGENT": "a", "OWLSCALE_DIR": "/ws"})
        assert result is True

    def test_returns_false_on_exception(self):
        with patch("subprocess.run", side_effect=Exception("no iterm2")):
            result = _launch_iterm2(["claude"], {})
        assert result is False


# ---------------------------------------------------------------------------
# _launch_tmux
# ---------------------------------------------------------------------------

class TestLaunchTmux:
    def test_calls_tmux_new_window(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = _launch_tmux(["claude"], {"OWLSCALE_AGENT": "a", "OWLSCALE_DIR": "/ws"})
        first_call_args = mock_run.call_args_list[0][0][0]
        assert "tmux" in first_call_args
        assert "new-window" in first_call_args

    def test_returns_false_on_exception(self):
        with patch("subprocess.run", side_effect=Exception("no tmux")):
            result = _launch_tmux(["claude"], {})
        assert result is False

    def test_returns_false_when_tmux_fails(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            result = _launch_tmux(["claude"], {})
        assert result is False


# ---------------------------------------------------------------------------
# _launch_system_terminal
# ---------------------------------------------------------------------------

class TestLaunchSystemTerminal:
    def test_returns_false_on_non_darwin(self):
        with patch("owlscale.launch.sys") as mock_sys:
            mock_sys.platform = "linux"
            result = _launch_system_terminal(["claude"], {})
        assert result is False

    def test_calls_osascript_on_darwin(self):
        with patch("owlscale.launch.sys") as mock_sys, \
             patch("subprocess.run") as mock_run:
            mock_sys.platform = "darwin"
            mock_run.return_value = MagicMock(returncode=0)
            result = _launch_system_terminal(["claude"], {})
        assert result is True


# ---------------------------------------------------------------------------
# launch_agent
# ---------------------------------------------------------------------------

class TestLaunchAgent:
    def test_uses_agent_launch_config(self, tmp_path):
        ws = _init(tmp_path)
        agent = _agent(launch={"terminal": "ghostty", "cmd": ["claude"], "window_title": "cc"})
        with patch("owlscale.launch._launch_ghostty", return_value=True) as mock_launch:
            result = launch_agent(agent, ws)
        mock_launch.assert_called_once()
        assert result is True

    def test_infers_config_when_no_launch(self, tmp_path):
        ws = _init(tmp_path)
        agent = _agent(tool="claude-code", launch={})
        with patch("owlscale.launch.infer_launch_config") as mock_infer, \
             patch("owlscale.launch._launch_system_terminal", return_value=True):
            mock_infer.return_value = {"terminal": "system", "cmd": ["claude"],
                                       "env": {}, "window_title": "copilot-opus"}
            launch_agent(agent, ws)
        mock_infer.assert_called_once_with(agent)

    def test_returns_false_on_unknown_terminal(self, tmp_path):
        ws = _init(tmp_path)
        agent = _agent(launch={"terminal": "unknown-term", "cmd": ["claude"]})
        result = launch_agent(agent, ws)
        assert result is False

    def test_non_fatal_on_exception(self, tmp_path):
        ws = _init(tmp_path)
        agent = _agent(launch={"terminal": "ghostty", "cmd": ["claude"]})
        with patch("owlscale.launch._launch_ghostty", side_effect=RuntimeError("boom")):
            result = launch_agent(agent, ws)
        assert result is False


# ---------------------------------------------------------------------------
# CLI: owlscale launch
# ---------------------------------------------------------------------------

class TestLaunchCLI:
    def _run(self, tmp_path, *args):
        import subprocess as sp
        return sp.run(
            [sys.executable, "-m", "owlscale"] + list(args),
            capture_output=True, text=True, cwd=str(tmp_path),
        )

    def test_launch_unknown_agent_exits_nonzero(self, tmp_path):
        self._run(tmp_path, "init")
        result = self._run(tmp_path, "launch", "nobody")
        assert result.returncode != 0

    def test_launch_all_exits_0_with_no_agents(self, tmp_path):
        self._run(tmp_path, "init")
        result = self._run(tmp_path, "launch", "--all")
        assert result.returncode == 0
