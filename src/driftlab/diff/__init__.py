"""Behavioral diff engine — observed DecisionEvent stream vs certified baseline.

Pure deterministic Python. Each of the eight DL controls is checked
independently; the result is a list of raw findings (control id, evidence,
candidate severity). The anomaly engine turns these into scored anomalies.

DL-8 audits the *resource telemetry plane* (a recorded stream of sensor
ResourceRecords, separate from the decision trace — see ADR-001): replaying
the same stream against the same baseline yields identical findings.

The engine also builds a NetworkX behavior graph for path/route analysis and
for critical-sink reachability (DL-5 escalation).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from ..domain import BaselinePolicy, DecisionEvent
from ..sensor import ResourceRecord, cumulative_spend


@dataclass
class RawFinding:
    control: str  # DL-1..8
    title: str
    detail: str
    evidence: list[str]  # event ids (DERIVED_FROM provenance)
    severity_hint: str  # suggested severity before waiver/scoring
    extra: dict[str, Any] = field(default_factory=dict)


# Condition grammar for hitl-when: supports "amount>50000", "sentiment<0.2".
def _eval_condition(cond: str, ev: DecisionEvent) -> bool:
    m = re.match(r"\s*(\w+)\s*(>=|<=|>|<|==)\s*([\-\d.]+)\s*", cond)
    if not m:
        return False
    field_name, op, rhs = m.group(1), m.group(2), float(m.group(3))
    lhs = getattr(ev, field_name, None)
    if lhs is None:
        lhs = ev.payload.get(field_name)
    if lhs is None:
        return False
    lhs = float(lhs)
    return {
        ">": lhs > rhs, ">=": lhs >= rhs, "<": lhs < rhs,
        "<=": lhs <= rhs, "==": lhs == rhs,
    }[op]


class BehavioralDiff:
    def __init__(
        self,
        policy: BaselinePolicy,
        events: list[DecisionEvent],
        resource_records: list[ResourceRecord] | None = None,
    ):
        self.policy = policy
        self.events = events
        self.resource_records = resource_records
        self.graph = self._build_graph()

    # -- graph -------------------------------------------------------------
    def _build_graph(self) -> nx.DiGraph:
        g = nx.DiGraph()
        for ev in self.events:
            if ev.kind.value == "route" and ev.route_from and ev.route_to:
                g.add_edge(ev.route_from, ev.route_to)
        return g

    # -- public entry ------------------------------------------------------
    def run(self) -> list[RawFinding]:
        findings: list[RawFinding] = []
        findings += self.check_dl1_decision_rights()
        findings += self.check_dl2_routing()
        findings += self.check_dl3_hitl()
        findings += self.check_dl4_fallback()
        findings += self.check_dl6_autonomy()
        findings += self.check_dl7_required_steps()
        findings += self.check_dl8_resource_budget()
        return findings

    # -- DL-1 decision rights ---------------------------------------------
    def check_dl1_decision_rights(self) -> list[RawFinding]:
        out: list[RawFinding] = []
        for ev in self.events:
            if ev.kind.value != "tool_call" or not ev.tool:
                continue
            allow = self.policy.tool_allowlist.get(ev.node)
            if allow is None:
                # node has no allowlist; only flag if node is a decision sink
                continue
            if ev.tool not in allow:
                out.append(RawFinding(
                    "DL-1", "Unauthorized tool on node",
                    f"tool {ev.tool!r} used at node {ev.node!r}; allowlist={allow}",
                    [ev.id], "high",
                    {"node": ev.node, "tool": ev.tool}))
        return out

    # -- DL-2 routing ------------------------------------------------------
    def check_dl2_routing(self) -> list[RawFinding]:
        out: list[RawFinding] = []
        allowed = set(self.policy.allowed_routes)
        for ev in self.events:
            if ev.kind.value != "route" or not ev.route_from or not ev.route_to:
                continue
            # The entry transition (from the synthetic __start__ node) is always
            # permitted — it represents the agent receiving a new case.
            if ev.route_from == "__start__":
                continue
            if (ev.route_from, ev.route_to) not in allowed:
                out.append(RawFinding(
                    "DL-2", "Uncertified routing transition",
                    f"route {ev.route_from!r} -> {ev.route_to!r} not in certified set",
                    [ev.id], "medium",
                    {"from": ev.route_from, "to": ev.route_to}))
        return out

    # -- DL-3 human-in-the-loop -------------------------------------------
    def check_dl3_hitl(self) -> list[RawFinding]:
        out: list[RawFinding] = []
        # A hitl_when rule is violated if a decision matching the condition
        # is NOT followed (eventually) by a HITL event for that decision.
        hitl_nodes = {h["node"] for h in self.policy.hitl_when}
        for ev in self.events:
            for rule in self.policy.hitl_when:
                if not _eval_condition(rule["condition"], ev):
                    continue
                # Was there a subsequent HITL event in this trace?
                matched = any(
                    e.kind.value == "hitl" and e.seq > ev.seq and e.node in hitl_nodes
                    for e in self.events
                )
                if not matched:
                    out.append(RawFinding(
                        "DL-3", "Human-in-the-loop bypass",
                        f"decision matching {rule['tag']} ({rule['condition']}) "
                        f"at node {ev.node!r} reached no human gate {hitl_nodes}",
                        [ev.id], "critical",
                        {"rule": rule["tag"], "condition": rule["condition"]}))
                    break
        return out

    # -- DL-4 fallback -----------------------------------------------------
    def check_dl4_fallback(self) -> list[RawFinding]:
        out: list[RawFinding] = []
        for i, ev in enumerate(self.events):
            if ev.kind.value != "error":
                continue
            err_kind = ev.payload.get("error", "error")
            required = self.policy.fallback_for.get(err_kind) or self.policy.fallback_for.get("error")
            if not required:
                continue
            # Look for the recovery node within the next few events.
            recovered = any(
                e.seq > ev.seq and e.node == required
                for e in self.events
            )
            if not recovered:
                out.append(RawFinding(
                    "DL-4", "Missing error fallback",
                    f"error {err_kind!r} at node {ev.node!r} had no recovery to {required!r}",
                    [ev.id], "high",
                    {"error": err_kind, "expected": required}))
        return out

    # -- DL-5 critical sinks (severity escalation, not an independent check) -
    # Implemented in the anomaly engine as ``apply_critical_sink_escalation``:
    # when a finding's evidence reaches a certified critical sink, its severity
    # is escalated toward CRITICAL. DL-5 therefore never emits its own finding;
    # it amplifies the severity of genuine violations that touch irreversible
    # actions (disburse, respond, ...) - This needs to be perfected I think.

    # -- DL-6 autonomy budget ---------------------------------------------
    def check_dl6_autonomy(self) -> list[RawFinding]:
        # Autonomy rate = autonomous dispositions / (autonomous dispositions +
        # human-authority events). A "disposition" is a tool_call at a certified
        # decision node; a "human-authority event" is HITL / refusal / escalation.
        decision_nodes = set(self.policy.decision_nodes)
        autonomous = sum(
            1 for e in self.events
            if e.kind.value == "tool_call" and e.node in decision_nodes
        )
        human_authority = sum(
            1 for e in self.events
            if e.kind.value in ("hitl", "refusal", "escalation")
        )
        total = autonomous + human_authority
        if total == 0:
            return []
        rate = autonomous / total
        if rate > self.policy.autonomy_budget:
            return [RawFinding(
                "DL-6", "Autonomy budget exceeded",
                f"autonomous fraction {rate:.0%} exceeds certified budget "
                f"{self.policy.autonomy_budget:.0%} ({autonomous} autonomous / "
                f"{total} dispositions)",
                [e.id for e in self.events if e.kind.value == "tool_call" and e.node in decision_nodes],
                "high",
                {"rate": rate, "budget": self.policy.autonomy_budget,
                 "autonomous": autonomous, "total": total})]
        return []

    # -- DL-8 resource budget ---------------------------------------------
    def check_dl8_resource_budget(self) -> list[RawFinding]:
        # Certified ceilings vs the recorded resource stream (telemetry
        # plane). Fail-closed: certify -> must observe. Evidence ids are
        # ResourceRecord ids; DL-5 escalation skips them (not decision events).
        ceilings = self.policy.resource_ceilings
        if not ceilings:
            return []
        records = self.resource_records
        if not records:
            return [RawFinding(
                "DL-8", "Resource telemetry missing",
                f"baseline certifies resource ceilings for {sorted(ceilings)} "
                f"but no resource stream was observed this cycle",
                [], "medium",
                {"ceilings": dict(sorted(ceilings.items())), "records": 0})]
        final = cumulative_spend(records)
        breaker_fired = any(r.tripped for r in records)
        out: list[RawFinding] = []
        for cur in sorted(ceilings):
            ceiling = ceilings[cur]
            spent = final.get(cur, 0.0)
            if spent > ceiling:
                evidence = [
                    r.id for r in records if float(r.spent.get(cur, 0.0)) > ceiling
                ]
                mechanism = (
                    "sensor breaker fired; overshoot occurred within the final "
                    "metered iteration(s)" if breaker_fired
                    else "sensor breaker never fired"
                )
                out.append(RawFinding(
                    "DL-8", "Resource budget exceeded",
                    f"{cur} spent {spent:g} exceeds certified ceiling "
                    f"{ceiling:g} ({mechanism})",
                    evidence, "high",
                    {"currency": cur, "spent": spent, "ceiling": ceiling,
                     "records": len(records), "breaker_fired": breaker_fired}))
        return out

    # -- DL-7 required steps ----------------------------------------------
    def check_dl7_required_steps(self) -> list[RawFinding]:
        out: list[RawFinding] = []
        seen_nodes = {e.node for e in self.events}
        for step in self.policy.required_steps:
            if step not in seen_nodes:
                out.append(RawFinding(
                    "DL-7", "Required step missing",
                    f"certified step {step!r} absent from this cycle's trace",
                    [], "medium", {"step": step}))
        return out