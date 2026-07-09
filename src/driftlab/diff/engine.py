"""Behavioral diff engine: observed DecisionEvents vs certified BaselinePolicy.

Keeps glass-graph's contract — ``compare(expected, observed) ->
list[DeviationRecord]`` with deterministic fingerprints — but replaces
structural set-difference with behavioral control checks: tool allowlists,
routing rules, HITL triggers, autonomy budgets, fallback protocols, and
required steps. Pure deterministic Python; every loop is sorted; no LLM
anywhere in this module.
"""

from __future__ import annotations

from collections import defaultdict

from driftlab.baseline.model import BaselinePolicy
from driftlab.diff.behavior_graph import BehaviorGraph
from driftlab.domain.models import (
    ComparisonType,
    DecisionEvent,
    DeviationRecord,
    DriftKind,
    EventType,
    EvidenceRef,
)

#: evidence lists are capped (deterministically: sorted, then sliced) to keep
#: ledgers reviewable; full counts are always preserved in ``measurement``.
MAX_EVIDENCE_IDS = 50


def select_autonomy_decisions(
    policy: BaselinePolicy, events: list[DecisionEvent]
) -> tuple[list[DecisionEvent], list[DecisionEvent]]:
    """(all routing decisions at autonomy-relevant nodes, the full-autonomy subset).

    Shared by the diff engine and the autonomy probe so both measure the same
    population — a probe must re-test the claim, not a different statistic.
    """
    if policy.autonomy_auto_targets:
        if policy.autonomy_decision_nodes:
            decision_nodes = set(policy.autonomy_decision_nodes)
        else:
            decision_nodes = {
                frm
                for frm, targets in policy.allowed_routes.items()
                if any(t in policy.autonomy_auto_targets for t in targets)
            }
        routes = [
            e
            for e in events
            if e.event_type is EventType.ROUTE
            and e.target
            and (not decision_nodes or e.node in decision_nodes)
        ]
        auto = [e for e in routes if e.target in policy.autonomy_auto_targets]
    else:
        routes = [e for e in events if e.autonomy is not None]
        auto = [e for e in routes if e.autonomy == "auto"]
    return routes, auto


def _runs(events: list[DecisionEvent]) -> dict[str, list[DecisionEvent]]:
    by_run: dict[str, list[DecisionEvent]] = defaultdict(list)
    for event in events:
        by_run[event.run_id].append(event)
    return {run_id: sorted(evs, key=lambda e: e.seq) for run_id, evs in sorted(by_run.items())}


def _evidence(control_id: str, event_ids: list[str], run_ids: list[str]) -> EvidenceRef:
    return EvidenceRef(
        origin="trace",
        control_id=control_id,
        event_ids=sorted(set(event_ids))[:MAX_EVIDENCE_IDS],
        run_ids=sorted(set(run_ids))[:MAX_EVIDENCE_IDS],
    )


class BehavioralDiffEngine:
    """Deterministic observed-vs-baseline behavioral diff."""

    def compare(
        self,
        *,
        policy: BaselinePolicy,
        events: list[DecisionEvent],
        comparison_type: ComparisonType = ComparisonType.OBSERVED_VS_BASELINE,
    ) -> list[DeviationRecord]:
        ct = comparison_type.value
        if not events:
            # glass-graph invariant: missing evidence is a finding, not a crash.
            return [
                DeviationRecord(
                    comparison_type=comparison_type,
                    kind=DriftKind.EVIDENCE_QUALITY,
                    fingerprint=f"{ct}:evidence_quality:no_trace",
                    control_id=policy.control_map.get("steps"),
                    title="No runtime traces available",
                    description=(
                        f"No decision events were observed for agent '{policy.agent_id}'. "
                        "Behavioral compliance cannot be attested for this cycle."
                    ),
                )
            ]

        runs = _runs(events)
        deviations: list[DeviationRecord] = []
        deviations += self._check_tools(ct, comparison_type, policy, events)
        deviations += self._check_routes(ct, comparison_type, policy, events)
        deviations += self._check_hitl(ct, comparison_type, policy, runs)
        deviations += self._check_autonomy(ct, comparison_type, policy, events)
        deviations += self._check_fallback(ct, comparison_type, policy, runs)
        deviations += self._check_required_steps(ct, comparison_type, policy, runs)
        deviations.sort(key=lambda d: d.fingerprint)
        return deviations

    # -- DL-1: decision rights / tool allowlists ------------------------------
    def _check_tools(self, ct, comparison_type, policy, events) -> list[DeviationRecord]:
        if not policy.has_tool_policy():
            return []
        control = policy.control_map.get("tools", "dl-1")
        seen: dict[tuple[str, str], list[DecisionEvent]] = defaultdict(list)
        for event in events:
            if event.event_type is EventType.TOOL_CALL and event.tool:
                seen[(event.node, event.tool)].append(event)
        out = []
        for (node, tool), evs in sorted(seen.items()):
            if policy.tool_allowed(node, tool):
                continue
            out.append(
                DeviationRecord(
                    comparison_type=comparison_type,
                    kind=DriftKind.UNEXPECTED_TOOL_CALL,
                    fingerprint=f"{ct}:unexpected_tool_call:{node}:{tool}",
                    control_id=control,
                    title=f"Unauthorized tool '{tool}' invoked at '{node}'",
                    description=(
                        f"Tool '{tool}' was called {len(evs)} time(s) at node '{node}' but is not in "
                        f"the certified decision-rights allowlist ({control.upper()})."
                    ),
                    impacted_nodes=[node],
                    evidence=_evidence(control, [e.event_id for e in evs], [e.run_id for e in evs]),
                    measurement={"call_count": len(evs), "tool": tool},
                )
            )
        return out

    # -- DL-2: routing rules ---------------------------------------------------
    def _check_routes(self, ct, comparison_type, policy, events) -> list[DeviationRecord]:
        if not policy.allowed_routes:
            return []
        control = policy.control_map.get("routes", "dl-2")
        seen: dict[tuple[str, str], list[DecisionEvent]] = defaultdict(list)
        for event in events:
            if event.event_type is EventType.ROUTE and event.target:
                seen[(event.node, event.target)].append(event)
        out = []
        for (frm, to), evs in sorted(seen.items()):
            if policy.route_allowed(frm, to) is not False:  # None = uncertified from-node
                continue
            out.append(
                DeviationRecord(
                    comparison_type=comparison_type,
                    kind=DriftKind.UNAUTHORIZED_ROUTE,
                    fingerprint=f"{ct}:unauthorized_route:{frm}->{to}",
                    control_id=control,
                    title=f"Unauthorized route {frm} -> {to}",
                    description=(
                        f"The agent routed {frm} -> {to} {len(evs)} time(s); certified targets for "
                        f"'{frm}' are {sorted(policy.allowed_routes[frm])} ({control.upper()})."
                    ),
                    impacted_nodes=[frm, to],
                    impacted_routes=[f"{frm}->{to}"],
                    evidence=_evidence(control, [e.event_id for e in evs], [e.run_id for e in evs]),
                    measurement={"transition_count": len(evs), "allowed_targets": sorted(policy.allowed_routes[frm])},
                )
            )
        return out

    # -- DL-3: human-in-the-loop triggers ---------------------------------------
    @staticmethod
    def run_satisfies_trigger(run_events: list[DecisionEvent], trigger) -> bool | None:
        """None = trigger never matched in this run; True/False = matched and
        (was / was not) escalated to the required human gate."""
        match_seq: int | None = None
        for event in run_events:
            if event.node == trigger.at_node and trigger.matches(event.decision_context):
                match_seq = event.seq
                break
        if match_seq is None:
            return None
        for event in run_events:
            if event.seq < match_seq:
                continue
            if event.event_type is EventType.ROUTE and event.target == trigger.require_route_to:
                return True
            if event.event_type in (EventType.HITL, EventType.ESCALATION) and (
                event.node == trigger.require_route_to or event.node == trigger.at_node
            ):
                return True
            if event.node == trigger.require_route_to:
                return True
        return False

    def _check_hitl(self, ct, comparison_type, policy, runs) -> list[DeviationRecord]:
        out = []
        control = policy.control_map.get("hitl", "dl-3")
        for trigger in sorted(policy.hitl_triggers, key=lambda t: t.trigger_id):
            matched_runs: list[str] = []
            violating: dict[str, list[str]] = {}
            for run_id, run_events in runs.items():
                verdict = self.run_satisfies_trigger(run_events, trigger)
                if verdict is None:
                    continue
                matched_runs.append(run_id)
                if verdict is False:
                    violating[run_id] = [
                        e.event_id
                        for e in run_events
                        if e.node == trigger.at_node and trigger.matches(e.decision_context)
                    ]
            if not violating:
                continue
            rate = round(len(violating) / len(matched_runs), 4)
            conds = " & ".join(c.render() for c in trigger.when) or "always"
            out.append(
                DeviationRecord(
                    comparison_type=comparison_type,
                    kind=DriftKind.MISSING_HITL,
                    fingerprint=f"{ct}:missing_hitl:{trigger.trigger_id}:{trigger.at_node}",
                    control_id=control,
                    title=f"HITL trigger '{trigger.trigger_id}' bypassed at '{trigger.at_node}'",
                    description=(
                        f"{len(violating)} of {len(matched_runs)} run(s) matching [{conds}] at "
                        f"'{trigger.at_node}' were never escalated to '{trigger.require_route_to}' "
                        f"as the certified baseline requires ({control.upper()})."
                    ),
                    impacted_nodes=[trigger.at_node, trigger.require_route_to],
                    evidence=_evidence(
                        control,
                        [eid for eids in violating.values() for eid in eids],
                        list(violating.keys()),
                    ),
                    measurement={
                        "trigger_id": trigger.trigger_id,
                        "matched_runs": len(matched_runs),
                        "violating_runs": len(violating),
                        "violation_rate": rate,
                        "conditions": conds,
                        "required_route": trigger.require_route_to,
                    },
                )
            )
        return out

    # -- DL-6: autonomy budget ---------------------------------------------------
    def _check_autonomy(self, ct, comparison_type, policy, events) -> list[DeviationRecord]:
        if policy.max_auto_fraction is None:
            return []
        control = policy.control_map.get("autonomy", "dl-6")
        routes, auto = select_autonomy_decisions(policy, events)
        if not routes:
            return []
        fraction = round(len(auto) / len(routes), 4)
        if fraction <= policy.max_auto_fraction:
            return []
        overshoot = round(fraction - policy.max_auto_fraction, 4)
        return [
            DeviationRecord(
                comparison_type=comparison_type,
                kind=DriftKind.AUTONOMY_BUDGET_EXCEEDED,
                fingerprint=f"{ct}:autonomy_budget_exceeded:{control}",
                control_id=control,
                title="Autonomy budget exceeded",
                description=(
                    f"{len(auto)} of {len(routes)} routing decisions ({fraction:.0%}) took the "
                    f"full-autonomy path; the certified budget is {policy.max_auto_fraction:.0%} "
                    f"({control.upper()})."
                ),
                impacted_nodes=sorted({e.node for e in auto}),
                evidence=_evidence(control, [e.event_id for e in auto], [e.run_id for e in auto]),
                measurement={
                    "observed_fraction": fraction,
                    "allowed_fraction": policy.max_auto_fraction,
                    "overshoot": overshoot,
                    "auto_decisions": len(auto),
                    "total_decisions": len(routes),
                },
            )
        ]

    # -- DL-4: fallback protocols ---------------------------------------------
    def _check_fallback(self, ct, comparison_type, policy, runs) -> list[DeviationRecord]:
        if not policy.fallback_rules:
            return []
        control = policy.control_map.get("fallback", "dl-4")
        # exact-node rules take precedence over "*"
        rules = sorted(policy.fallback_rules, key=lambda r: (r.on_error_at == "*", r.on_error_at))
        violations: dict[str, list[DecisionEvent]] = defaultdict(list)
        for run_events in runs.values():
            for i, event in enumerate(run_events):
                if event.event_type is not EventType.ERROR:
                    continue
                rule = next((r for r in rules if r.applies_to(event.node)), None)
                if rule is None:
                    continue
                nxt = run_events[i + 1] if i + 1 < len(run_events) else None
                ok = nxt is not None and (
                    nxt.node == rule.require_next_node
                    or (nxt.event_type is EventType.ROUTE and nxt.target == rule.require_next_node)
                    or nxt.event_type is EventType.FALLBACK
                )
                if not ok:
                    violations[f"{rule.on_error_at}->{rule.require_next_node}"].append(event)
        out = []
        for key, evs in sorted(violations.items()):
            on_node, required = key.split("->", 1)
            out.append(
                DeviationRecord(
                    comparison_type=comparison_type,
                    kind=DriftKind.FALLBACK_VIOLATION,
                    fingerprint=f"{ct}:fallback_violation:{key}",
                    control_id=control,
                    title=f"Fallback protocol not followed after error at '{on_node}'",
                    description=(
                        f"{len(evs)} error(s) at '{on_node}' were not followed by the certified "
                        f"fallback '{required}' ({control.upper()})."
                    ),
                    impacted_nodes=sorted({e.node for e in evs} | {required}),
                    evidence=_evidence(control, [e.event_id for e in evs], [e.run_id for e in evs]),
                    measurement={"error_count": len(evs), "required_fallback": required},
                )
            )
        return out

    # -- DL-7: required steps ----------------------------------------------------
    def _check_required_steps(self, ct, comparison_type, policy, runs) -> list[DeviationRecord]:
        if not policy.required_steps:
            return []
        control = policy.control_map.get("steps", "dl-7")
        out = []
        for step in sorted(policy.required_steps):
            missing_runs = sorted(
                run_id
                for run_id, run_events in runs.items()
                if not any(e.node == step for e in run_events)
            )
            if not missing_runs:
                continue
            out.append(
                DeviationRecord(
                    comparison_type=comparison_type,
                    kind=DriftKind.MISSING_STEP,
                    fingerprint=f"{ct}:missing_step:{step}",
                    control_id=control,
                    title=f"Required step '{step}' skipped",
                    description=(
                        f"{len(missing_runs)} of {len(runs)} run(s) never executed the certified "
                        f"required step '{step}' ({control.upper()})."
                    ),
                    impacted_nodes=[step],
                    evidence=EvidenceRef(origin="trace", control_id=control, run_ids=missing_runs[:MAX_EVIDENCE_IDS]),
                    measurement={"missing_runs": len(missing_runs), "total_runs": len(runs)},
                )
            )
        return out


def build_behavior_graph(events: list[DecisionEvent]) -> BehaviorGraph:
    return BehaviorGraph(events)
