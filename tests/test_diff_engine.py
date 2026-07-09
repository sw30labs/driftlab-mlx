from driftlab.baseline.model import BaselinePolicy, Condition, FallbackRule, HitlTrigger
from driftlab.diff.engine import BehavioralDiffEngine
from driftlab.domain.models import DecisionEvent, DriftKind, EventType


def _ev(run="r1", seq=0, et=EventType.NODE_ENTER, node="n", **kw):
    return DecisionEvent(agent_id="a", run_id=run, seq=seq, event_type=et, node=node, **kw)


def _policy(**kw):
    defaults = dict(baseline_id="b", agent_id="a")
    defaults.update(kw)
    return BaselinePolicy(**defaults)


ENGINE = BehavioralDiffEngine()


def test_empty_trace_is_evidence_quality_not_crash():
    devs = ENGINE.compare(policy=_policy(), events=[])
    assert [d.kind for d in devs] == [DriftKind.EVIDENCE_QUALITY]


def test_tool_allowlist_violation_and_wildcard():
    policy = _policy(allowed_tools={"n": ["ok_tool"], "*": ["global_tool"]})
    events = [
        _ev(seq=0, et=EventType.TOOL_CALL, tool="ok_tool"),
        _ev(seq=1, et=EventType.TOOL_CALL, tool="global_tool"),
        _ev(seq=2, et=EventType.TOOL_CALL, tool="rogue"),
        _ev(seq=3, et=EventType.TOOL_CALL, tool="rogue"),
    ]
    devs = ENGINE.compare(policy=policy, events=events)
    assert len(devs) == 1
    d = devs[0]
    assert d.kind is DriftKind.UNEXPECTED_TOOL_CALL
    assert d.fingerprint == "observed_vs_baseline:unexpected_tool_call:n:rogue"
    assert d.measurement["call_count"] == 2
    assert len(d.evidence.event_ids) == 2


def test_route_rules_only_constrain_certified_from_nodes():
    policy = _policy(allowed_routes={"a": ["b"]})
    events = [
        _ev(seq=0, et=EventType.ROUTE, node="a", target="b"),   # certified
        _ev(seq=1, et=EventType.ROUTE, node="a", target="z"),   # violation
        _ev(seq=2, et=EventType.ROUTE, node="q", target="zz"),  # uncertified from-node: ignored
    ]
    devs = ENGINE.compare(policy=policy, events=events)
    assert [d.kind for d in devs] == [DriftKind.UNAUTHORIZED_ROUTE]
    assert devs[0].impacted_routes == ["a->z"]


def _hitl_policy():
    return _policy(
        hitl_triggers=[
            HitlTrigger(
                trigger_id="big",
                at_node="assess",
                when=[Condition.parse("amount>100")],
                require_route_to="review",
            )
        ]
    )


def test_hitl_bypass_detected_and_compliance_respected():
    policy = _hitl_policy()
    events = [
        # r1: matches, escalates -> compliant
        _ev(run="r1", seq=0, node="assess", decision_context={"amount": 500}),
        _ev(run="r1", seq=1, et=EventType.ROUTE, node="assess", target="review"),
        # r2: matches, never escalates -> violation
        _ev(run="r2", seq=0, node="assess", decision_context={"amount": 200}),
        _ev(run="r2", seq=1, et=EventType.ROUTE, node="assess", target="auto"),
        # r3: does not match -> not in population
        _ev(run="r3", seq=0, node="assess", decision_context={"amount": 50}),
    ]
    devs = ENGINE.compare(policy=policy, events=events)
    assert len(devs) == 1
    m = devs[0].measurement
    assert (m["matched_runs"], m["violating_runs"], m["violation_rate"]) == (2, 1, 0.5)


def test_hitl_all_compliant_yields_nothing():
    policy = _hitl_policy()
    events = [
        _ev(run="r1", seq=0, node="assess", decision_context={"amount": 500}),
        _ev(run="r1", seq=1, et=EventType.HITL, node="review"),
    ]
    assert ENGINE.compare(policy=policy, events=events) == []


def test_autonomy_budget_exceed_and_within():
    policy = _policy(
        max_auto_fraction=0.5,
        autonomy_auto_targets=["auto"],
        allowed_routes={"gate": ["auto", "manual"]},
    )
    over = [
        _ev(run=f"r{i}", seq=0, et=EventType.ROUTE, node="gate", target="auto" if i < 3 else "manual")
        for i in range(4)
    ]
    devs = ENGINE.compare(policy=policy, events=over)
    kinds = [d.kind for d in devs]
    assert DriftKind.AUTONOMY_BUDGET_EXCEEDED in kinds
    m = next(d for d in devs if d.kind is DriftKind.AUTONOMY_BUDGET_EXCEEDED).measurement
    assert m["observed_fraction"] == 0.75 and m["overshoot"] == 0.25

    within = [
        _ev(run=f"r{i}", seq=0, et=EventType.ROUTE, node="gate", target="auto" if i < 2 else "manual")
        for i in range(4)
    ]
    assert all(
        d.kind is not DriftKind.AUTONOMY_BUDGET_EXCEEDED
        for d in ENGINE.compare(policy=policy, events=within)
    )


def test_autonomy_decision_nodes_exclude_hitl_gate_exits():
    """Regression (soc-ir integration): a HITL gate routing to the auto target
    must not be counted as an autonomous decision when the baseline pins the
    decision population via dl:decision-node."""
    policy = _policy(
        max_auto_fraction=0.7,
        autonomy_auto_targets=["respond"],
        autonomy_decision_nodes=["select"],
        allowed_routes={"select": ["gate", "respond"], "gate": ["respond", "gate"]},
    )
    events = []
    # 10 decisions at select: 7 auto (70%, exactly at budget), 3 gated
    for i in range(10):
        target = "respond" if i < 7 else "gate"
        events.append(_ev(run=f"r{i}", seq=0, et=EventType.ROUTE, node="select", target=target))
    # the 3 gated runs exit the gate to respond — human-answered, NOT autonomy
    for i in range(7, 10):
        events.append(_ev(run=f"r{i}", seq=1, et=EventType.ROUTE, node="gate", target="respond"))
    devs = ENGINE.compare(policy=policy, events=events)
    assert all(d.kind is not DriftKind.AUTONOMY_BUDGET_EXCEEDED for d in devs)
    # without the explicit decision population, the old inference overcounts
    legacy = policy.model_copy(update={"autonomy_decision_nodes": []})
    devs2 = ENGINE.compare(policy=legacy, events=events)
    assert any(d.kind is DriftKind.AUTONOMY_BUDGET_EXCEEDED for d in devs2)


def test_autonomy_falls_back_to_event_annotations():
    policy = _policy(max_auto_fraction=0.4)
    events = [
        _ev(run="r1", seq=0, et=EventType.ROUTE, node="g", target="x", autonomy="auto"),
        _ev(run="r2", seq=0, et=EventType.ROUTE, node="g", target="y", autonomy="human"),
    ]
    devs = ENGINE.compare(policy=policy, events=events)
    assert [d.kind for d in devs] == [DriftKind.AUTONOMY_BUDGET_EXCEEDED]
    assert devs[0].measurement["observed_fraction"] == 0.5


def test_fallback_violation_and_compliance():
    policy = _policy(fallback_rules=[FallbackRule(on_error_at="*", require_next_node="rescue")])
    events = [
        # r1: error then rescue -> compliant
        _ev(run="r1", seq=0, et=EventType.ERROR, node="work"),
        _ev(run="r1", seq=1, node="rescue"),
        # r2: error then business-as-usual -> violation
        _ev(run="r2", seq=0, et=EventType.ERROR, node="work"),
        _ev(run="r2", seq=1, node="next_step"),
        # r3: error as final event -> violation (no fallback happened)
        _ev(run="r3", seq=0, et=EventType.ERROR, node="work"),
    ]
    devs = ENGINE.compare(policy=policy, events=events)
    assert len(devs) == 1
    assert devs[0].measurement["error_count"] == 2


def test_missing_step():
    policy = _policy(required_steps=["audit"])
    events = [
        _ev(run="r1", seq=0, node="audit"),
        _ev(run="r2", seq=0, node="other"),
    ]
    devs = ENGINE.compare(policy=policy, events=events)
    assert [d.kind for d in devs] == [DriftKind.MISSING_STEP]
    assert devs[0].evidence.run_ids == ["r2"]


def test_diff_is_deterministic(loan_policy, drifted_events):
    a = ENGINE.compare(policy=loan_policy, events=drifted_events)
    b = ENGINE.compare(policy=loan_policy, events=list(drifted_events))
    assert [d.fingerprint for d in a] == [d.fingerprint for d in b]
    assert [d.model_dump(mode="json") for d in a] == [d.model_dump(mode="json") for d in b]
