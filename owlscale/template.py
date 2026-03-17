"""Template management for owlscale Context Packets."""

from pathlib import Path
from owlscale.core import OwlscaleError


BUILTIN_TEMPLATES: dict[str, str] = {
    "add-command": """\
## Goal

<!-- Describe the new CLI command or API endpoint to add -->

## Current State

<!-- What exists today? What is missing? -->

## Confirmed Findings

- Existing command structure:
- Entry point file:
- Test file:

## Relevant Files

- `<module>/cli.py` — add subcommand parser + handler
- `<module>/<feature>.py` — new module
- `tests/test_<feature>.py` — new tests

## Scope

**In scope:**
- New command implementation
- CLI wiring
- Unit tests

**Out of scope:**
- Changes to existing commands
- Documentation site

## Constraints

- No new dependencies
- Follow existing command pattern (lazy imports in cmd_* functions)
- Exit 0 on success, 1 on error

## Execution Plan

1. Create `<module>/<feature>.py` with core logic
2. Add subcommand parser to `cli.py`
3. Implement `cmd_<feature>()` handler
4. Write tests

## Validation

```bash
<command> --help
<command> <subcommand> <args>
poetry run pytest tests/test_<feature>.py -v
```

## Expected Output

- New command working end-to-end
- All tests passing

## Open Risks

- None identified
""",
    "fix-bug": """\
## Goal

<!-- One-sentence description of the bug and the fix -->

## Current State

<!-- Describe the buggy behavior, including error messages or incorrect output -->

## Confirmed Findings

- Bug location: `<file>:<line>`
- Root cause:
- Reproduction steps:
  1.
  2.
- Affected versions:

## Relevant Files

- `<file-containing-bug>` — root cause here
- `tests/test_<module>.py` — existing tests (may need update)

## Scope

**In scope:**
- Fix the specific bug at root cause location
- Update or add test to prevent regression

**Out of scope:**
- Refactoring unrelated code
- Adding new features

## Constraints

- Minimal change — fix only what's broken
- Add regression test
- Do not break existing tests

## Execution Plan

1. Reproduce the bug with a failing test
2. Fix root cause in `<file>`
3. Confirm test passes
4. Check no regressions

## Validation

```bash
poetry run pytest tests/test_<module>.py -v
poetry run pytest  # full suite
```

## Expected Output

- Bug no longer reproduced
- Regression test added and passing
- All existing tests still pass

## Open Risks

- Fix may uncover related bugs in adjacent code
""",
    "write-tests": """\
## Goal

<!-- Describe what needs test coverage and why it currently lacks it -->

## Current State

<!-- What test coverage exists? What is missing? -->

## Confirmed Findings

- Module under test: `<module>`
- Test file: `tests/test_<module>.py`
- Current coverage gaps:
  - Missing: 
  - Missing: 

## Relevant Files

- `<module>.py` — module under test
- `tests/test_<module>.py` — test file to create/extend

## Scope

**In scope:**
- Unit tests for all public functions/methods
- Edge cases and error handling
- CLI integration tests (subprocess)

**Out of scope:**
- Adding new functionality
- Integration tests beyond CLI

## Constraints

- Use `pytest` with `tmp_path` fixtures
- Test classes named `TestXxx` grouped by feature
- No mocking of filesystem (use tmp_path)
- Cover happy path AND error cases

## Execution Plan

1. Identify all untested functions/branches
2. Write test class per logical group
3. Cover: happy path, edge cases, error cases
4. Run full suite to check no regressions

## Validation

```bash
poetry run pytest tests/test_<module>.py -v
poetry run pytest  # full suite
```

## Expected Output

- All new tests passing
- No regressions

## Open Risks

- Some behavior may be undocumented; verify against source
""",
}


class TemplateError(OwlscaleError):
    """Template-related error."""
    pass


def _template_dir(owlscale_dir: Path) -> Path:
    return owlscale_dir / "templates"


def list_templates(owlscale_dir: Path) -> list[str]:
    """Return sorted list of available template names (builtins + user-defined)."""
    user_names = [p.stem for p in _template_dir(owlscale_dir).glob("*.md")]
    all_names = sorted(set(BUILTIN_TEMPLATES) | set(user_names))
    return all_names


def get_template(owlscale_dir: Path, name: str) -> str:
    """Return body content of a named template.

    Raises TemplateError if not found.
    """
    # Check user-defined first (allows overriding builtins)
    user_path = _template_dir(owlscale_dir) / f"{name}.md"
    if user_path.exists():
        return user_path.read_text()

    if name in BUILTIN_TEMPLATES:
        return BUILTIN_TEMPLATES[name]

    available = list_templates(owlscale_dir)
    available_str = ", ".join(available) if available else "(none)"
    raise TemplateError(
        f"Template '{name}' not found. Available: {available_str}"
    )


def save_template(owlscale_dir: Path, name: str, body: str) -> Path:
    """Write a user-defined template file. Overwrites if exists."""
    path = _template_dir(owlscale_dir) / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def delete_template(owlscale_dir: Path, name: str) -> None:
    """Remove a user-defined template. Raises TemplateError if not found or is a builtin."""
    if name in BUILTIN_TEMPLATES:
        raise TemplateError(f"Cannot delete built-in template '{name}'.")
    path = _template_dir(owlscale_dir) / f"{name}.md"
    if not path.exists():
        raise TemplateError(f"Template '{name}' not found.")
    path.unlink()
