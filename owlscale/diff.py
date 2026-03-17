"""Packet diff logic for owlscale — compare two packet versions."""

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from owlscale.core import TaskError


@dataclass
class DiffResult:
    """Result of comparing two packets."""
    task_id_a: str
    task_id_b: str
    frontmatter_changes: list[str]
    body_diff: str
    has_changes: bool


def _parse_raw(content: str) -> tuple[dict, str]:
    """Parse raw markdown into (frontmatter_dict, body)."""
    lines = content.split("\n")
    if not lines[0].strip() == "---":
        raise ValueError("Missing opening ---")

    end_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx == -1:
        raise ValueError("Missing closing ---")

    yaml_content = "\n".join(lines[1:end_idx])
    try:
        import yaml
        fm_dict = yaml.safe_load(yaml_content) or {}
    except ImportError:
        raise ImportError("owlscale diff requires PyYAML: pip install pyyaml")
    body = "\n".join(lines[end_idx + 1:])
    return fm_dict, body


def _diff_frontmatter(fm_a: dict, fm_b: dict) -> list[str]:
    """Compare two frontmatter dicts, return list of human-readable changes."""
    changes = []
    all_keys = sorted(set(list(fm_a.keys()) + list(fm_b.keys())))

    for key in all_keys:
        val_a = fm_a.get(key)
        val_b = fm_b.get(key)
        if val_a != val_b:
            if val_a is None:
                changes.append(f"+ {key}: {val_b}")
            elif val_b is None:
                changes.append(f"- {key}: {val_a}")
            else:
                changes.append(f"~ {key}: {val_a!r} → {val_b!r}")

    return changes


def diff_packets(
    path_a: Path,
    path_b: Path,
    context_lines: int = 3,
) -> DiffResult:
    """Compare two packet files and return a DiffResult.

    Args:
        path_a: Path to first packet (e.g., the original).
        path_b: Path to second packet (e.g., the updated version).
        context_lines: Number of context lines in unified diff.
    """
    if not path_a.exists():
        raise TaskError(f"Packet not found: {path_a}")
    if not path_b.exists():
        raise TaskError(f"Packet not found: {path_b}")

    content_a = path_a.read_text()
    content_b = path_b.read_text()

    fm_a, body_a = _parse_raw(content_a)
    fm_b, body_b = _parse_raw(content_b)

    fm_changes = _diff_frontmatter(fm_a, fm_b)

    body_lines_a = body_a.splitlines(keepends=True)
    body_lines_b = body_b.splitlines(keepends=True)
    body_diff = "".join(difflib.unified_diff(
        body_lines_a, body_lines_b,
        fromfile=str(path_a.name),
        tofile=str(path_b.name),
        n=context_lines,
    ))

    has_changes = bool(fm_changes) or bool(body_diff)

    label_a = path_a.stem
    label_b = path_b.stem

    return DiffResult(
        task_id_a=label_a,
        task_id_b=label_b,
        frontmatter_changes=fm_changes,
        body_diff=body_diff,
        has_changes=has_changes,
    )


def diff_task_packets(
    owlscale_dir: Path,
    task_id_a: str,
    task_id_b: str,
    context_lines: int = 3,
) -> DiffResult:
    """Compare two packets by task ID within the workspace."""
    path_a = owlscale_dir / "packets" / f"{task_id_a}.md"
    path_b = owlscale_dir / "packets" / f"{task_id_b}.md"
    return diff_packets(path_a, path_b, context_lines=context_lines)
