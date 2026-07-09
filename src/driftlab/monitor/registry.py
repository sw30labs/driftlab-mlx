"""Monitored-agent registry — regitel's jurisdictions.yaml pattern.

YAML-first with graceful degradation; paths resolve relative to the registry
file so a seed directory is fully relocatable."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from driftlab.store.db import AgentRow, Database

logger = logging.getLogger(__name__)


class AgentSpec(BaseModel):
    id: str
    name: str = ""
    priority: int = Field(default=5, ge=1, le=7)
    baseline: Path
    traces: Path
    description: str = ""

    @classmethod
    def from_entry(cls, entry: dict, *, base_dir: Path) -> "AgentSpec":
        def resolve(raw: str) -> Path:
            path = Path(raw)
            return path if path.is_absolute() else (base_dir / path).resolve()

        return cls(
            id=str(entry["id"]),
            name=str(entry.get("name", entry["id"])),
            priority=int(entry.get("priority", 5)),
            baseline=resolve(str(entry["baseline"])),
            traces=resolve(str(entry["traces"])),
            description=str(entry.get("description", "")).strip(),
        )


def load_registry(path: Path | str) -> list[AgentSpec]:
    path = Path(path)
    if not path.exists():
        logger.warning("registry %s not found; empty estate", path)
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("agents", raw if isinstance(raw, list) else [])
    specs = [AgentSpec.from_entry(entry, base_dir=path.parent) for entry in entries]
    ids = [s.id for s in specs]
    if len(ids) != len(set(ids)):
        raise ValueError(f"registry {path} contains duplicate agent ids")
    return specs


def sync_registry(database: Database, specs: list[AgentSpec]) -> None:
    """Upsert registry entries into the agents table (keeps last_checked_at)."""
    with database.session() as session:
        for spec in specs:
            row = session.get(AgentRow, spec.id)
            if row is None:
                row = AgentRow(id=spec.id)
                session.add(row)
            row.name = spec.name
            row.priority = spec.priority
            row.baseline_path = str(spec.baseline)
            row.traces_path = str(spec.traces)
            row.description = spec.description
