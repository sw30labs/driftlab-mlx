"""Determinism: re-running a cycle on identical inputs yields a byte-identical
anomaly ledger and identical cycle id."""

from pathlib import Path

from driftlab.baseline import BaselineCompiler, load_profile
from driftlab.ingest import load_jsonl
from driftlab.diff import BehavioralDiff
from driftlab.anomaly import AnomalyEngine
from driftlab.cycle import run_cycle
from driftlab.identity import cycle_id

SEED = Path(__file__).resolve().parent.parent / "src" / "driftlab" / "seed"


def _ledger(agent: str) -> tuple[str, str]:
    from driftlab.sensor import load_resource_jsonl
    profile = load_profile(SEED / "baselines" / f"{agent}-baseline.json")
    policy = BaselineCompiler().compile(profile)
    events = load_jsonl(SEED / "traces" / f"{agent}-trace.jsonl", agent)
    records = load_resource_jsonl(SEED / "resource" / f"{agent}-resource.jsonl")
    result = run_cycle(agent, str(SEED / "baselines" / f"{agent}-baseline.json"), events,
                       run_experiments=False, resource_records=records)
    return result.cycle_id, __import__("json").dumps(result.to_ledger(), sort_keys=True)


def test_determinism_loan_officer():
    cid1, led1 = _ledger("loan-officer")
    cid2, led2 = _ledger("loan-officer")
    assert cid1 == cid2
    assert led1 == led2


def test_determinism_support_triage():
    cid1, led1 = _ledger("support-triage")
    cid2, led2 = _ledger("support-triage")
    assert cid1 == cid2
    assert led1 == led2


def test_cycle_id_stable_formula():
    profile = load_profile(SEED / "baselines" / "loan-officer-baseline.json")
    policy = BaselineCompiler().compile(profile)
    events = load_jsonl(SEED / "traces" / "loan-officer-trace.jsonl", "loan-officer")
    import json
    from driftlab.identity import stable_json_digest
    trace_hash = stable_json_digest([e.model_dump(mode="json") for e in events])
    assert cycle_id("loan-officer", policy.baseline_hash, trace_hash) == cycle_id(
        "loan-officer", policy.baseline_hash, trace_hash)