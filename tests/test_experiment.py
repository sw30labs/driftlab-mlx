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

SEED = Path(__file__).resolve().parent.parent / "src" / "driftlab" / "seed"


def _anomalies(agent: str):
    profile = load_profile(SEED / "baselines" / f"{agent}-baseline.json")
    policy = BaselineCompiler().compile(profile)
    events = load_jsonl(SEED / "traces" / f"{agent}-trace.jsonl", agent)
    diff = BehavioralDiff(policy, events)
    findings = diff.run()
    anoms = AnomalyEngine().build(findings, diff=diff)
    return policy, events, anoms


def test_experiment_confirms_drifts():
    policy, events, anoms = _anomalies("loan-officer")
    outcomes = [run_experiment(generate(a, policy), events) for a in anoms if not a.waived]
    verdicts = {o.anomaly_id: o.verdict for o in outcomes}
    # Every seeded drift family should be CONFIRMED with probe evidence.
    confirmed = [o for o in outcomes if o.verdict == Verdict.CONFIRMED]
    assert len(confirmed) >= 4, f"expected >=4 confirmed, got {[(o.anomaly_id, o.verdict.value) for o in outcomes]}"
    # No drift is left INCONCLUSIVE/CONFIRMED-false for the drifted agent.
    assert all(o.verdict == Verdict.CONFIRMED for o in outcomes)


def test_experiment_refutes_on_clean_trace():
    # Re-run the loan-officer hypotheses against the CLEAN support trace.
    loan_policy, _, loan_anoms = _anomalies("loan-officer")
    _, clean_events, _ = _anomalies("support-triage")
    outcomes = [run_experiment(generate(a, loan_policy), clean_events) for a in loan_anoms]
    # On a clean trace none of the loan drifts should be confirmed.
    assert all(o.verdict != Verdict.CONFIRMED for o in outcomes)