"""Tests for owlscale template management."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent)
CLI_ENV = {**os.environ, "PYTHONPATH": PROJECT_ROOT}

from owlscale.core import init_project, pack_task
from owlscale.template import (
    BUILTIN_TEMPLATES, TemplateError,
    list_templates, get_template, save_template, delete_template,
)


@pytest.fixture()
def workspace(tmp_path):
    return init_project(tmp_path)


class TestBuiltins:
    def test_three_builtins(self):
        assert set(BUILTIN_TEMPLATES) == {"add-command", "fix-bug", "write-tests"}

    def test_builtins_are_nonempty(self):
        for name, body in BUILTIN_TEMPLATES.items():
            assert len(body.strip()) > 50, f"Builtin '{name}' is too short"

    def test_builtins_have_goal_section(self):
        for name, body in BUILTIN_TEMPLATES.items():
            assert "## Goal" in body, f"Builtin '{name}' missing ## Goal"

    def test_builtins_have_execution_plan(self):
        for name, body in BUILTIN_TEMPLATES.items():
            assert "## Execution Plan" in body, f"Builtin '{name}' missing ## Execution Plan"


class TestListTemplates:
    def test_empty_workspace_shows_builtins(self, workspace):
        templates = list_templates(workspace)
        assert "add-command" in templates
        assert "fix-bug" in templates
        assert "write-tests" in templates

    def test_user_template_appears(self, workspace):
        save_template(workspace, "my-custom", "## Goal\nCustom")
        templates = list_templates(workspace)
        assert "my-custom" in templates

    def test_sorted_output(self, workspace):
        save_template(workspace, "zzz-last", "## Goal\n")
        save_template(workspace, "aaa-first", "## Goal\n")
        templates = list_templates(workspace)
        assert templates == sorted(templates)

    def test_deduplicates_builtin_override(self, workspace):
        save_template(workspace, "fix-bug", "## Goal\nMy override")
        templates = list_templates(workspace)
        assert templates.count("fix-bug") == 1


class TestGetTemplate:
    def test_builtin_returned(self, workspace):
        body = get_template(workspace, "add-command")
        assert "## Goal" in body

    def test_user_template_returned(self, workspace):
        save_template(workspace, "my-task", "## Goal\nDo something")
        body = get_template(workspace, "my-task")
        assert "Do something" in body

    def test_user_overrides_builtin(self, workspace):
        save_template(workspace, "fix-bug", "## Goal\nOverride!")
        body = get_template(workspace, "fix-bug")
        assert "Override!" in body

    def test_nonexistent_raises(self, workspace):
        with pytest.raises(TemplateError, match="not found"):
            get_template(workspace, "does-not-exist")

    def test_error_lists_available(self, workspace):
        try:
            get_template(workspace, "no-such-one")
        except TemplateError as e:
            assert "add-command" in str(e)


class TestSaveTemplate:
    def test_creates_file(self, workspace):
        path = save_template(workspace, "new-tmpl", "## Goal\nHello")
        assert path.exists()
        assert path.name == "new-tmpl.md"

    def test_overwrites_existing(self, workspace):
        save_template(workspace, "t", "v1")
        save_template(workspace, "t", "v2")
        assert get_template(workspace, "t") == "v2"


class TestDeleteTemplate:
    def test_deletes_user_template(self, workspace):
        save_template(workspace, "custom", "body")
        delete_template(workspace, "custom")
        assert "custom" not in list_templates(workspace)

    def test_cannot_delete_builtin(self, workspace):
        with pytest.raises(TemplateError, match="built-in"):
            delete_template(workspace, "fix-bug")

    def test_nonexistent_raises(self, workspace):
        with pytest.raises(TemplateError, match="not found"):
            delete_template(workspace, "ghost")


class TestPackWithTemplate:
    def test_pack_with_builtin_template(self, workspace):
        path = pack_task(workspace, "my-fix", "Fix the crash", template="fix-bug")
        content = path.read_text()
        assert "## Confirmed Findings" in content

    def test_pack_with_user_template(self, workspace):
        save_template(workspace, "custom", "## Goal\nCustom body\n\n## Execution Plan\n1. Do it")
        path = pack_task(workspace, "my-task", "My goal", template="custom")
        content = path.read_text()
        assert "Custom body" in content

    def test_pack_with_nonexistent_template_raises(self, workspace):
        from owlscale.core import OwlscaleError
        with pytest.raises(OwlscaleError):
            pack_task(workspace, "t", "Goal", template="ghost")

    def test_pack_without_template_uses_default(self, workspace):
        path = pack_task(workspace, "default-task", "My goal")
        content = path.read_text()
        assert "## Goal" in content
        assert "My goal" in content


class TestTemplateCLI:
    def test_template_list(self, tmp_path):
        init_project(tmp_path)
        r = subprocess.run(
            [sys.executable, "-m", "owlscale", "template", "list"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert r.returncode == 0
        assert "fix-bug" in r.stdout
        assert "add-command" in r.stdout
        assert "write-tests" in r.stdout

    def test_template_show(self, tmp_path):
        init_project(tmp_path)
        r = subprocess.run(
            [sys.executable, "-m", "owlscale", "template", "show", "fix-bug"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert r.returncode == 0
        assert "## Goal" in r.stdout

    def test_template_show_missing(self, tmp_path):
        init_project(tmp_path)
        r = subprocess.run(
            [sys.executable, "-m", "owlscale", "template", "show", "no-such"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert r.returncode == 1

    def test_template_add_from_file(self, tmp_path):
        init_project(tmp_path)
        src = tmp_path / "my.md"
        src.write_text("## Goal\nImported")
        r = subprocess.run(
            [sys.executable, "-m", "owlscale", "template", "add", "imported", "--file", str(src)],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert r.returncode == 0
        assert "imported" in r.stdout
        r2 = subprocess.run(
            [sys.executable, "-m", "owlscale", "template", "list"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert "imported" in r2.stdout

    def test_template_remove(self, tmp_path):
        ws = init_project(tmp_path)
        save_template(ws, "to-remove", "body")
        r = subprocess.run(
            [sys.executable, "-m", "owlscale", "template", "remove", "to-remove"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert r.returncode == 0

    def test_template_remove_builtin_fails(self, tmp_path):
        init_project(tmp_path)
        r = subprocess.run(
            [sys.executable, "-m", "owlscale", "template", "remove", "fix-bug"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert r.returncode == 1

    def test_pack_with_template_flag(self, tmp_path):
        ws = init_project(tmp_path)
        r = subprocess.run(
            [sys.executable, "-m", "owlscale", "pack", "my-task",
             "--goal", "Fix something", "--template", "fix-bug"],
            capture_output=True, env=CLI_ENV, text=True, cwd=str(tmp_path),
        )
        assert r.returncode == 0
        assert "fix-bug" in r.stdout
        packet = ws / "packets" / "my-task.md"
        assert "## Confirmed Findings" in packet.read_text()
