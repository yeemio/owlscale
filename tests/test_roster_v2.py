"""Tests for roster v2 Agent metadata compatibility."""

from __future__ import annotations

import json

import pytest

from owlscale.core import init_project, load_roster, save_roster
from owlscale.models import Agent, AgentRole


@pytest.fixture()
def workspace(tmp_path):
    return init_project(tmp_path)


class TestAgentModelV2:
    def test_from_dict_legacy_defaults_new_fields(self):
        agent = Agent.from_dict(
            "legacy",
            {
                "name": "Legacy Agent",
                "role": "executor",
                "strengths": ["python"],
                "constraints": {"shell": "limited"},
            },
        )

        assert agent.tool is None
        assert agent.delivery == {}
        assert agent.launch == {}

    def test_from_dict_reads_v2_fields(self):
        agent = Agent.from_dict(
            "cc-opus",
            {
                "name": "Claude Code Opus",
                "role": "coordinator",
                "tool": "claude-code",
                "delivery": {"mode": "ghostty-applescript", "target": "window-title"},
                "launch": {"command": ["claude"], "terminal": "ghostty"},
            },
        )

        assert agent.tool == "claude-code"
        assert agent.delivery["mode"] == "ghostty-applescript"
        assert agent.launch["command"] == ["claude"]

    def test_to_dict_omits_empty_v2_fields(self):
        agent = Agent(id="copilot", name="Copilot", role=AgentRole.executor)

        data = agent.to_dict()

        assert "tool" not in data
        assert "delivery" not in data
        assert "launch" not in data

    def test_to_dict_includes_populated_v2_fields(self):
        agent = Agent(
            id="copilot",
            name="Copilot",
            role=AgentRole.executor,
            tool="copilot-cli",
            delivery={"mode": "none"},
            launch={"command": ["gh", "copilot"]},
        )

        data = agent.to_dict()

        assert data["tool"] == "copilot-cli"
        assert data["delivery"] == {"mode": "none"}
        assert data["launch"] == {"command": ["gh", "copilot"]}

    def test_from_dict_ignores_invalid_v2_types(self):
        agent = Agent.from_dict(
            "bad-v2",
            {
                "name": "Bad V2",
                "role": "executor",
                "tool": ["claude"],
                "delivery": "ghostty",
                "launch": ["claude"],
            },
        )

        assert agent.tool is None
        assert agent.delivery == {}
        assert agent.launch == {}


class TestRosterRoundTripV2:
    def test_load_roster_preserves_v2_fields(self, workspace):
        roster_path = workspace / "roster.json"
        roster_path.write_text(
            json.dumps(
                {
                    "agents": {
                        "claude-code": {
                            "name": "Claude Code",
                            "role": "coordinator",
                            "tool": "claude-code",
                            "delivery": {"mode": "ghostty-applescript", "target": "window-title"},
                            "launch": {"command": ["claude"], "terminal": "ghostty"},
                        }
                    }
                },
                indent=2,
            )
        )

        roster = load_roster(workspace)

        assert roster["claude-code"].tool == "claude-code"
        assert roster["claude-code"].delivery["mode"] == "ghostty-applescript"
        assert roster["claude-code"].launch["terminal"] == "ghostty"

    def test_save_roster_round_trips_v2_fields(self, workspace):
        agents = {
            "copilot": Agent(
                id="copilot",
                name="GitHub Copilot",
                role=AgentRole.executor,
                tool="copilot-cli",
                delivery={"mode": "none"},
                launch={"command": ["gh", "copilot"], "terminal": "ghostty"},
            )
        }

        save_roster(workspace, agents)
        data = json.loads((workspace / "roster.json").read_text())

        assert data["agents"]["copilot"]["tool"] == "copilot-cli"
        assert data["agents"]["copilot"]["delivery"] == {"mode": "none"}
        assert data["agents"]["copilot"]["launch"]["command"] == ["gh", "copilot"]

    def test_legacy_roster_shape_stays_compact_for_default_agent(self, workspace):
        agents = {
            "basic": Agent(
                id="basic",
                name="Basic Agent",
                role=AgentRole.executor,
                strengths=[],
                constraints={},
            )
        }

        save_roster(workspace, agents)
        data = json.loads((workspace / "roster.json").read_text())

        assert data["agents"]["basic"] == {
            "name": "Basic Agent",
            "role": "executor",
            "strengths": [],
            "constraints": {},
        }
