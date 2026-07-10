"""Sandboxed replay of a monitored agent.

The micro-experiment loop never touches the live/production system. It operates
only on a *replay* of the agent's recorded decision trace, held in memory. The
sandbox is intentionally incapable of outbound action: it exposes a read-only
view over the replayed events and a deterministic "probe" primitive that
re-tests a behavioral claim against the matching population of events.

Isolation contract: a sandbox is constructed from an event list. It can answer
queries about those events but has no network, no filesystem writes, and no
handle to any live agent. The test suite proves this by booby-trapping the
socket layer before constructing and running a sandbox — any outbound attempt
raises.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..domain import DecisionEvent


@dataclass
class ProbeResult:
    """Outcome of a single controlled probe against the replay sandbox."""

    probe_id: str
    claim: str
    kind: str  # "existence" | "rate"
    samples: int
    violations: int
    detail: str


class ReplaySandbox:
    """An in-memory, read-only replay of one agent's decision trace.

    Constructed purely from events; holds no live references. The only way to
    "act" is :meth:`query`, which is a pure function over the replayed events.
    """

    def __init__(self, agent: str, events: list[DecisionEvent]):
        self.agent = agent
        self.events = list(events)

    def matching(self, predicate: Callable[[DecisionEvent], bool]) -> list[DecisionEvent]:
        """Return the events matching a predicate (the 'population' for a probe)."""
        return [e for e in self.events if predicate(e)]

    def count(self, predicate: Callable[[DecisionEvent], bool]) -> int:
        return sum(1 for e in self.events if predicate(e))

    def query(self, predicate: Callable[[DecisionEvent], bool]) -> list[dict]:
        """Read-only projection: return matching events as plain dicts."""
        return [e.model_dump(mode="json") for e in self.events if predicate(e)]