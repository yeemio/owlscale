"""Self-contained owlscale walkthrough for onboarding and screenshots."""

from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from owlscale import __version__
from owlscale.core import accept_task, add_agent, dispatch_task, get_status, init_project, pack_task, return_task

_TASK_ID = "demo-add-rate-limiting"
_PROJECT_NAME = "demo-project"


def _use_color(no_color: bool) -> bool:
    return not no_color and not os.environ.get("NO_COLOR") and sys.stdout.isatty()


def _c(enabled: bool, code: str, text: str) -> str:
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"


def _pause(fast: bool) -> None:
    if not fast:
        time.sleep(0.3)


def _print_header(color: bool) -> None:
    inner_width = 48

    def _box(text: str) -> str:
        return f"║{text.center(inner_width)}║"

    lines = [
        "╔" + ("═" * inner_width) + "╗",
        _box(f"owlscale demo — v{__version__}"),
        _box("Multi-agent AI collaboration protocol"),
        "╚" + ("═" * inner_width) + "╝",
    ]
    for line in lines:
        print(_c(color, "36;1", line))
    print()


def _step(color: bool, current: int, total: int, label: str) -> None:
    print(_c(color, "34;1", f"Step {current}/{total}  {label}"))


def _cmd(color: bool, command: str) -> None:
    print(f"  {_c(color, '33', '$')} {command}")


def _ok(color: bool, message: str) -> None:
    print(f"  {_c(color, '32;1', '✓')} {message}")


def _write_project_name(owlscale_dir: Path, project_name: str) -> None:
    config_path = owlscale_dir / "config.json"
    config_path.write_text(
        json.dumps({"project_name": project_name}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_demo_return(return_path: Path) -> None:
    return_path.write_text(
        f"""# Return Packet: {_TASK_ID}

## Summary

Implemented API rate limiting middleware and request budget checks.

## Files Modified

- `api/middleware/rate_limit.py` — added token bucket enforcement.
- `tests/test_rate_limit.py` — covered burst and steady-state traffic.

## Key Decisions

- Used a token bucket because it handles bursts cleanly.
- Kept config surface small for first rollout.

## Tests Run

- `pytest tests/test_rate_limit.py -q`

## Remaining Risks

- Distributed enforcement needs shared state in production.

## Unfinished Items

- None
""",
        encoding="utf-8",
    )


def _render_table(task_id: str, assignee: str, status: str) -> str:
    task_w = 40
    assignee_w = 8
    status_w = 8

    def _row(left: str, middle: str, right: str) -> str:
        return f"│ {left.ljust(task_w)} │ {middle.ljust(assignee_w)} │ {right.ljust(status_w)} │"

    top = f"┌{'─' * (task_w + 2)}┬{'─' * (assignee_w + 2)}┬{'─' * (status_w + 2)}┐"
    mid = f"├{'─' * (task_w + 2)}┼{'─' * (assignee_w + 2)}┼{'─' * (status_w + 2)}┤"
    bottom = f"└{'─' * (task_w + 2)}┴{'─' * (assignee_w + 2)}┴{'─' * (status_w + 2)}┘"
    return "\n".join(
        [
            top,
            _row("Task", "Assignee", "Status"),
            mid,
            _row(task_id, assignee, status),
            bottom,
        ]
    )


def run_demo(fast: bool = False, no_color: bool = False) -> None:
    """Run the onboarding walkthrough in an isolated temporary workspace."""
    fast = fast or os.environ.get("OWLSCALE_DEMO_FAST") == "1"
    color = _use_color(no_color)

    workspace_root = Path(tempfile.mkdtemp(prefix="owlscale-demo-")).resolve()

    def _cleanup() -> None:
        shutil.rmtree(workspace_root, ignore_errors=True)

    atexit.register(_cleanup)

    try:
        owlscale_dir = init_project(workspace_root)
        _write_project_name(owlscale_dir, _PROJECT_NAME)

        _print_header(color)

        _step(color, 1, 6, "Initialize workspace")
        _cmd(color, 'owlscale init --name "demo-project"')
        _ok(color, ".owlscale/ created")
        _pause(fast)
        print()

        _step(color, 2, 6, "Register agents")
        _cmd(color, 'owlscale roster add orchestrator --role coordinator --name "Claude Code"')
        add_agent(owlscale_dir, "orchestrator", "Claude Code", "coordinator")
        _cmd(color, 'owlscale roster add worker      --role executor    --name "Copilot"')
        add_agent(owlscale_dir, "worker", "Copilot", "executor")
        _ok(color, "2 agents registered")
        _pause(fast)
        print()

        _step(color, 3, 6, "Create and dispatch a task")
        _cmd(color, 'owlscale pack demo-add-rate-limiting --goal "Add rate limiting to the API"')
        pack_task(owlscale_dir, _TASK_ID, "Add rate limiting to the API")
        _cmd(color, "owlscale dispatch demo-add-rate-limiting worker")
        dispatch_task(owlscale_dir, _TASK_ID, "worker")
        _ok(color, "Task dispatched → worker")
        _pause(fast)
        print()

        _step(color, 4, 6, "Agent returns work")
        _cmd(color, "owlscale return demo-add-rate-limiting")
        return_path = owlscale_dir / "returns" / f"{_TASK_ID}.md"
        _write_demo_return(return_path)
        return_task(owlscale_dir, _TASK_ID)
        _ok(color, "Return packet created and submitted")
        _pause(fast)
        print()

        _step(color, 5, 6, "Coordinator reviews and accepts")
        _cmd(color, "owlscale accept demo-add-rate-limiting")
        accept_task(owlscale_dir, _TASK_ID)
        _ok(color, "Task accepted")
        _pause(fast)
        print()

        _step(color, 6, 6, "Status overview")
        _cmd(color, "owlscale status")
        state = get_status(owlscale_dir)
        accepted = sum(1 for task in state.tasks.values() if task.status.value == "accepted")
        in_progress = sum(1 for task in state.tasks.values() if task.status.value == "in_progress")
        pending = sum(1 for task in state.tasks.values() if task.status.value in {"draft", "ready", "dispatched", "returned"})
        print(f"  Tasks: {accepted} accepted, {in_progress} in progress, {pending} pending")
        print(_render_table(_TASK_ID, "worker", "accepted"))
        print()
        print(_c(color, "32;1", "✓ Demo complete.") + " Run `owlscale init` in your project to get started.")
        print("  Docs: https://github.com/yeemio/owlscale")

    except Exception as exc:
        print(_c(color, "31;1", f"✗ Demo failed: {exc}"), file=sys.stderr)
        raise
    finally:
        _cleanup()
