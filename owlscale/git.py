"""Git integration helpers for owlscale."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(root: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=check,
    )


def is_git_repo(root: Path) -> bool:
    """Return True if root is inside a git repository."""
    r = _git(root, "rev-parse", "--git-dir")
    return r.returncode == 0


def current_branch(root: Path) -> str:
    """Return the name of the currently checked-out branch."""
    r = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    return r.stdout.strip()


def branch_exists(root: Path, branch: str) -> bool:
    """Return True if the given local branch exists."""
    r = _git(root, "branch", "--list", branch)
    return bool(r.stdout.strip())


def create_branch(root: Path, branch: str) -> bool:
    """Create a new local branch at HEAD.

    Returns True if created, False if it already existed.
    """
    if branch_exists(root, branch):
        return False
    _git(root, "branch", branch, check=True)
    return True


def task_branch_name(task_id: str, assignee: str) -> str:
    """Return canonical branch name for a task: '<assignee>/<task-id>'."""
    return f"{assignee}/{task_id}"


def get_pr_command(task_id: str, assignee: str, base: str = "main") -> str:
    """Return the gh CLI command to create a PR for this task branch."""
    branch = task_branch_name(task_id, assignee)
    return f'gh pr create --title "feat: {task_id}" --base {base} --head {branch}'


def get_open_task_branches(root: Path, owlscale_dir: Path) -> list[dict]:
    """Return list of {task_id, assignee, branch, exists} for dispatched/in-progress tasks."""
    from owlscale.core import load_state, load_roster
    from owlscale.models import TaskStatus

    state = load_state(owlscale_dir)
    open_statuses = {TaskStatus.dispatched, TaskStatus.in_progress, TaskStatus.returned}
    result = []

    for task_id, task_state in state.tasks.items():
        if task_state.status not in open_statuses or not task_state.assignee:
            continue
        branch = task_branch_name(task_id, task_state.assignee)
        result.append({
            "task_id": task_id,
            "assignee": task_state.assignee,
            "branch": branch,
            "exists": branch_exists(root, branch),
            "status": task_state.status.value,
        })

    return result
