"""Packet validation logic for owlscale."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

from owlscale.core import get_workspace_root, load_state, TaskError
from owlscale.models import Packet


@dataclass
class ValidationResult:
    """Result of a single validation check."""
    name: str
    passed: bool
    message: str


# HTML comment pattern
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# Section header pattern — handles both "## Goal" and "## 1. Goal"
_SECTION_RE = re.compile(r"^##\s+(?:\d+\.\s+)?(.+)$", re.MULTILINE)


def _is_placeholder(text: str) -> bool:
    """Return True if text is empty, whitespace-only, or only contains placeholders."""
    # Strip HTML comments
    cleaned = _COMMENT_RE.sub("", text)
    # Strip template bullets (lines that are just "- " or "1. ")
    lines = []
    for line in cleaned.split("\n"):
        stripped = line.strip()
        if stripped and stripped not in ["-", "- ", "1.", "1. "]:
            lines.append(stripped)
    return len(lines) == 0


def _extract_sections(body: str) -> dict[str, str]:
    """Extract sections from packet body as {name: content}."""
    sections: dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(body))

    for i, match in enumerate(matches):
        name = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections[name] = body[start:end].strip()

    return sections


def validate_packet(owlscale_dir: Path, task_id: str) -> List[ValidationResult]:
    """Validate a Context Packet for completeness.

    Returns a list of ValidationResult for each check.
    """
    packet_path = owlscale_dir / "packets" / f"{task_id}.md"
    if not packet_path.exists():
        raise TaskError(f"Packet not found: {packet_path}")

    content = packet_path.read_text()
    packet = Packet.from_markdown(content)
    sections = _extract_sections(packet.body)

    results = []

    # Check 1: Goal present
    goal_section = sections.get("Goal", "")
    goal_from_fm = packet.frontmatter.goal or ""
    has_goal = (not _is_placeholder(goal_section)) or bool(goal_from_fm.strip())
    results.append(ValidationResult(
        name="goal_present",
        passed=has_goal,
        message="Goal is clear" if has_goal else "Goal section is empty or contains only placeholders",
    ))

    # Check 2: Scope present with In scope / Out of scope
    scope_section = sections.get("Scope", "")
    has_scope = (
        not _is_placeholder(scope_section)
        and ("in scope" in scope_section.lower() or "out of scope" in scope_section.lower())
    )
    results.append(ValidationResult(
        name="scope_present",
        passed=has_scope,
        message="Scope is defined" if has_scope else "Scope section is empty or missing In scope/Out of scope",
    ))

    # Check 3: Constraints present
    constraints_section = sections.get("Constraints", "")
    has_constraints = not _is_placeholder(constraints_section)
    results.append(ValidationResult(
        name="constraints_present",
        passed=has_constraints,
        message="Constraints are defined" if has_constraints else "Constraints section is empty or contains only placeholders",
    ))

    # Check 4: Relevant Files with descriptions
    files_section = sections.get("Relevant Files", "")
    has_files = not _is_placeholder(files_section)
    if has_files:
        # Check that entries have descriptions (not just bare paths)
        file_lines = [
            l.strip() for l in files_section.split("\n")
            if l.strip().startswith("- ") and len(l.strip()) > 2
        ]
        has_files = len(file_lines) > 0
    results.append(ValidationResult(
        name="files_with_descriptions",
        passed=has_files,
        message="Relevant files are listed" if has_files else "Relevant Files section is empty or has no entries with descriptions",
    ))

    # Check 5: Validation defined
    validation_section = sections.get("Validation", "")
    has_validation = not _is_placeholder(validation_section)
    results.append(ValidationResult(
        name="validation_defined",
        passed=has_validation,
        message="Validation criteria defined" if has_validation else "Validation section is empty or contains only placeholders",
    ))

    # Check 6: Expected Output defined
    output_section = sections.get("Expected Output", "")
    has_output = not _is_placeholder(output_section)
    results.append(ValidationResult(
        name="expected_output_defined",
        passed=has_output,
        message="Expected output defined" if has_output else "Expected Output section is empty or contains only placeholders",
    ))

    return results
