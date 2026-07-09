"""Normalize raw trace payloads into canonical ``DecisionEvent``s.

Accepts the loose dict shapes emitted by the JSONL recorder, the LangGraph
callback hook, or third-party exporters, and maps them onto the canonical
vocabulary. Unknown event types are surfaced loudly (twinops: schema drift is
loud), not silently dropped.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from driftlab.domain.models import DecisionEvent, EventType

logger = logging.getLogger(__name__)

#: loose aliases seen in the wild -> canonical EventType
_EVENT_ALIASES: dict[str, EventType] = {
    "node": EventType.NODE_ENTER,
    "node_enter": EventType.NODE_ENTER,
    "on_chain_start": EventType.NODE_ENTER,
    "tool": EventType.TOOL_CALL,
    "tool_call": EventType.TOOL_CALL,
    "on_tool_start": EventType.TOOL_CALL,
    "route": EventType.ROUTE,
    "routing": EventType.ROUTE,
    "edge": EventType.ROUTE,
    "hitl": EventType.HITL,
    "human_in_the_loop": EventType.HITL,
    "interrupt": EventType.HITL,
    "escalation": EventType.ESCALATION,
    "escalate": EventType.ESCALATION,
    "refusal": EventType.REFUSAL,
    "refuse": EventType.REFUSAL,
    "fallback": EventType.FALLBACK,
    "error": EventType.ERROR,
    "on_chain_error": EventType.ERROR,
    "on_tool_error": EventType.ERROR,
    "output_commit": EventType.OUTPUT_COMMIT,
    "commit": EventType.OUTPUT_COMMIT,
    "final": EventType.OUTPUT_COMMIT,
}


class NormalizationError(ValueError):
    """Raised when a raw event cannot be mapped onto the canonical model."""


def normalize_event(raw: dict[str, Any], *, default_agent_id: str | None = None) -> DecisionEvent:
    """Map one raw dict onto a canonical DecisionEvent.

    Required keys: run_id, seq, event_type (or an alias), node.
    ``agent_id`` may come from the payload or the ingestion context.
    """
    agent_id = raw.get("agent_id") or default_agent_id
    if not agent_id:
        raise NormalizationError("event has no agent_id and no default was provided")

    raw_type = str(raw.get("event_type") or raw.get("type") or "").strip().lower()
    event_type = _EVENT_ALIASES.get(raw_type)
    if event_type is None:
        try:
            event_type = EventType(raw_type)
        except ValueError as exc:
            raise NormalizationError(f"unknown event_type {raw_type!r} (run {raw.get('run_id')})") from exc

    try:
        run_id = str(raw["run_id"])
        seq = int(raw["seq"])
        node = str(raw["node"])
    except KeyError as exc:
        raise NormalizationError(f"event missing required key {exc}") from exc

    return DecisionEvent(
        agent_id=str(agent_id),
        run_id=run_id,
        seq=seq,
        event_type=event_type,
        node=node,
        tool=raw.get("tool"),
        target=raw.get("target"),
        autonomy=raw.get("autonomy"),
        decision_context=dict(raw.get("decision_context") or raw.get("context") or {}),
        ts=raw.get("ts") or raw.get("timestamp"),
        attrs=dict(raw.get("attrs") or {}),
    )


def normalize_events(
    raws: Iterable[dict[str, Any]],
    *,
    default_agent_id: str | None = None,
    strict: bool = True,
) -> tuple[list[DecisionEvent], list[str]]:
    """Normalize a stream. Returns (events sorted by (run_id, seq), problems).

    In non-strict mode malformed events are reported, not fatal — but they are
    never silently ignored.
    """
    events: list[DecisionEvent] = []
    problems: list[str] = []
    for i, raw in enumerate(raws):
        try:
            events.append(normalize_event(raw, default_agent_id=default_agent_id))
        except NormalizationError as exc:
            if strict:
                raise
            problems.append(f"event[{i}]: {exc}")
            logger.warning("skipping malformed event %d: %s", i, exc)
    events.sort(key=lambda e: (e.run_id, e.seq))
    return events, problems
