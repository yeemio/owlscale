"""
owlscale.launch — Open terminal sessions for registered agents.

Public API
----------
    launch_agent(agent, owlscale_dir) -> bool
    build_env(agent, owlscale_dir) -> dict
    infer_launch_config(agent, detect_result=None) -> dict
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

# Tool ID → default CLI command
_TOOL_CMD_MAP: dict[str, list[str]] = {
    "claude-code": ["claude"],
    "copilot-cli": ["gh", "copilot"],
    "codex": ["codex"],
    "cursor": ["cursor"],
    "vscode": ["code"],
}

# Terminal preference order for auto-detection
_TERMINAL_PRIORITY = ["ghostty", "iterm2", "tmux", "system"]


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

def build_env(agent: Any, owlscale_dir: Path) -> dict:
    """Return env dict with OWLSCALE_AGENT, OWLSCALE_DIR, plus agent overrides."""
    env = os.environ.copy()
    env["OWLSCALE_AGENT"] = agent.id
    env["OWLSCALE_DIR"] = str(owlscale_dir.resolve())
    if agent.launch and isinstance(agent.launch.get("env"), dict):
        env.update(agent.launch["env"])
    return env


# ---------------------------------------------------------------------------
# Infer launch config from detect results
# ---------------------------------------------------------------------------

def infer_launch_config(agent: Any, detect_result: Any = None) -> dict:
    """
    Build launch config from agent.tool + detect results when agent.launch is not set.
    detect_result: DetectionResult from owlscale.detect.scan() — imported lazily.
    """
    # Pick command from tool mapping
    cmd = _TOOL_CMD_MAP.get(agent.tool or "", [])

    # Pick terminal from detect results
    terminal = "system"
    if detect_result is None:
        try:
            from owlscale.detect import scan
            detect_result = scan()
        except Exception:
            detect_result = None

    if detect_result is not None:
        for t in _TERMINAL_PRIORITY:
            term_info = detect_result.terminals.get(t)
            if term_info and term_info.found:
                terminal = t
                break

    return {
        "terminal": terminal,
        "cmd": cmd,
        "env": {},
        "window_title": agent.id,
    }


# ---------------------------------------------------------------------------
# Terminal launchers
# ---------------------------------------------------------------------------

def _shell_cmd_string(cmd: list[str], env_extras: dict) -> str:
    """Build shell command string with env prefix."""
    env_prefix = " ".join(f"{k}={v}" for k, v in env_extras.items())
    cmd_str = " ".join(cmd) if cmd else "bash"
    return f"{env_prefix} {cmd_str}".strip() if env_prefix else cmd_str


def _launch_ghostty(cmd: list[str], env: dict, window_title: Optional[str] = None) -> bool:
    """
    Open a new Ghostty window and run cmd inside it.
    Uses System Events Cmd+N to open new window, then inputs the command.
    """
    cmd_str = _shell_cmd_string(cmd, {
        "OWLSCALE_AGENT": env.get("OWLSCALE_AGENT", ""),
        "OWLSCALE_DIR": env.get("OWLSCALE_DIR", ""),
    })

    # Escape for AppleScript string literal
    safe_cmd = cmd_str.replace("\\", "\\\\").replace('"', '\\"')

    script = f"""\
tell application "Ghostty"
    activate
end tell
tell application "System Events"
    tell process "Ghostty"
        keystroke "n" using command down
    end tell
end tell
delay 0.5
tell application "Ghostty"
    tell front window
        tell current tab
            tell current terminal
                input text "{safe_cmd}\\n"
            end tell
        end tell
    end tell
end tell
"""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def _launch_iterm2(cmd: list[str], env: dict) -> bool:
    """Open a new iTerm2 window and run cmd inside it."""
    cmd_str = _shell_cmd_string(cmd, {
        "OWLSCALE_AGENT": env.get("OWLSCALE_AGENT", ""),
        "OWLSCALE_DIR": env.get("OWLSCALE_DIR", ""),
    })
    safe_cmd = cmd_str.replace("\\", "\\\\").replace('"', '\\"')

    script = f"""\
tell application "iTerm2"
    activate
    create window with default profile
    tell current session of current window
        write text "{safe_cmd}"
    end tell
end tell
"""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def _launch_tmux(cmd: list[str], env: dict, window_name: Optional[str] = None) -> bool:
    """
    Open a new tmux window and run cmd inside it.
    Requires an existing running tmux session.
    Injects env via send-keys rather than -e flag for broader tmux version compat.
    """
    name = window_name or "owlscale"
    cmd_str = " ".join(cmd) if cmd else "bash"

    # Build env export prefix
    env_exports = " ".join(
        f"export {k}={v};" for k, v in {
            "OWLSCALE_AGENT": env.get("OWLSCALE_AGENT", ""),
            "OWLSCALE_DIR": env.get("OWLSCALE_DIR", ""),
        }.items()
    )
    full_cmd = f"{env_exports} {cmd_str}".strip()

    try:
        # Create new window
        r = subprocess.run(
            ["tmux", "new-window", "-n", name],
            capture_output=True, timeout=5,
        )
        if r.returncode != 0:
            return False
        # Send command
        subprocess.run(
            ["tmux", "send-keys", full_cmd, "Enter"],
            capture_output=True, timeout=5,
        )
        return True
    except Exception:
        return False


def _launch_system_terminal(cmd: list[str], env: dict) -> bool:
    """Open macOS Terminal.app with cmd."""
    if sys.platform != "darwin":
        return False
    cmd_str = _shell_cmd_string(cmd, {
        "OWLSCALE_AGENT": env.get("OWLSCALE_AGENT", ""),
        "OWLSCALE_DIR": env.get("OWLSCALE_DIR", ""),
    })
    safe_cmd = cmd_str.replace("\\", "\\\\").replace('"', '\\"')
    script = f"""\
tell application "Terminal"
    activate
    do script "{safe_cmd}"
end tell
"""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public launch entry point
# ---------------------------------------------------------------------------

_LAUNCHERS = {
    "ghostty": _launch_ghostty,
    "iterm2": _launch_iterm2,
    "tmux": _launch_tmux,
    "system": _launch_system_terminal,
}


def launch_agent(agent: Any, owlscale_dir: Path) -> bool:
    """
    Open a terminal window/tab for the agent and start the correct AI tool.
    Returns True on success, False on any failure (non-fatal).
    """
    try:
        config = agent.launch if agent.launch else infer_launch_config(agent)
        terminal = config.get("terminal", "system")
        cmd = config.get("cmd") or []
        window_title = config.get("window_title", agent.id)
        env = build_env(agent, owlscale_dir)
        # Merge any per-config env overrides (on top of build_env)
        extra_env = config.get("env", {})
        if extra_env:
            env.update(extra_env)

        launcher = _LAUNCHERS.get(terminal)
        if launcher is None:
            print(f"Warning: unknown terminal '{terminal}' for agent '{agent.id}'",
                  file=sys.stderr)
            return False

        if terminal == "ghostty":
            return _launch_ghostty(cmd, env, window_title=window_title)
        elif terminal == "tmux":
            return _launch_tmux(cmd, env, window_name=window_title)
        else:
            return launcher(cmd, env)

    except Exception as exc:
        print(f"Warning: launch failed for '{agent.id}': {exc}", file=sys.stderr)
        return False
