"""
owlscale.adapters.ghostty — Ghostty AppleScript terminal adapter.

Drives Ghostty by injecting a prompt line via osascript.
All failures are non-fatal: returns False and logs a warning.
"""

from __future__ import annotations

import shlex
import subprocess


_SCRIPT_WINDOW_TITLE = """\
tell application "Ghostty"
    set targetWindow to missing value
    repeat with w in windows
        if name of w contains "{window_title}" then
            set targetWindow to w
            exit repeat
        end if
    end repeat
    if targetWindow is missing value then
        set targetWindow to front window
    end if
    set targetTerminal to focused terminal of selected tab of targetWindow
    input text "{message}" to targetTerminal
    send key "enter" to targetTerminal
end tell
"""

_SCRIPT_FRONT_WINDOW = """\
tell application "Ghostty"
    set targetTerminal to focused terminal of selected tab of front window
    input text "{message}" to targetTerminal
    send key "enter" to targetTerminal
end tell
"""


def inject_prompt(
    agent_id: str,
    task_id: str,
    window_title: str | None = None,
) -> bool:
    """
    Type a wake-up shell snippet into the Ghostty terminal, then send Enter.

    window_title: match Ghostty window by title substring.
    Falls back to front window if None or no match.
    Returns True on success, False on any failure (non-fatal).
    """
    message = f"owlscale has new work for {agent_id}: {task_id}"
    command = (
        f"printf '%s\\n' {shlex.quote(message)}; "
        f"owlscale whoami {shlex.quote(agent_id)}"
    )
    # Escape backslashes and double-quotes for AppleScript string literal
    safe_message = command.replace("\\", "\\\\").replace('"', '\\"')

    if window_title:
        safe_title = window_title.replace("\\", "\\\\").replace('"', '\\"')
        script = _SCRIPT_WINDOW_TITLE.format(
            window_title=safe_title,
            message=safe_message,
        )
    else:
        script = _SCRIPT_FRONT_WINDOW.format(message=safe_message)

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:  # noqa: BLE001
        return False
