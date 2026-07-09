"""Deterministic probe designers and executors.

A probe is a controlled re-test of a drift hypothesis against a sandboxed
replay: it evaluates the *entire matching population* fresh, independent of
whichever events the original anomaly happened to cite. Two probe classes:

* existence probes — the violating behavior either reproduces or it doesn't
  (tool calls, routes, HITL bypasses, fallback breaks, skipped steps). One
  reproduced violation is deterministic proof.
* rate probes — the claim is a *sustained* statistical deviation (autonomy
  budget). The probe splits decisions into ordered windows and asks how many
  windows independently exceed the budget: drift, not a one-off burst.
"""

from __future__ import annotations

from typing import Any

from driftlab.baseline.model import BaselinePolicy
from driftlab.diff.engine import BehavioralDiffEngine, select_autonomy_decisions
from driftlab.domain.models import DriftHypothesis, DriftKind, EventType, ProbeResult
from driftlab.experiment.sandbox import Sandbox
from driftlab.identity import deterministic_id

RATE_KINDS = {DriftKind.AUTONOMY_BUDGET_EXCEEDED}


def design_probe(hypothesis: DriftHypothesis, iteration: int) -> dict[str, Any]:
    """Probe spec for this iteration. Reflection widens scope deterministically."""
    spec = dict(hypothesis.probe_spec)
    spec["scope"] = iteration + 1
    if spec.get("probe_kind") == "autonomy_windows":
        spec["windows"] = int(spec.get("windows", 3)) + iteration  # finer granularity each pass
    return spec


def execute_probe(
    *,
    sandbox: Sandbox,
    hypothesis: DriftHypothesis,
    policy: BaselinePolicy,
    probe_spec: dict[str, Any],
) -> ProbeResult:
    sandbox.assert_isolated()  # bounded autonomy: replay-only, enforced every call
    kind = probe_spec.get("probe_kind")
    probe_id = deterministic_id("prb", f"{hypothesis.hypothesis_id}:{probe_spec.get('scope', 1)}:{kind}")

    if kind == "hitl_replay":
        return _probe_hitl(sandbox, policy, probe_spec, probe_id)
    if kind == "tool_replay":
        return _probe_tool(sandbox, probe_spec, probe_id)
    if kind == "route_replay":
        return _probe_route(sandbox, probe_spec, probe_id)
    if kind == "autonomy_windows":
        return _probe_autonomy(sandbox, policy, probe_spec, probe_id)
    if kind == "fallback_replay":
        return _probe_fallback(sandbox, policy, probe_id)
    if kind == "step_replay":
        return _probe_step(sandbox, probe_spec, probe_id)
    raise ValueError(f"unknown probe kind {kind!r}")


# -- existence probes ---------------------------------------------------------
def _probe_hitl(sandbox: Sandbox, policy: BaselinePolicy, spec: dict, probe_id: str) -> ProbeResult:
    trigger = next((t for t in policy.hitl_triggers if t.trigger_id == spec.get("trigger_id")), None)
    if trigger is None:
        return ProbeResult(probe_id=probe_id, samples=0, violations=0, violation_rate=0.0,
                           detail={"error": f"trigger {spec.get('trigger_id')!r} not in baseline"})
    matched, violating, violating_events = [], [], []
    for run_id, run_events in sandbox.runs().items():
        verdict = BehavioralDiffEngine.run_satisfies_trigger(run_events, trigger)
        if verdict is None:
            continue
        matched.append(run_id)
        if verdict is False:
            violating.append(run_id)
            violating_events.extend(
                e.event_id for e in run_events
                if e.node == trigger.at_node and trigger.matches(e.decision_context)
            )
    return ProbeResult(
        probe_id=probe_id,
        samples=len(matched),
        violations=len(violating),
        violation_rate=round(len(violating) / len(matched), 4) if matched else 0.0,
        matched_run_ids=sorted(matched),
        violating_event_ids=sorted(violating_events),
        detail={"trigger_id": trigger.trigger_id, "required_route": trigger.require_route_to},
    )


def _probe_tool(sandbox: Sandbox, spec: dict, probe_id: str) -> ProbeResult:
    node, tool = str(spec.get("node")), str(spec.get("tool"))
    matched, violating, violating_events = [], [], []
    for run_id, run_events in sandbox.runs().items():
        if not any(e.node == node for e in run_events):
            continue
        matched.append(run_id)
        hits = [e for e in run_events if e.event_type is EventType.TOOL_CALL and e.node == node and e.tool == tool]
        if hits:
            violating.append(run_id)
            violating_events.extend(e.event_id for e in hits)
    return ProbeResult(
        probe_id=probe_id,
        samples=len(matched),
        violations=len(violating),
        violation_rate=round(len(violating) / len(matched), 4) if matched else 0.0,
        matched_run_ids=sorted(matched),
        violating_event_ids=sorted(violating_events),
        detail={"node": node, "tool": tool},
    )


def _probe_route(sandbox: Sandbox, spec: dict, probe_id: str) -> ProbeResult:
    frm, _, to = str(spec.get("route", "?->?")).partition("->")
    matched, violating, violating_events = [], [], []
    for run_id, run_events in sandbox.runs().items():
        if not any(e.node == frm for e in run_events):
            continue
        matched.append(run_id)
        hits = [e for e in run_events if e.event_type is EventType.ROUTE and e.node == frm and e.target == to]
        if hits:
            violating.append(run_id)
            violating_events.extend(e.event_id for e in hits)
    return ProbeResult(
        probe_id=probe_id,
        samples=len(matched),
        violations=len(violating),
        violation_rate=round(len(violating) / len(matched), 4) if matched else 0.0,
        matched_run_ids=sorted(matched),
        violating_event_ids=sorted(violating_events),
        detail={"route": f"{frm}->{to}"},
    )


def _probe_fallback(sandbox: Sandbox, policy: BaselinePolicy, probe_id: str) -> ProbeResult:
    rules = sorted(policy.fallback_rules, key=lambda r: (r.on_error_at == "*", r.on_error_at))
    samples = violations = 0
    violating_events, matched_runs = [], set()
    for run_id, run_events in sandbox.runs().items():
        for i, event in enumerate(run_events):
            if event.event_type is not EventType.ERROR:
                continue
            rule = next((r for r in rules if r.applies_to(event.node)), None)
            if rule is None:
                continue
            samples += 1
            matched_runs.add(run_id)
            nxt = run_events[i + 1] if i + 1 < len(run_events) else None
            ok = nxt is not None and (
                nxt.node == rule.require_next_node
                or (nxt.event_type is EventType.ROUTE and nxt.target == rule.require_next_node)
                or nxt.event_type is EventType.FALLBACK
            )
            if not ok:
                violations += 1
                violating_events.append(event.event_id)
    return ProbeResult(
        probe_id=probe_id,
        samples=samples,
        violations=violations,
        violation_rate=round(violations / samples, 4) if samples else 0.0,
        matched_run_ids=sorted(matched_runs),
        violating_event_ids=sorted(violating_events),
        detail={"rule_count": len(rules)},
    )


def _probe_step(sandbox: Sandbox, spec: dict, probe_id: str) -> ProbeResult:
    step = str(spec.get("step"))
    runs = sandbox.runs()
    missing = sorted(rid for rid, evs in runs.items() if not any(e.node == step for e in evs))
    return ProbeResult(
        probe_id=probe_id,
        samples=len(runs),
        violations=len(missing),
        violation_rate=round(len(missing) / len(runs), 4) if runs else 0.0,
        matched_run_ids=sorted(runs.keys()),
        detail={"step": step, "missing_runs": missing},
    )


# -- rate probe ----------------------------------------------------------------
def _probe_autonomy(sandbox: Sandbox, policy: BaselinePolicy, spec: dict, probe_id: str) -> ProbeResult:
    events = [e for evs in sandbox.runs().values() for e in evs]
    events.sort(key=lambda e: (e.run_id, e.seq))
    routes, auto = select_autonomy_decisions(policy, events)
    budget = policy.max_auto_fraction if policy.max_auto_fraction is not None else 1.0
    n_windows = max(2, int(spec.get("windows", 3)))
    if not routes:
        return ProbeResult(probe_id=probe_id, samples=0, violations=0, violation_rate=0.0,
                           detail={"error": "no routing decisions in replay"})
    auto_ids = {e.event_id for e in auto}
    size = max(1, len(routes) // n_windows)
    windows: list[dict[str, Any]] = []
    exceeded = 0
    for w in range(n_windows):
        chunk = routes[w * size :] if w == n_windows - 1 else routes[w * size : (w + 1) * size]
        if not chunk:
            continue
        frac = round(sum(1 for e in chunk if e.event_id in auto_ids) / len(chunk), 4)
        over = frac > budget
        exceeded += int(over)
        windows.append({"window": w + 1, "decisions": len(chunk), "auto_fraction": frac, "exceeds_budget": over})
    return ProbeResult(
        probe_id=probe_id,
        samples=len(windows),
        violations=exceeded,
        violation_rate=round(exceeded / len(windows), 4) if windows else 0.0,
        matched_run_ids=sorted({e.run_id for e in routes}),
        detail={"budget": budget, "windows": windows, "overall_fraction": round(len(auto) / len(routes), 4)},
    )
