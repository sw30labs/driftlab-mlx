"""Trace ingestion and normalization.

Observed agent behavior arrives as a stream of raw records (JSONL lines, or
live LangGraph/LangChain callback events). The normalizer coerces each record
into a canonical :class:`DecisionEvent`. Unknown event shapes raise loudly —
normalization must fail closed, never silently drop evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from ..domain import DecisionEvent, EventKind


# A raw record is a dict. We map a few well-known shapes to EventKind.
_KIND_BY_KEY = {
    "tool_call": EventKind.TOOL_CALL,
    "tool": EventKind.TOOL_CALL,
    "route": EventKind.ROUTE,
    "routing": EventKind.ROUTE,
    "escalation": EventKind.ESCALATION,
    "escalate": EventKind.ESCALATION,
    "refusal": EventKind.REFUSAL,
    "refuse": EventKind.REFUSAL,
    "error": EventKind.ERROR,
    "hitl": EventKind.HITL,
    "human_review": EventKind.HITL,
}


class NormalizationError(ValueError):
    """Raised when a raw record cannot be normalized (fail-closed)."""


def normalize_record(agent: str, seq: int, raw: dict[str, Any]) -> DecisionEvent:
    """Coerce a single raw record into a canonical DecisionEvent.

    Raises :class:`NormalizationError` if the record shape is unrecognized or
    missing required fields — evidence must never be silently dropped.
    """
    kind_raw = str(raw.get("kind", raw.get("type", ""))).lower()
    kind = _KIND_BY_KEY.get(kind_raw)
    if kind is None:
        raise NormalizationError(
            f"unknown event kind {kind_raw!r} at seq {seq}; cannot normalize"
        )

    node = raw.get("node")
    if node is None:
        raise NormalizationError(f"event at seq {seq} missing required 'node'")

    event = DecisionEvent(
        agent=agent,
        seq=seq,
        kind=kind,
        node=str(node),
        tool=raw.get("tool"),
        route_from=raw.get("route_from") or raw.get("from"),
        route_to=raw.get("route_to") or raw.get("to"),
        amount=_coerce_float(raw.get("amount")),
        payload={k: v for k, v in raw.items() if k not in _RESERVED},
    )
    return event


_RESERVED = {
    "kind",
    "type",
    "node",
    "tool",
    "route_from",
    "from",
    "route_to",
    "to",
    "amount",
    "agent",
    "seq",
}


def _coerce_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def normalize_stream(agent: str, raws: Iterable[dict[str, Any]]) -> list[DecisionEvent]:
    """Normalize an ordered iterable of raw records into canonical events."""
    out: list[DecisionEvent] = []
    for seq, raw in enumerate(raws):
        out.append(normalize_record(agent, seq, raw))
    return out


def load_jsonl(path: str | Path, agent: str | None = None) -> list[DecisionEvent]:
    """Replay a logged trace file: one JSON object per line."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"trace file not found: {p}")
    raws: list[dict[str, Any]] = []
    with p.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            raws.append(json.loads(line))
    agent_name = agent or p.stem
    return normalize_stream(agent_name, raws)