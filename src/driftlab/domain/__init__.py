"""Canonical domain models shared across the deterministic compliance path.

The two primary shapes are:

* ``DecisionEvent`` — one normalized observed decision from a running agent
  (a tool call, a routing choice, an escalation, a refusal, an error).
* ``BaselinePolicy`` — an executable, fail-closed compilation of a certified
  OSCAL baseline (the DL-1..7 control family bound to concrete parameters).
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from ..identity import event_id, stable_json_digest


class EventKind(str, Enum):
    TOOL_CALL = "tool_call"
    ROUTE = "route"
    ESCALATION = "escalation"
    REFUSAL = "refusal"
    ERROR = "error"
    HITL = "hitl"  # human-in-the-loop trigger / gate interaction


class DecisionEvent(BaseModel):
    """A single normalized decision emitted by a running agent.

    ``id`` is content-derived so identical decisions collapse to one id and
    re-runs are deterministic.
    """

    agent: str
    seq: int
    kind: EventKind
    node: str  # the graph/agent node that produced the decision
    tool: str | None = None  # for tool_call
    route_from: str | None = None  # for route
    route_to: str | None = None  # for route
    amount: float | None = None  # optional numeric context (e.g. loan amount)
    payload: dict[str, Any] = Field(default_factory=dict)
    id: str = ""

    def model_post_init(self, _info: Any) -> None:
        if not self.id:
            self.id = event_id(
                self.agent,
                self.seq,
                self.kind.value,
                self.node,
                json.dumps(self.payload, sort_keys=True, default=str),
            )

    @property
    def is_autonomous(self) -> bool:
        """A decision counts toward the autonomy budget unless it reaches a
        human gate or is a refusal/escalation that defers authority."""
        return self.kind not in (EventKind.HITL, EventKind.REFUSAL, EventKind.ESCALATION)


# -------------------------------------------------------------------------------------------------
# Baseline (certified OSCAL-derived) control model - Thinking in moving it to a YAML .. why not ...
# --------------------------------------------------------------------------------------------------


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ControlDef(BaseModel):
    """One behavioral control in the DL-1..7 family."""

    id: str  # e.g. "DL-3"
    title: str
    description: str
    nist_800_53: list[str] = Field(default_factory=list)
    is_ca7: bool = False  # continuous-monitoring umbrella anchor


class BaselinePolicy(BaseModel):
    """Executable compilation of a certified baseline.

    Fail-closed: any referenced control parameter that is missing or
    malformed raises at compile time rather than silently passing.
    """

    agent: str
    baseline_id: str
    baseline_hash: str
    title: str
    controls: list[ControlDef] = Field(default_factory=list)

    # -- bound policy parameters (the `dl:` vocabulary) --------------------
    # DL-1 decision rights: per-node tool allowlists
    tool_allowlist: dict[str, list[str]] = Field(default_factory=dict)
    # DL-2 routing: allowed (from -> to) transitions
    allowed_routes: list[tuple[str, str]] = Field(default_factory=list)
    # DL-3 HITL triggers: condition -> gate node
    hitl_when: list[dict[str, Any]] = Field(default_factory=list)
    # DL-4 fallback: on error kind, required recovery node
    fallback_for: dict[str, str] = Field(default_factory=dict)
    # DL-5 critical sinks: nodes whose use escalates severity
    critical_sinks: list[str] = Field(default_factory=list)
    # DL-6 autonomy budget: max fraction of decisions that may be autonomous
    autonomy_budget: float = 1.0
    # DL-6 helper: nodes whose tool_calls count as autonomous dispositions
    decision_nodes: list[str] = Field(default_factory=list)
    # DL-7 required steps: nodes that must appear in every cycle's trace
    required_steps: list[str] = Field(default_factory=list)
    # DL-8 resource budget: certified per-currency ceilings (currency names are
    # the driftlab.sensor Currency values; see ADR-001)
    resource_ceilings: dict[str, float] = Field(default_factory=dict)

    def digest(self) -> str:
        return stable_json_digest(self.model_dump(mode="json"))