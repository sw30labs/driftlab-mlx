"""Test the drift hypothesis + micro-experiment loop.

The loop must CONFIRM each seeded drift on the drifted trace and REFUTE a
previously-confirmed hypothesis when re-run against the clean trace.
"""

from pathlib import Path

from driftlab.baseline import BaselineCompiler, load_profile
from driftlab.ingest import load_jsonl
from driftlab.diff import BehavioralDiff
from driftlab.anomaly import AnomalyEngine
from driftlab.experiment.hypothesis import generate
from driftlab.experiment.loop import run_experiment, Verdict
from driftlab.sensor import load_resource_jsonl

SEED = Path(__file__).resolve().parent.parent / "src" / "driftlab" / "seed"


def _anomalies(agent: str):
    profile = load_profile(SEED / "baselines" / f"{agent}-baseline.json")
    policy = BaselineCompiler().compile(profile)
    events = load_jsonl(SEED / "traces" / f"{agent}-trace.jsonl", agent)
    records = load_resource_jsonl(SEED / "resource" / f"{agent}-resource.jsonl")
    diff = BehavioralDiff(policy, events, resource_records=records)
    findings = diff.run()
    anoms = AnomalyEngine().build(findings, diff=diff)
    return policy, events, records, anoms


def test_experiment_confirms_drifts():
    policy, events, records, anoms = _anomalies("loan-officer")
    outcomes = [run_experiment(generate(a, policy), events, resource_records=records)
                for a in anoms if not a.waived]
    verdicts = {o.anomaly_id: o.verdict for o in outcomes}
    # Every seeded drift family should be CONFIRMED with probe evidence.
    confirmed = [o for o in outcomes if o.verdict == Verdict.CONFIRMED]
    assert len(confirmed) >= 5, f"expected >=5 confirmed, got {[(o.anomaly_id, o.verdict.value) for o in outcomes]}"
    # No drift is left INCONCLUSIVE/CONFIRMED-false for the drifted agent.
    assert all(o.verdict == Verdict.CONFIRMED for o in outcomes)


def test_experiment_loop_emits_own_telemetry():
    # Dogfood (ADR-001): the proof engine records its own resource telemetry
    # under the isolated data dir — observe-only, never in the artifacts.
    from driftlab.config import get_settings
    from driftlab.sensor import load_resource_jsonl

    policy, events, records, anoms = _anomalies("loan-officer")
    anomaly = next(a for a in anoms if not a.waived)
    run_experiment(generate(anomaly, policy), events, resource_records=records)
    stream = get_settings().data_dir / "resource" / "driftlab-experiment.jsonl"
    assert stream.exists()
    recs = load_resource_jsonl(stream)
    assert recs[-1].spent["iterations"] >= 1.0
    assert recs[-1].payload["control"] == anomaly.control
    assert recs[-1].payload["anomaly"] == anomaly.id


def test_experiment_refutes_on_clean_trace():
    # Re-run the loan-officer hypotheses against the CLEAN support trace +
    # support's clean resource stream (never crosses loan's token ceiling).
    loan_policy, _, _, loan_anoms = _anomalies("loan-officer")
    _, clean_events, clean_records, _ = _anomalies("support-triage")
    outcomes = [run_experiment(generate(a, loan_policy), clean_events,
                               resource_records=clean_records) for a in loan_anoms]
    # On a clean trace none of the loan drifts should be confirmed.
    assert all(o.verdict != Verdict.CONFIRMED for o in outcomes)