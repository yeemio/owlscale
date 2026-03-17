"""Tests for owlscale demo command."""

from __future__ import annotations

import os
import subprocess
import sys

from owlscale.demo import run_demo


def test_run_demo_outputs_expected_text(monkeypatch, capsys):
    monkeypatch.setenv("OWLSCALE_DEMO_FAST", "1")

    run_demo()

    out = capsys.readouterr().out
    assert "owlscale demo" in out
    assert "Step 1/6  Initialize workspace" in out
    assert "demo-add-rate-limiting" in out
    assert "✓ Demo complete." in out


def test_run_demo_cleans_up_temp_dir(monkeypatch, tmp_path):
    demo_dir = tmp_path / "demo-root"
    demo_dir.mkdir()
    monkeypatch.setenv("OWLSCALE_DEMO_FAST", "1")
    monkeypatch.setattr("owlscale.demo.tempfile.mkdtemp", lambda prefix: str(demo_dir))

    run_demo()

    assert not demo_dir.exists()


def test_run_demo_no_color_has_no_ansi(monkeypatch, capsys):
    monkeypatch.setenv("OWLSCALE_DEMO_FAST", "1")

    run_demo(no_color=True)

    out = capsys.readouterr().out
    assert "\x1b[" not in out


def test_cli_demo_fast_no_color(tmp_path):
    env = os.environ.copy()
    env["OWLSCALE_DEMO_FAST"] = "1"

    result = subprocess.run(
        [sys.executable, "-m", "owlscale", "demo", "--fast", "--no-color"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=env,
    )

    assert result.returncode == 0
    assert "Step 6/6  Status overview" in result.stdout
    assert "Tasks: 1 accepted, 0 in progress, 0 pending" in result.stdout
    assert "\x1b[" not in result.stdout
