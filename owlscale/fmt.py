"""Packet formatter and normalizer for owlscale."""

import re
from pathlib import Path
from typing import Tuple

import yaml

from owlscale.core import TaskError

CANONICAL_FRONTMATTER_ORDER = [
    "id", "type", "goal", "status", "assignee", "created", "parent", "tags",
]

CANONICAL_SECTION_ORDER = [
    "Task Identity",
    "Goal",
    "Current State",
    "Confirmed Findings",
    "Relevant Files",
    "Scope",
    "Constraints",
    "Execution Plan",
    "Validation",
    "Expected Output",
    "Open Risks",
]

# Matches "## Goal", "## 1. Goal", "## 10. Open Risks", etc.
_SECTION_RE = re.compile(r"^(##\s+)(?:(\d+)\.\s+)?(.+)$", re.MULTILINE)


def _parse_raw(content: str) -> tuple[dict, str]:
    """Parse raw markdown into (frontmatter_dict, body).

    Works directly with YAML dict to preserve unknown fields.
    """
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
    fm_dict = yaml.safe_load(yaml_content) or {}
    body = "\n".join(lines[end_idx + 1:]).lstrip("\n")
    return fm_dict, body


def _parse_sections(body: str) -> list[tuple[str, str, str]]:
    """Parse body into sections: [(original_header, canonical_name, content), ...]

    Content before the first ## is captured with canonical_name = None.
    """
    sections = []
    matches = list(_SECTION_RE.finditer(body))

    if matches:
        preamble = body[:matches[0].start()].rstrip()
        if preamble:
            sections.append(("", None, preamble))
    elif body.strip():
        sections.append(("", None, body.rstrip()))
        return sections

    for i, match in enumerate(matches):
        name = match.group(3).strip()
        original_header = match.group(0)

        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        content = body[start:end].strip()

        sections.append((original_header, name, content))

    return sections


def _reorder_frontmatter(fm_dict: dict) -> dict:
    """Reorder frontmatter fields to canonical order."""
    ordered = {}
    for key in CANONICAL_FRONTMATTER_ORDER:
        if key in fm_dict:
            ordered[key] = fm_dict[key]
    for key in fm_dict:
        if key not in ordered:
            ordered[key] = fm_dict[key]
    return ordered


def _build_formatted(fm_dict: dict, sections: list[tuple[str, str, str]], numbered: bool) -> str:
    """Build the formatted markdown string."""
    ordered_fm = _reorder_frontmatter(fm_dict)
    yaml_str = yaml.dump(ordered_fm, default_flow_style=False, sort_keys=False, allow_unicode=True)
    lines = [f"---\n{yaml_str}---"]

    preamble = None
    body_sections = []
    for header, name, content in sections:
        if name is None:
            preamble = content
        else:
            body_sections.append((header, name, content))

    if preamble:
        lines.append("")
        lines.append(preamble)

    canon_index = {name: i for i, name in enumerate(CANONICAL_SECTION_ORDER)}

    def sort_key(item):
        _, name, _ = item
        return canon_index.get(name, len(CANONICAL_SECTION_ORDER))

    sorted_sections = sorted(body_sections, key=sort_key)

    num = 1
    for header, name, content in sorted_sections:
        lines.append("")
        if numbered:
            lines.append(f"## {num}. {name}")
            num += 1
        else:
            lines.append(f"## {name}")
        lines.append("")
        if content:
            lines.append(content)

    result = "\n".join(lines)
    result = "\n".join(line.rstrip() for line in result.split("\n"))
    if not result.endswith("\n"):
        result += "\n"
    return result


def fmt_packet(packet_path: Path, write: bool = True) -> Tuple[str, bool]:
    """Format a packet file. Returns (formatted_content, changed)."""
    if not packet_path.exists():
        raise TaskError(f"Packet file not found: {packet_path}")

    original = packet_path.read_text()
    fm_dict, body = _parse_raw(original)
    sections = _parse_sections(body)

    numbered = bool(re.search(r"^##\s+\d+\.\s+", original, re.MULTILINE))

    formatted = _build_formatted(fm_dict, sections, numbered)
    changed = formatted != original

    if write and changed:
        packet_path.write_text(formatted)

    return formatted, changed


def fmt_task_packet(owlscale_dir: Path, task_id: str, write: bool = True) -> Tuple[str, bool]:
    """Format a packet by task ID. Convenience wrapper around fmt_packet."""
    packet_path = owlscale_dir / "packets" / f"{task_id}.md"
    return fmt_packet(packet_path, write=write)
