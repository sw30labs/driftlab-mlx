from datetime import datetime, timedelta
from driftlab.clock import naive_utcnow

from driftlab.anomaly.engine import AnomalyEngine
from driftlab.baseline.model import BaselinePolicy
from driftlab.diff.behavior_graph import BehaviorGraph
from driftlab.diff.engine import BehavioralDiffEngine
from driftlab.domain.models import (
    ComparisonType,
    DecisionEvent,
    DeviationRecord,
    DriftKind,
    EventType,
    Severity,
    WaiverDefinition,
)

ENGINE = AnomalyEngine()


def _graph(edges):
    events = []
    for i, (a, b) in enumerate(edges):
        events.append(
            DecisionEvent(agent_id="x", run_id="r1", seq=i, event_type=EventType.ROUTE, node=a, target=b)
        )
    return BehaviorGraph(events)


def _dev(kind, fingerprint="fp", nodes=(), measurement=None, control="dl-1"):
    return DeviationRecord(
        comparison_type=ComparisonType.OBSERVED_VS_BASELINE,
        kind=kind,
        fingerprint=fingerprint,
        control_id=control,
        title="t",
        description="d",
        impacted_nodes=list(nodes),
        measurement=measurement or {},
    )


def _policy(**kw):
    return BaselinePolicy(baseline_id="b", agent_id="x", **kw)


def test_hitl_bypass_reaching_sink_is_critical():
    graph = _graph([("assess", "auto"), ("auto", "disburse")])
    policy = _policy(critical_sinks=["disburse"])
    dev = _dev(DriftKind.MISSING_HITL, nodes=["assess", "review"])
    [anomaly] = ENGINE.build_anomalies(policy=policy, deviations=[dev], graph=graph)
    assert anomaly.severity is Severity.CRITICAL
    assert any(p.reaches_critical_sink for p in anomaly.impacted_paths)


def test_hitl_bypass_off_sink_path_is_high():
    graph = _graph([("assess", "auto")])
    policy = _policy(critical_sinks=["disburse"])  # unreachable
    dev = _dev(DriftKind.MISSING_HITL, nodes=["assess"])
    [anomaly] = ENGINE.build_anomalies(policy=policy, deviations=[dev], graph=graph)
    assert anomaly.severity is Severity.HIGH


def test_tool_severity_gradation():
    graph = _graph([("assess", "disburse")])
    policy = _policy(critical_sinks=["disburse"])
    on_sink = _dev(DriftKind.UNEXPECTED_TOOL_CALL, nodes=["disburse"], measurement={"tool": "x"})
    reaches = _dev(DriftKind.UNEXPECTED_TOOL_CALL, fingerprint="fp2", nodes=["assess"], measurement={"tool": "x"})
    isolated = _dev(DriftKind.UNEXPECTED_TOOL_CALL, fingerprint="fp3", nodes=["island"], measurement={"tool": "x"})
    result = ENGINE.build_anomalies(policy=policy, deviations=[on_sink, reaches, isolated], graph=graph)
    by_fp = {a.fingerprint: a.severity for a in result}
    assert by_fp["fp"] is Severity.CRITICAL
    assert by_fp["fp2"] is Severity.HIGH
    assert by_fp["fp3"] is Severity.MEDIUM


def test_autonomy_overshoot_thresholds():
    graph = _graph([])
    policy = _policy()
    big = _dev(DriftKind.AUTONOMY_BUDGET_EXCEEDED, measurement={"overshoot": 0.25})
    small = _dev(DriftKind.AUTONOMY_BUDGET_EXCEEDED, fingerprint="fp2", measurement={"overshoot": 0.05})
    result = ENGINE.build_anomalies(policy=policy, deviations=[big, small], graph=graph)
    by_fp = {a.fingerprint: a.severity for a in result}
    assert by_fp["fp"] is Severity.HIGH and by_fp["fp2"] is Severity.MEDIUM


def test_waiver_caps_severity_and_marks_status():
    graph = _graph([("assess", "disburse")])
    waiver = WaiverDefinition(
        waiver_id="w1", title="accepted", applies_to=["fp"], severity_cap=Severity.LOW, rationale="r"
    )
    policy = _policy(critical_sinks=["disburse"], waivers=[waiver])
    dev = _dev(DriftKind.MISSING_HITL, nodes=["assess"])
    [anomaly] = ENGINE.build_anomalies(policy=policy, deviations=[dev], graph=graph)
    assert anomaly.severity is Severity.LOW
    assert anomaly.waiver_status == "waived"
    assert "(waived: accepted)" in anomaly.description


def test_expired_waiver_does_not_apply():
    graph = _graph([("assess", "disburse")])
    waiver = WaiverDefinition(
        waiver_id="w1", title="old", applies_to=["fp"], severity_cap=Severity.LOW,
        rationale="r", effective_to=naive_utcnow() - timedelta(days=1),
    )
    policy = _policy(critical_sinks=["disburse"], waivers=[waiver])
    dev = _dev(DriftKind.MISSING_HITL, nodes=["assess"])
    [anomaly] = ENGINE.build_anomalies(policy=policy, deviations=[dev], graph=graph)
    assert anomaly.severity is Severity.CRITICAL and anomaly.waiver_status == "none"


def test_score_formula_is_glass_graph_weights():
    # 1 critical + 2 high + 1 medium + 1 low = 35 + 40 + 8 + 3 = 86 -> 14.0
    graph = _graph([])
    policy = _policy()
    devs = [
        _dev(DriftKind.MISSING_HITL, fingerprint="f1", nodes=[]),                       # HIGH (no sink)
        _dev(DriftKind.UNAUTHORIZED_ROUTE, fingerprint="f2", nodes=[]),                 # HIGH
        _dev(DriftKind.AUTONOMY_BUDGET_EXCEEDED, fingerprint="f3", measurement={"overshoot": 0.01}),  # MEDIUM
        _dev(DriftKind.EVIDENCE_QUALITY, fingerprint="f4"),                             # LOW
    ]
    anomalies = ENGINE.build_anomalies(policy=policy, deviations=devs, graph=graph)
    score, counts = AnomalyEngine.score(anomalies)
    assert counts == {"high": 2, "low": 1, "medium": 1}
    assert score == 100.0 - (20 + 20 + 8 + 3)


def test_score_floors_at_zero(loan_policy, drifted_events):
    devs = BehavioralDiffEngine().compare(policy=loan_policy, events=drifted_events)
    anomalies = ENGINE.build_anomalies(
        policy=loan_policy, deviations=devs * 5, graph=BehaviorGraph(drifted_events)
    )
    score, _ = AnomalyEngine.score(anomalies)
    assert score == 0.0
