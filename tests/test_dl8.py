"""DL-8 resource-budget audit (ADR-001 phase 2): diff check over replayed
resource streams, fail-closed telemetry-missing finding, cycle identity with
the resource plane, fidelity confound annotation, and resource experiments."""

import json
from pathlib import Path

from driftlab.anomaly import AnomalyEngine
from driftlab.baseline import BaselineCompiler, load_profile
from driftlab.cycle import run_cycle
from driftlab.diff import BehavioralDiff
from driftlab.experiment.hypothesis import ClaimKind, generate
from driftlab.experiment.loop import run_experiment
from driftlab.identity import cycle_id
from driftlab.ingest import load_jsonl
from driftlab.sensor import cumulative_spend, load_resource_jsonl

SEED = Path(__file__).resolve().parent.parent / "src" / "driftlab" / "seed"


def _policy(agent: str):
    return BaselineCompiler().compile(
        load_profile(SEED / "baselines" / f"{agent}-baseline.json"))


def _events(agent: str):
    return load_jsonl(SEED / "traces" / f"{agent}-trace.jsonl", agent)


def _records(agent: str):
    return load_resource_jsonl(SEED / "resource" / f"{agent}-resource.jsonl")


# -- diff check -----------------------------------------------------------


def test_dl8_breach_finding_on_seed_stream():
    policy, records = _policy("loan-officer"), _records("loan-officer")
    findings = BehavioralDiff(policy, _events("loan-officer"),
                              resource_records=records).check_dl8_resource_budget()
    assert len(findings) == 1
    f = findings[0]
    assert f.title == "Resource budget exceeded"
    assert f.extra["currency"] == "tokens"
    assert f.extra["spent"] == 130450.0
    assert f.extra["ceiling"] == 120000.0
    assert f.extra["breaker_fired"] is True
    # Evidence: exactly the records with tokens over the ceiling.
    over = [r.id for r in records if r.spent.get("tokens", 0) > 120000]
    assert f.evidence == over and len(over) == 2
    # Breach resolves HIGH (hint wins over the MEDIUM DL-8 base).
    anomalies = AnomalyEngine().build(findings)
    assert anomalies[0].severity.value == "high"


def test_dl8_missing_telemetry_fails_closed():
    policy = _policy("support-triage")
    findings = BehavioralDiff(policy, _events("support-triage"),
                              resource_records=None).check_dl8_resource_budget()
    assert len(findings) == 1
    assert findings[0].title == "Resource telemetry missing"
    assert findings[0].extra["records"] == 0
    anomalies = AnomalyEngine().build(findings)
    assert anomalies[0].severity.value == "medium"


def test_dl8_clean_stream_no_findings():
    policy, records = _policy("support-triage"), _records("support-triage")
    findings = BehavioralDiff(policy, _events("support-triage"),
                              resource_records=records).check_dl8_resource_budget()
    assert findings == []


def test_dl8_skipped_when_nothing_certified():
    policy = _policy("support-triage")
    policy.resource_ceilings = {}
    findings = BehavioralDiff(policy, _events("support-triage"),
                              resource_records=None).check_dl8_resource_budget()
    assert findings == []


def test_cumulative_spend_uses_max():
    records = _records("loan-officer")
    spend = cumulative_spend(records)
    assert spend["tokens"] == 130450.0
    assert spend["iterations"] == 11.0


# -- cycle identity + ledger ------------------------------------------------


def test_legacy_cycle_id_unchanged_without_resource_stream():
    assert cycle_id("a", "bh", "th") == cycle_id("a", "bh", "th", "")


def test_cycle_with_stream_changes_id_and_stays_deterministic():
    events, records = _events("support-triage"), _records("support-triage")
    base = str(SEED / "baselines" / "support-triage-baseline.json")
    with_stream_1 = run_cycle("support-triage", base, events,
                              run_experiments=False, resource_records=records)
    with_stream_2 = run_cycle("support-triage", base, events,
                              run_experiments=False, resource_records=records)
    without = run_cycle("support-triage", base, events, run_experiments=False)
    assert with_stream_1.cycle_id == with_stream_2.cycle_id
    assert with_stream_1.cycle_id != without.cycle_id
    assert json.dumps(with_stream_1.to_ledger(), sort_keys=True) == \
        json.dumps(with_stream_2.to_ledger(), sort_keys=True)
    # Ledger carries the resource plane only when a stream was observed.
    ledger = with_stream_1.to_ledger()
    assert ledger["resource"]["records"] == 8
    assert ledger["resource"]["spent"]["tokens"] == 41200.0
    assert ledger["resource"]["breaker_fired"] is False
    assert with_stream_1.resource_hash
    assert "resource" not in without.to_ledger()
    assert "resource_hash" not in without.to_ledger()


def test_fidelity_confound_annotation():
    events, records = _events("loan-officer"), _records("loan-officer")
    degraded = [r.model_copy(update={"fidelity": "reduced"}) if r.seq == 5 else r
                for r in records]
    base = str(SEED / "baselines" / "loan-officer-baseline.json")
    result = run_cycle("loan-officer", base, events,
                       run_experiments=False, resource_records=degraded)
    assert result.anomalies
    for a in result.anomalies:
        assert a.extra["fidelity_observed"] == ["full", "reduced"]
    # Uniform full fidelity adds no annotation (legacy-identical extras).
    clean = run_cycle("loan-officer", base, events,
                      run_experiments=False, resource_records=records)
    assert all("fidelity_observed" not in a.extra for a in clean.anomalies)


# -- experiments ------------------------------------------------------------


def test_dl8_experiment_confirms_breach():
    events, records = _events("loan-officer"), _records("loan-officer")
    base = str(SEED / "baselines" / "loan-officer-baseline.json")
    result = run_cycle("loan-officer", base, events,
                       run_experiments=True, resource_records=records)
    dl8 = [e for e in result.experiments if e["control"] == "DL-8"]
    assert len(dl8) == 1
    assert dl8[0]["verdict"] == "confirmed"
    assert dl8[0]["probe"]["kind"] == "resource"
    assert dl8[0]["probe"]["violations"] == 2


def test_dl8_experiment_inconclusive_without_telemetry():
    policy = _policy("support-triage")
    findings = BehavioralDiff(policy, _events("support-triage"),
                              resource_records=None).check_dl8_resource_budget()
    anomaly = AnomalyEngine().build(findings)[0]
    hypo = generate(anomaly, policy)
    assert hypo.kind is ClaimKind.RESOURCE
    outcome = run_experiment(hypo, _events("support-triage"), resource_records=[])
    assert outcome.verdict.value == "inconclusive"
