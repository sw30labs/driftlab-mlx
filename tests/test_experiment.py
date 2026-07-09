"""Micro-experiment loop: confirm on drifted evidence, refute on clean,
inconclusive on thin evidence, bounded iterations, batch isolation."""

from driftlab.anomaly.engine import AnomalyEngine
from driftlab.baseline.model import BaselinePolicy, Condition, HitlTrigger
from driftlab.diff.behavior_graph import BehaviorGraph
from driftlab.diff.engine import BehavioralDiffEngine
from driftlab.domain.models import DecisionEvent, DriftHypothesis, DriftKind, EventType, Verdict
from driftlab.experiment.loop import run_experiment, run_experiments
from driftlab.experiment.sandbox import ReplaySandbox
from driftlab.hypothesis.generator import generate_hypotheses, hypothesis_for_anomaly


def _pipeline(policy, events):
    devs = BehavioralDiffEngine().compare(policy=policy, events=events)
    anomalies = AnomalyEngine().build_anomalies(policy=policy, deviations=devs, graph=BehaviorGraph(events))
    return anomalies


def test_all_seed_drifts_are_confirmed(loan_policy, drifted_events):
    anomalies = _pipeline(loan_policy, drifted_events)
    hypotheses = generate_hypotheses(anomalies)
    assert len(hypotheses) == 4
    records = run_experiments(hypotheses, sandbox=ReplaySandbox(drifted_events), policy=loan_policy)
    assert {r.verdict for r in records} == {Verdict.CONFIRMED}
    kinds = {r.hypothesis.kind for r in records}
    assert kinds == {
        DriftKind.MISSING_HITL,
        DriftKind.AUTONOMY_BUDGET_EXCEEDED,
        DriftKind.FALLBACK_VIOLATION,
        DriftKind.UNEXPECTED_TOOL_CALL,
    }
    # every confirmation carries reproduced probe evidence
    for record in records:
        assert record.probes and record.probes[-1].violations > 0


def test_hitl_hypothesis_refuted_against_clean_trace(loan_policy, drifted_events, clean_events):
    anomalies = _pipeline(loan_policy, drifted_events)
    hitl = next(a for a in anomalies if a.kind is DriftKind.MISSING_HITL)
    hypothesis = hypothesis_for_anomaly(hitl)
    record = run_experiment(hypothesis, sandbox=ReplaySandbox(clean_events), policy=loan_policy)
    assert record.verdict is Verdict.REFUTED
    assert record.validity_score == 0.0
    assert record.probes[-1].samples >= 3  # refutation requires evidence, not absence of data


def test_thin_evidence_is_inconclusive_not_confirmed(loan_policy):
    """One matching run with zero violations cannot refute (min samples)."""
    trigger = loan_policy.hitl_triggers[1]
    assert trigger.trigger_id == "high-value"
    events = [
        DecisionEvent(agent_id="loan-officer", run_id="r1", seq=0, event_type=EventType.NODE_ENTER,
                      node="assess", decision_context={"amount": 99000}),
        DecisionEvent(agent_id="loan-officer", run_id="r1", seq=1, event_type=EventType.ROUTE,
                      node="assess", target="hitl_review"),
    ]
    hypothesis = DriftHypothesis(
        anomaly_fingerprint="observed_vs_baseline:missing_hitl:high-value:assess",
        control_id="dl-3",
        kind=DriftKind.MISSING_HITL,
        statement="s",
        probe_spec={"probe_kind": "hitl_replay", "trigger_id": "high-value", "scope": 1},
    )
    record = run_experiment(
        hypothesis, sandbox=ReplaySandbox(events), policy=loan_policy, max_iterations=2
    )
    assert record.verdict is Verdict.INCONCLUSIVE
    assert record.iterations == 2  # bounded, then honest


def test_iteration_bound_is_respected(loan_policy, clean_events):
    hypothesis = DriftHypothesis(
        anomaly_fingerprint="fp",
        kind=DriftKind.AUTONOMY_BUDGET_EXCEEDED,
        statement="s",
        probe_spec={"probe_kind": "autonomy_windows", "windows": 3, "scope": 1},
    )
    # clean trace: some windows exceed, some don't -> stays between thresholds
    record = run_experiment(hypothesis, sandbox=ReplaySandbox(clean_events), policy=loan_policy, max_iterations=3)
    assert record.iterations <= 3
    if record.verdict is Verdict.INCONCLUSIVE:
        assert len(record.probes) == 3  # one probe per iteration


def test_batch_isolation_bad_probe_never_raises(loan_policy, drifted_events):
    bogus = DriftHypothesis(
        anomaly_fingerprint="fp-x",
        kind=DriftKind.MISSING_HITL,
        statement="s",
        probe_spec={"probe_kind": "not_a_probe", "scope": 1},
    )
    records = run_experiments([bogus], sandbox=ReplaySandbox(drifted_events), policy=loan_policy)
    assert records[0].verdict is Verdict.INCONCLUSIVE
    assert any("failed" in note for note in records[0].notes)


def test_hypothesis_generation_ranks_and_caps(loan_policy, drifted_events):
    anomalies = _pipeline(loan_policy, drifted_events)
    top1 = generate_hypotheses(anomalies, max_experiments=1)
    assert len(top1) == 1
    assert top1[0].kind is DriftKind.MISSING_HITL  # critical outranks high
    # deterministic ids
    again = generate_hypotheses(anomalies, max_experiments=1)
    assert top1[0].hypothesis_id == again[0].hypothesis_id


def test_experiment_verdict_is_evidence_based_not_llm(loan_policy, drifted_events):
    """The loop must produce identical verdicts with no LLM anywhere."""
    anomalies = _pipeline(loan_policy, drifted_events)
    hypotheses = generate_hypotheses(anomalies)
    r1 = run_experiments(hypotheses, sandbox=ReplaySandbox(drifted_events), policy=loan_policy)
    r2 = run_experiments(hypotheses, sandbox=ReplaySandbox(drifted_events), policy=loan_policy)
    assert [(r.verdict, r.validity_score, r.iterations) for r in r1] == [
        (r.verdict, r.validity_score, r.iterations) for r in r2
    ]
