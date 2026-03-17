"""Tests for owlscale git integration."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
CLI_ENV = {**os.environ, "PYTHONPATH": PROJECT_ROOT}

from owlscale.core import init_project, add_agent, pack_task, dispatch_task
from owlscale.git import (
    is_git_repo, current_branch, branch_exists, create_branch,
    task_branch_name, get_pr_command, get_open_task_branches,
)


# Skip all git tests if git is not installed
pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git not found in PATH",
)


@pytest.fixture()
def git_repo(tmp_path):
    """Isolated git repository for testing (never touches the real repo)."""
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True)
    # Create initial commit so HEAD exists
    (tmp_path / "README.md").write_text("init")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
    return tmp_path


@pytest.fixture()
def ws_in_git_repo(git_repo):
    """Owlscale workspace inside an isolated git repo."""
    ws = init_project(git_repo)
    add_agent(ws, "bot", "Bot", "executor")
    return ws, git_repo


class TestIsGitRepo:
    def test_true_in_git_repo(self, git_repo):
        assert is_git_repo(git_repo) is True

    def test_false_outside_repo(self, tmp_path):
        assert is_git_repo(tmp_path) is False


class TestBranchExists:
    def test_false_for_new_branch(self, git_repo):
        assert branch_exists(git_repo, "feature/new") is False

    def test_true_after_create(self, git_repo):
        create_branch(git_repo, "feature/exists")
        assert branch_exists(git_repo, "feature/exists") is True

    def test_false_for_similar_name(self, git_repo):
        create_branch(git_repo, "feature/abc")
        assert branch_exists(git_repo, "feature/ab") is False


class TestCreateBranch:
    def test_creates_and_returns_true(self, git_repo):
        assert create_branch(git_repo, "new-branch") is True

    def test_returns_false_if_exists(self, git_repo):
        create_branch(git_repo, "dup")
        assert create_branch(git_repo, "dup") is False


class TestTaskBranchName:
    def test_format(self):
        assert task_branch_name("my-task", "copilot") == "copilot/my-task"

    def test_with_complex_ids(self):
        name = task_branch_name("2026-03-17-owlscale-git", "claude-opus")
        assert name == "claude-opus/2026-03-17-owlscale-git"


class TestGetPrCommand:
    def test_contains_task_id(self):
        cmd = get_pr_command("my-task", "bot")
        assert "my-task" in cmd

    def test_contains_gh_pr_create(self):
        cmd = get_pr_command("my-task", "bot")
        assert cmd.startswith("gh pr create")

    def test_contains_base(self):
        cmd = get_pr_command("my-task", "bot", base="develop")
        assert "--base develop" in cmd

    def test_contains_head_branch(self):
        cmd = get_pr_command("my-task", "bot")
        assert "--head bot/my-task" in cmd


class TestGetOpenTaskBranches:
    def test_dispatched_task_appears(self, ws_in_git_repo):
        ws, repo = ws_in_git_repo
        pack_task(ws, "open-1", "Open task")
        dispatch_task(ws, "open-1", "bot")
        tasks = get_open_task_branches(repo, ws)
        task_ids = [t["task_id"] for t in tasks]
        assert "open-1" in task_ids

    def test_branch_exists_correctly_reported(self, ws_in_git_repo):
        ws, repo = ws_in_git_repo
        pack_task(ws, "with-branch", "Task")
        dispatch_task(ws, "with-branch", "bot")
        create_branch(repo, "bot/with-branch")
        tasks = get_open_task_branches(repo, ws)
        entry = next(t for t in tasks if t["task_id"] == "with-branch")
        assert entry["exists"] is True

    def test_branch_not_exists_reported(self, ws_in_git_repo):
        ws, repo = ws_in_git_repo
        pack_task(ws, "no-branch", "Task")
        dispatch_task(ws, "no-branch", "bot")
        tasks = get_open_task_branches(repo, ws)
        entry = next(t for t in tasks if t["task_id"] == "no-branch")
        assert entry["exists"] is False


class TestDispatchWithGit:
    def test_dispatch_git_creates_branch(self, git_repo):
        ws = init_project(git_repo)
        add_agent(ws, "copilot", "Copilot", "executor")
        pack_task(ws, "task-g", "Git task")
        r = subprocess.run(
            [sys.executable, "-m", "owlscale", "dispatch", "task-g", "copilot", "--git"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(git_repo),
        )
        assert r.returncode == 0
        assert "Created branch" in r.stdout
        assert branch_exists(git_repo, "copilot/task-g")

    def test_dispatch_git_warns_if_branch_exists(self, git_repo):
        ws = init_project(git_repo)
        add_agent(ws, "copilot", "Copilot", "executor")
        pack_task(ws, "task-dup", "Task")
        create_branch(git_repo, "copilot/task-dup")
        r = subprocess.run(
            [sys.executable, "-m", "owlscale", "dispatch", "task-dup", "copilot", "--git"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(git_repo),
        )
        assert r.returncode == 0
        assert "already exists" in r.stdout

    def test_dispatch_without_git_no_branch(self, git_repo):
        ws = init_project(git_repo)
        add_agent(ws, "copilot", "Copilot", "executor")
        pack_task(ws, "task-nog", "No git task")
        r = subprocess.run(
            [sys.executable, "-m", "owlscale", "dispatch", "task-nog", "copilot"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(git_repo),
        )
        assert r.returncode == 0
        assert not branch_exists(git_repo, "copilot/task-nog")


class TestGitSubcommands:
    def test_git_pr_prints_command(self, git_repo):
        ws = init_project(git_repo)
        add_agent(ws, "bot", "Bot", "executor")
        pack_task(ws, "pr-task", "PR task")
        dispatch_task(ws, "pr-task", "bot")
        r = subprocess.run(
            [sys.executable, "-m", "owlscale", "git", "pr", "pr-task"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(git_repo),
        )
        assert r.returncode == 0
        assert "gh pr create" in r.stdout
        assert "bot/pr-task" in r.stdout

    def test_git_branch_creates(self, git_repo):
        ws = init_project(git_repo)
        add_agent(ws, "bot", "Bot", "executor")
        pack_task(ws, "br-task", "Branch task")
        dispatch_task(ws, "br-task", "bot")
        r = subprocess.run(
            [sys.executable, "-m", "owlscale", "git", "branch", "br-task"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(git_repo),
        )
        assert r.returncode == 0
        assert branch_exists(git_repo, "bot/br-task")

    def test_git_status_shows_tasks(self, git_repo):
        ws = init_project(git_repo)
        add_agent(ws, "bot", "Bot", "executor")
        pack_task(ws, "open-task", "Open")
        dispatch_task(ws, "open-task", "bot")
        r = subprocess.run(
            [sys.executable, "-m", "owlscale", "git", "status"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(git_repo),
        )
        assert r.returncode == 0
        assert "open-task" in r.stdout
