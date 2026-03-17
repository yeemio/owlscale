"""
owlscale.detect — Scan local machine for AI tools and terminals.

Public API
----------
    scan() -> DetectionResult
    fmt_detection(result: DetectionResult) -> str

All probes are non-fatal: missing tools yield found=False, never exceptions.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ToolInfo:
    id: str
    name: str
    found: bool
    path: Optional[str]
    launch_cmd: list[str]


@dataclass
class TerminalInfo:
    id: str
    name: str
    found: bool
    path: Optional[str]
    adapter: Optional[str]


@dataclass
class DetectionResult:
    tools: dict[str, ToolInfo] = field(default_factory=dict)
    terminals: dict[str, TerminalInfo] = field(default_factory=dict)
    platform: str = field(default_factory=lambda: sys.platform)


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _probe_which(cmd: str) -> Optional[str]:
    """Return absolute path of `cmd` binary, or None if not found."""
    try:
        return shutil.which(cmd)
    except Exception:
        return None


def _probe_app(name: str) -> Optional[str]:
    """Return '/Applications/<name>.app' path on macOS if it exists, else None."""
    if sys.platform != "darwin":
        return None
    p = Path(f"/Applications/{name}.app")
    return str(p) if p.exists() else None


def _probe_gh_copilot() -> bool:
    """Return True if `gh extension list` output contains 'copilot'."""
    try:
        result = subprocess.run(
            ["gh", "extension", "list"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        return "copilot" in result.stdout.lower()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Tool probes
# ---------------------------------------------------------------------------

def _probe_claude_code() -> ToolInfo:
    path = _probe_which("claude")
    return ToolInfo(
        id="claude-code",
        name="Claude Code",
        found=path is not None,
        path=path,
        launch_cmd=["claude"],
    )


def _probe_copilot_cli() -> ToolInfo:
    gh_path = _probe_which("gh")
    found = gh_path is not None and _probe_gh_copilot()
    return ToolInfo(
        id="copilot-cli",
        name="GitHub Copilot CLI",
        found=found,
        path=gh_path if found else None,
        launch_cmd=["gh", "copilot"],
    )


def _probe_codex() -> ToolInfo:
    path = _probe_which("codex")
    return ToolInfo(
        id="codex",
        name="Codex CLI",
        found=path is not None,
        path=path,
        launch_cmd=["codex"],
    )


def _probe_cursor() -> ToolInfo:
    # Prefer app bundle on macOS; fall back to CLI wrapper
    app_path = _probe_app("Cursor")
    cli_path = _probe_which("cursor") if app_path is None else None
    path = app_path or cli_path
    return ToolInfo(
        id="cursor",
        name="Cursor",
        found=path is not None,
        path=path,
        launch_cmd=["cursor"],
    )


def _probe_vscode() -> ToolInfo:
    app_path = _probe_app("Visual Studio Code")
    cli_path = _probe_which("code") if app_path is None else None
    path = app_path or cli_path
    return ToolInfo(
        id="vscode",
        name="VSCode",
        found=path is not None,
        path=path,
        launch_cmd=["code"],
    )


# ---------------------------------------------------------------------------
# Terminal probes
# ---------------------------------------------------------------------------

def _probe_ghostty() -> TerminalInfo:
    app_path = _probe_app("Ghostty")
    cli_path = _probe_which("ghostty") if app_path is None else None
    path = app_path or cli_path
    return TerminalInfo(
        id="ghostty",
        name="Ghostty",
        found=path is not None,
        path=path,
        adapter="ghostty",
    )


def _probe_iterm2() -> TerminalInfo:
    path = _probe_app("iTerm")
    return TerminalInfo(
        id="iterm2",
        name="iTerm2",
        found=path is not None,
        path=path,
        adapter="iterm2",
    )


def _probe_tmux() -> TerminalInfo:
    path = _probe_which("tmux")
    return TerminalInfo(
        id="tmux",
        name="tmux",
        found=path is not None,
        path=path,
        adapter="tmux",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan() -> DetectionResult:
    """Run all probes and return a DetectionResult."""
    tools: dict[str, ToolInfo] = {}
    for probe in (
        _probe_claude_code,
        _probe_copilot_cli,
        _probe_codex,
        _probe_cursor,
        _probe_vscode,
    ):
        try:
            info = probe()
            tools[info.id] = info
        except Exception:
            pass

    terminals: dict[str, TerminalInfo] = {}
    for probe in (_probe_ghostty, _probe_iterm2, _probe_tmux):
        try:
            info = probe()
            terminals[info.id] = info
        except Exception:
            pass

    return DetectionResult(tools=tools, terminals=terminals)


def fmt_detection(result: DetectionResult) -> str:
    """Pretty-print a DetectionResult for CLI output."""
    lines: list[str] = []

    lines.append("AI Tools detected:")
    for tool in result.tools.values():
        mark = "✓" if tool.found else "✗"
        detail = tool.path or "(not found)"
        lines.append(f"  {mark} {tool.name:<20} {detail}")

    lines.append("")
    lines.append("Terminals detected:")
    for term in result.terminals.values():
        mark = "✓" if term.found else "✗"
        detail = term.path or "(not found)"
        lines.append(f"  {mark} {term.name:<20} {detail}")

    return "\n".join(lines)
