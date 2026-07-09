"""Replay decision traces from JSONL files.

This is the primary ingestion path for v1: agents (or the LangGraph hook)
append one JSON object per line; driftlab replays them offline. Keeps the
whole platform testable without a live agent, and keeps traces on-host.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from driftlab.domain.models import DecisionEvent
from driftlab.identity import content_hash
from driftlab.ingest.normalizer import normalize_events


def iter_jsonl(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON ({exc})") from exc


def load_events_jsonl(
    path: Path | str,
    *,
    default_agent_id: str | None = None,
    strict: bool = True,
) -> tuple[list[DecisionEvent], list[str]]:
    """Load and normalize a JSONL trace file (or every ``*.jsonl`` in a dir)."""
    path = Path(path)
    files = sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
    raws: list[dict] = []
    for file in files:
        raws.extend(iter_jsonl(file))
    return normalize_events(raws, default_agent_id=default_agent_id, strict=strict)


def trace_hash(events: list[DecisionEvent]) -> str:
    """Deterministic content hash of an event stream (identity, not wall-clock)."""
    return content_hash([e.event_id for e in sorted(events, key=lambda e: (e.run_id, e.seq))])
