"""Turn anomalies into testable drift hypotheses.

A hypothesis is a falsifiable claim plus a concrete probe spec the experiment
loop can execute against a sandboxed replay. Generation is deterministic and
template-based; an LLM may later *rephrase* the statement for humans, but the
claim and the probe are fixed by the anomaly.
"""

from __future__ import annotations

from driftlab.domain.models import AnomalyRecord, DriftHypothesis, DriftKind, Severity

#: kinds that can be probed by replay; EVIDENCE_QUALITY cannot be experimented on.
PROBEABLE_KINDS = {
    DriftKind.MISSING_HITL,
    DriftKind.UNEXPECTED_TOOL_CALL,
    DriftKind.UNAUTHORIZED_ROUTE,
    DriftKind.AUTONOMY_BUDGET_EXCEEDED,
    DriftKind.FALLBACK_VIOLATION,
    DriftKind.MISSING_STEP,
}


def hypothesis_for_anomaly(anomaly: AnomalyRecord) -> DriftHypothesis | None:
    """Build the deterministic hypothesis + probe spec for one anomaly."""
    if anomaly.kind not in PROBEABLE_KINDS:
        return None
    m = anomaly.measurement
    kind = anomaly.kind

    if kind is DriftKind.MISSING_HITL:
        statement = (
            f"The agent systematically bypasses the '{m.get('trigger_id')}' human-review gate: "
            f"decisions matching [{m.get('conditions')}] are committed without routing to "
            f"'{m.get('required_route')}'."
        )
        expected = f"Under the certified baseline, 100% of matching decisions route to '{m.get('required_route')}'."
        probe = {
            "probe_kind": "hitl_replay",
            "trigger_id": m.get("trigger_id"),
            "scope": 1,
        }
    elif kind is DriftKind.UNEXPECTED_TOOL_CALL:
        node = anomaly.impacted_nodes[0] if anomaly.impacted_nodes else "?"
        statement = (
            f"The agent has acquired an uncertified capability: tool '{m.get('tool')}' is being "
            f"invoked at node '{node}' outside the certified decision-rights allowlist."
        )
        expected = f"Under the certified baseline, '{m.get('tool')}' is never invoked at '{node}'."
        probe = {"probe_kind": "tool_replay", "node": node, "tool": m.get("tool"), "scope": 1}
    elif kind is DriftKind.UNAUTHORIZED_ROUTE:
        route = anomaly.impacted_routes[0] if anomaly.impacted_routes else "?->?"
        statement = f"The agent routes decisions along an uncertified path ({route})."
        expected = f"Under the certified baseline, the transition {route} never occurs."
        probe = {"probe_kind": "route_replay", "route": route, "scope": 1}
    elif kind is DriftKind.AUTONOMY_BUDGET_EXCEEDED:
        statement = (
            f"The agent's full-autonomy rate has drifted to {m.get('observed_fraction', 0):.0%}, "
            f"sustained above the certified budget of {m.get('allowed_fraction', 0):.0%} "
            f"(not a one-off burst)."
        )
        expected = (
            f"Under the certified baseline, at most {m.get('allowed_fraction', 0):.0%} of routing "
            "decisions take the full-autonomy path in any observation window."
        )
        probe = {"probe_kind": "autonomy_windows", "windows": 3, "scope": 1}
    elif kind is DriftKind.FALLBACK_VIOLATION:
        statement = (
            f"After errors, the agent continues normal flow instead of taking the certified "
            f"fallback '{m.get('required_fallback')}'."
        )
        expected = f"Under the certified baseline, every error is followed by '{m.get('required_fallback')}'."
        probe = {"probe_kind": "fallback_replay", "required_fallback": m.get("required_fallback"), "scope": 1}
    else:  # MISSING_STEP
        step = anomaly.impacted_nodes[0] if anomaly.impacted_nodes else "?"
        statement = f"The agent skips the certified required step '{step}' in some runs."
        expected = f"Under the certified baseline, every run executes '{step}'."
        probe = {"probe_kind": "step_replay", "step": step, "scope": 1}

    return DriftHypothesis(
        anomaly_fingerprint=anomaly.fingerprint,
        control_id=anomaly.control_id,
        kind=kind,
        statement=statement,
        probe_spec=probe,
        expected_under_baseline=expected,
    )


def generate_hypotheses(
    anomalies: list[AnomalyRecord],
    *,
    max_experiments: int = 5,
    min_severity: Severity = Severity.MEDIUM,
) -> list[DriftHypothesis]:
    """Hypotheses for the worst unwaived anomalies, severity-first (deterministic)."""
    from driftlab.domain.models import SEVERITY_WEIGHTS

    ranked = sorted(
        (a for a in anomalies if a.waiver_status == "none"),
        key=lambda a: (-SEVERITY_WEIGHTS[a.severity.value], a.fingerprint),
    )
    floor = SEVERITY_WEIGHTS[min_severity.value]
    out: list[DriftHypothesis] = []
    for anomaly in ranked:
        if SEVERITY_WEIGHTS[anomaly.severity.value] < floor:
            continue
        hyp = hypothesis_for_anomaly(anomaly)
        if hyp is not None:
            out.append(hyp)
        if len(out) >= max_experiments:
            break
    return out
