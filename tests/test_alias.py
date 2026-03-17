"""Tests for owlscale alias module."""

import json
import sys
import os
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
CLI_ENV = {**os.environ, "PYTHONPATH": PROJECT_ROOT}

from owlscale.alias import set_alias, remove_alias, list_aliases, resolve_alias
from owlscale.core import init_project, add_agent, pack_task, dispatch_task


def init_ws(tmp_path: Path) -> Path:
    return init_project(tmp_path)


# ---------------------------------------------------------------------------
# TestSetAlias
# ---------------------------------------------------------------------------

class TestSetAlias:
    def test_sets_alias(self, tmp_path):
        ws = init_ws(tmp_path)
        set_alias(ws, "cc", "claude-code")
        assert list_aliases(ws)["cc"] == "claude-code"

    def test_overwrite_alias(self, tmp_path):
        ws = init_ws(tmp_path)
        set_alias(ws, "cc", "claude-code")
        set_alias(ws, "cc", "claude-code-v2")
        assert list_aliases(ws)["cc"] == "claude-code-v2"

    def test_multiple_aliases(self, tmp_path):
        ws = init_ws(tmp_path)
        set_alias(ws, "cc", "claude-code")
        set_alias(ws, "cp", "copilot")
        aliases = list_aliases(ws)
        assert "cc" in aliases
        assert "cp" in aliases


# ---------------------------------------------------------------------------
# TestRemoveAlias
# ---------------------------------------------------------------------------

class TestRemoveAlias:
    def test_removes_alias(self, tmp_path):
        ws = init_ws(tmp_path)
        set_alias(ws, "cc", "claude-code")
        remove_alias(ws, "cc")
        assert "cc" not in list_aliases(ws)

    def test_missing_alias_raises(self, tmp_path):
        ws = init_ws(tmp_path)
        with pytest.raises(KeyError, match="nonexistent"):
            remove_alias(ws, "nonexistent")

    def test_other_aliases_preserved(self, tmp_path):
        ws = init_ws(tmp_path)
        set_alias(ws, "cc", "claude-code")
        set_alias(ws, "cp", "copilot")
        remove_alias(ws, "cc")
        assert "cp" in list_aliases(ws)


# ---------------------------------------------------------------------------
# TestListAliases
# ---------------------------------------------------------------------------

class TestListAliases:
    def test_empty_when_no_file(self, tmp_path):
        ws = init_ws(tmp_path)
        assert list_aliases(ws) == {}

    def test_returns_all(self, tmp_path):
        ws = init_ws(tmp_path)
        set_alias(ws, "a", "agent-a")
        set_alias(ws, "b", "agent-b")
        aliases = list_aliases(ws)
        assert len(aliases) == 2


# ---------------------------------------------------------------------------
# TestResolveAlias
# ---------------------------------------------------------------------------

class TestResolveAlias:
    def test_resolves_known_alias(self, tmp_path):
        ws = init_ws(tmp_path)
        set_alias(ws, "cc", "claude-code")
        assert resolve_alias(ws, "cc") == "claude-code"

    def test_passthrough_unknown(self, tmp_path):
        ws = init_ws(tmp_path)
        assert resolve_alias(ws, "unknown-agent") == "unknown-agent"

    def test_chained_alias(self, tmp_path):
        ws = init_ws(tmp_path)
        set_alias(ws, "a", "b")
        set_alias(ws, "b", "claude-code")
        assert resolve_alias(ws, "a") == "claude-code"

    def test_circular_alias_terminates(self, tmp_path):
        ws = init_ws(tmp_path)
        set_alias(ws, "a", "b")
        set_alias(ws, "b", "a")
        result = resolve_alias(ws, "a")
        assert result in ("a", "b")

    def test_no_aliases_file(self, tmp_path):
        ws = init_ws(tmp_path)
        assert resolve_alias(ws, "some-agent") == "some-agent"


# ---------------------------------------------------------------------------
# TestAliasWiredIntoDispatch
# ---------------------------------------------------------------------------

class TestAliasWiredIntoDispatch:
    def _run(self, tmp_path, *args):
        return subprocess.run(
            [sys.executable, "-m", "owlscale"] + list(args),
            capture_output=True, text=True, env=CLI_ENV, cwd=tmp_path,
        )

    def test_dispatch_resolves_alias(self, tmp_path):
        ws = init_ws(tmp_path)
        add_agent(ws, "claude-code", "Claude Code", "executor")
        pack_task(ws, "t1", "Do something")
        set_alias(ws, "cc", "claude-code")

        result = self._run(tmp_path, "dispatch", "t1", "cc")
        assert result.returncode == 0
        assert "claude-code" in result.stdout

    def test_dispatch_passthrough_when_no_alias(self, tmp_path):
        ws = init_ws(tmp_path)
        add_agent(ws, "copilot", "Copilot", "executor")
        pack_task(ws, "t1", "Do something")

        result = self._run(tmp_path, "dispatch", "t1", "copilot")
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# TestAliasCli
# ---------------------------------------------------------------------------

class TestAliasCli:
    def _run(self, tmp_path, *args):
        return subprocess.run(
            [sys.executable, "-m", "owlscale"] + list(args),
            capture_output=True, text=True, env=CLI_ENV, cwd=tmp_path,
        )

    def test_set_alias_cli(self, tmp_path):
        init_ws(tmp_path)
        result = self._run(tmp_path, "alias", "set", "cc", "claude-code")
        assert result.returncode == 0
        assert "cc" in result.stdout

    def test_list_empty(self, tmp_path):
        init_ws(tmp_path)
        result = self._run(tmp_path, "alias", "list")
        assert result.returncode == 0
        assert "No aliases" in result.stdout

    def test_list_shows_aliases(self, tmp_path):
        ws = init_ws(tmp_path)
        set_alias(ws, "cc", "claude-code")
        result = self._run(tmp_path, "alias", "list")
        assert "cc" in result.stdout
        assert "claude-code" in result.stdout

    def test_remove_alias_cli(self, tmp_path):
        ws = init_ws(tmp_path)
        set_alias(ws, "cc", "claude-code")
        result = self._run(tmp_path, "alias", "remove", "cc")
        assert result.returncode == 0
        assert "cc" not in list_aliases(ws)

    def test_remove_missing_alias_fails(self, tmp_path):
        init_ws(tmp_path)
        result = self._run(tmp_path, "alias", "remove", "nonexistent")
        assert result.returncode != 0
