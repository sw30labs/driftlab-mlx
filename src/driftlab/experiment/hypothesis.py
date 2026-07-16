"""Drift hypothesis generator.

Turns each MEDIUM+ anomaly into a falsifiable, testable hypothesis with a
concrete probe spec. The experiment loop later executes the probe against the
replay sandbox and returns a deterministic verdict (CONFIRMED / REFUTED /
INCONCLUSIVE).

Three claim shapes:

* **Existence** (DL-1, DL-2, DL-3, DL-4, DL-5) — "an unauthorized X occurred".
  One independently reproduced violation is proof; zero violations across
  sufficient samples is refutation.
* **Rate** (DL-6) — "autonomy exceeds budget". Decisions are split into ordered
  windows; drift confirms only when windows *sustain* the excess (a one-off
  burst stays INCONCLUSIVE).
* **Resource** (DL-8) — "cumulative spend crossed the certified ceiling". The
  probe replays the recorded resource stream (telemetry plane, ADR-001): a
  record over the ceiling confirms; a full stream that never crosses refutes;
  an absent stream is INCONCLUSIVE by construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from ..anomaly import Anomaly
from ..domain import BaselinePolicy


class ClaimKind(str, Enum):
    EXISTENCE = "existence"
    RATE = "rate"
    RESOURCE = "resource"


class Verdict(str, Enum):
    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"


@dataclass
class Hypothesis:
    anomaly_id: str
    control: str
    claim: str
    kind: ClaimKind
    # A picklable spec the experiment loop uses to build a replay predicate.
    predicate_spec: dict[str, Any]
    min_samples: int = 5
    # For RATE claims:
    window_size: int = 5
    rate_threshold: float | None = None


# Predicate builders keyed by control. Each returns a callable over DecisionEvent.
def _build_predicate(spec: dict[str, Any]) -> Callable:
    kind = spec["match"]
    if kind == "tool_not_in_allowlist":
        node, allow = spec["node"], set(spec["allow"])
        return lambda e: e.kind.value == "tool_call" and e.node == node and e.tool not in allow
    if kind == "route_not_allowed":
        allowed = set((f, t) for f, t in spec["allowed"])
        return lambda e: e.kind.value == "route" and (e.route_from, e.route_to) not in allowed
    if kind == "hitl_bypass":
        node = spec["node"]
        cond = spec["condition"]
        import re

        m = re.match(r"(\w+)\s*(>|<|>=|<=|==)\s*([\-\d.]+)", cond)
        field_, op, rhs = m.group(1), m.group(2), float(m.group(3))
        return lambda e: (
            e.kind.value == "tool_call" and e.node == node
            and _cmp(getattr(e, field_, e.payload.get(field_)), op, rhs)
        )
    if kind == "missing_fallback":
        err = spec["error"]
        return lambda e: e.kind.value == "error" and e.payload.get("error", "error") == err
    if kind == "autonomy_excess":
        decision_nodes = set(spec["decision_nodes"])
        return lambda e: e.kind.value == "tool_call" and e.node in decision_nodes
    raise ValueError(f"unknown predicate spec {kind}")


def _cmp(lhs, op, rhs) -> bool:
    if lhs is None:
        return False
    lhs = float(lhs)
    return {"<": lhs < rhs, ">": lhs > rhs, "<=": lhs <= rhs,
            ">=": lhs >= rhs, "==": lhs == rhs}[op]


def generate(anomaly: Anomaly, policy: BaselinePolicy) -> Hypothesis:
    c = anomaly.control
    if c == "DL-1":
        extra = anomaly.extra
        node = extra.get("node")
        return Hypothesis(
            anomaly.id, c, f"unauthorized tool {extra.get('tool')!r} used at {node!r}",
            ClaimKind.EXISTENCE,
            {"match": "tool_not_in_allowlist", "node": node,
             "allow": list(policy.tool_allowlist.get(node, []))}, min_samples=1)
    if c == "DL-2":
        extra = anomaly.extra
        return Hypothesis(
            anomaly.id, c, f"uncertified route {extra.get('from')!r}->{extra.get('to')!r}",
            ClaimKind.EXISTENCE,
            {"match": "route_not_allowed", "allowed": [list(r) for r in policy.allowed_routes]},
            min_samples=1)
    if c == "DL-3":
        extra = anomaly.extra
        return Hypothesis(
            anomaly.id, c, f"HITL bypass for {extra.get('rule')} ({extra.get('condition')})",
            ClaimKind.EXISTENCE,
            {"match": "hitl_bypass", "node": "decide", "condition": extra["condition"]},
            min_samples=1)
    if c == "DL-4":
        extra = anomaly.extra
        return Hypothesis(
            anomaly.id, c, f"missing fallback for error {extra.get('error')!r}",
            ClaimKind.EXISTENCE,
            {"match": "missing_fallback", "error": extra["error"]}, min_samples=1)
    if c == "DL-6":
        extra = anomaly.extra
        return Hypothesis(
            anomaly.id, c, f"autonomy {extra['rate']:.0%} exceeds budget {extra['budget']:.0%}",
            ClaimKind.RATE,
            {"match": "autonomy_excess", "decision_nodes": list(policy.decision_nodes)},
            window_size=5, rate_threshold=extra["budget"])
    if c == "DL-8":
        extra = anomaly.extra
        if "currency" in extra:  # ceiling breach
            return Hypothesis(
                anomaly.id, c,
                f"{extra['currency']} spend {extra['spent']:g} crossed certified "
                f"ceiling {extra['ceiling']:g}",
                ClaimKind.RESOURCE,
                {"match": "resource_over_ceiling", "currency": extra["currency"],
                 "ceiling": extra["ceiling"]}, min_samples=1)
        # telemetry missing — probe the (absent) stream; INCONCLUSIVE by construction
        return Hypothesis(
            anomaly.id, c, "certified resource ceilings have no observed telemetry",
            ClaimKind.RESOURCE,
            {"match": "resource_over_ceiling", "currency": None, "ceiling": None},
            min_samples=1)
    # DL-5 escalations and DL-7 are not independently probed here.
    return Hypothesis(
        anomaly.id, c, anomaly.title, ClaimKind.EXISTENCE,
        {"match": "tool_not_in_allowlist", "node": "", "allow": []}, min_samples=1)