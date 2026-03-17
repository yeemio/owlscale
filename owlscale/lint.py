"""Lint — comprehensive quality check combining validate, fmt, file existence, and assignee verification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class LintResult:
    """Result of a single lint check."""
    name: str
    passed: bool
    message: str


def _extract_relevant_files(body: str, project_root: Path) -> list[Path]:
    """Extract file paths mentioned in a packet body.

    Looks for paths ending in known extensions within backtick spans, code blocks,
    or bare path patterns like 'src/foo.py'.
    """
    # First, collect backtick-quoted paths
    candidates = re.findall(r"`([^`]+)`", body)

    # For bare paths, strip URLs first to avoid matching inside URLs
    body_no_urls = re.sub(r"https?://\S+", "", body)
    candidates += re.findall(
        r"\b([\w./-]+\.(?:py|ts|js|go|rs|java|yaml|yml|json|md|sh|toml))\b",
        body_no_urls,
    )

    paths = []
    for c in candidates:
        c = c.strip()
        if not c or c.startswith("http"):
            continue
        p = project_root / c
        if p not in paths:
            paths.append(p)
    return paths


def _check_packet_valid(owlscale_dir: Path, task_id: str) -> LintResult:
    """Run validate_packet and summarize result."""
    from owlscale.validate import validate_packet
    results = validate_packet(owlscale_dir, task_id)
    failed = [r for r in results if not r.passed]
    if not failed:
        return LintResult(name="validate", passed=True, message=f"All {len(results)} validation checks passed")
    msgs = "; ".join(f.message for f in failed)
    return LintResult(name="validate", passed=False, message=f"{len(failed)} check(s) failed: {msgs}")


def _check_fmt(owlscale_dir: Path, task_id: str) -> LintResult:
    """Check that packet is properly formatted."""
    from owlscale.fmt import fmt_task_packet
    _, changed = fmt_task_packet(owlscale_dir, task_id, write=False)
    if changed:
        return LintResult(name="fmt", passed=False, message="Packet needs formatting (run: owlscale fmt <task-id>)")
    return LintResult(name="fmt", passed=True, message="Packet is correctly formatted")


def _check_files(owlscale_dir: Path, task_id: str) -> LintResult:
    """Check that files referenced in packet body exist on disk."""
    from owlscale.models import Packet
    project_root = owlscale_dir.parent
    packet_path = owlscale_dir / "packets" / f"{task_id}.md"

    if not packet_path.exists():
        return LintResult(name="files", passed=False, message=f"Packet file not found: {packet_path}")

    packet = Packet.from_markdown(packet_path.read_text())
    referenced = _extract_relevant_files(packet.body, project_root)

    if not referenced:
        return LintResult(name="files", passed=True, message="No file references found")

    missing = [str(p.relative_to(project_root)) for p in referenced if not p.exists()]
    if missing:
        return LintResult(
            name="files",
            passed=False,
            message=f"{len(missing)} referenced file(s) not found: {', '.join(missing[:5])}",
        )
    return LintResult(name="files", passed=True, message=f"{len(referenced)} referenced file(s) exist")


def _check_assignee(owlscale_dir: Path, task_id: str) -> LintResult:
    """Check that the assignee (if any) is registered in the roster."""
    from owlscale.core import load_state, load_roster

    state = load_state(owlscale_dir)
    if task_id not in state.tasks:
        return LintResult(name="assignee", passed=False, message=f"Task '{task_id}' not found in state")

    task = state.tasks[task_id]
    if not task.assignee:
        return LintResult(name="assignee", passed=True, message="No assignee set")

    roster = load_roster(owlscale_dir)
    if task.assignee in roster:
        return LintResult(name="assignee", passed=True, message=f"Assignee '{task.assignee}' is registered")
    return LintResult(
        name="assignee",
        passed=False,
        message=f"Assignee '{task.assignee}' is not registered in roster",
    )


def lint_packet(owlscale_dir: Path, task_id: str) -> List[LintResult]:
    """Run all lint checks on a packet.

    Returns exactly 4 LintResult in fixed order: validate, fmt, files, assignee.
    """
    return [
        _check_packet_valid(owlscale_dir, task_id),
        _check_fmt(owlscale_dir, task_id),
        _check_files(owlscale_dir, task_id),
        _check_assignee(owlscale_dir, task_id),
    ]
