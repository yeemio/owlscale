"""Alias — map short Agent ID aliases to full agent IDs."""

from __future__ import annotations

import json
from pathlib import Path


_ALIASES_FILE = "aliases.json"


def _aliases_path(owlscale_dir: Path) -> Path:
    return owlscale_dir / _ALIASES_FILE


def _load(owlscale_dir: Path) -> dict:
    p = _aliases_path(owlscale_dir)
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def _save(owlscale_dir: Path, aliases: dict) -> None:
    _aliases_path(owlscale_dir).write_text(json.dumps(aliases, indent=2, ensure_ascii=False))


def set_alias(owlscale_dir: Path, alias: str, agent_id: str) -> None:
    """Register or update an alias mapping alias → agent_id."""
    aliases = _load(owlscale_dir)
    aliases[alias] = agent_id
    _save(owlscale_dir, aliases)


def remove_alias(owlscale_dir: Path, alias: str) -> None:
    """Remove an alias.

    Raises KeyError if alias does not exist.
    """
    aliases = _load(owlscale_dir)
    if alias not in aliases:
        raise KeyError(f"Alias '{alias}' not found")
    del aliases[alias]
    _save(owlscale_dir, aliases)


def list_aliases(owlscale_dir: Path) -> dict:
    """Return dict of {alias: agent_id}."""
    return _load(owlscale_dir)


def resolve_alias(owlscale_dir: Path, name: str) -> str:
    """Resolve name to agent_id via alias map.

    Returns the resolved agent_id if alias exists, otherwise returns name unchanged.
    Supports chained resolution (alias of alias) up to 10 hops to avoid infinite loops.
    """
    aliases = _load(owlscale_dir)
    seen = set()
    current = name
    for _ in range(10):
        if current in seen:
            break
        if current not in aliases:
            break
        seen.add(current)
        current = aliases[current]
    return current
