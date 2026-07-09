import json

from driftlab.baseline.oscal_loader import catalog_control_index, load_oscal_json
from driftlab.config import Settings
from driftlab.cycle import CycleService
from driftlab.emit.oscal_evidence import build_assessment_plan, build_assessment_results


def _cycle(tmp_path, settings, trace="loan-officer-drifted.jsonl"):
    seed = settings.registry_path.parent
    service = CycleService(Settings(data_dir=tmp_path / "ws", llm_provider="none"))
    return (
        service.run_cycle(
            agent_id="loan-officer",
            baseline_path=seed / "baselines" / "loan-officer-profile.json",
            traces_path=seed / "traces" / trace,
        ),
        service,
    )


def test_assessment_plan_shape(loan_policy):
    doc = build_assessment_plan(loan_policy, timestamp="2026-07-09T00:00:00Z")
    plan = doc["assessment-plan"]
    assert plan["metadata"]["oscal-version"] == "1.1.2"
    task_controls = {p["value"] for t in plan["tasks"] for p in t["props"] if p["name"] == "dl:control"}
    assert task_controls == {"dl-1", "dl-2", "dl-3", "dl-4", "dl-5", "dl-6", "dl-7"}
    selections = plan["reviewed-controls"]["control-selections"][0]["include-controls"]
    assert {s["control-id"] for s in selections} == task_controls
    # deterministic uuid: same baseline -> same plan uuid
    again = build_assessment_plan(loan_policy, timestamp="2027-01-01T00:00:00Z")
    assert again["assessment-plan"]["uuid"] == plan["uuid"]


def test_assessment_results_findings_states(tmp_path, settings, loan_policy):
    cycle, _service = _cycle(tmp_path, settings)
    doc = build_assessment_results(cycle, loan_policy)
    result = doc["assessment-results"]["results"][0]
    states = {
        f["target"]["target-id"]: f["target"]["status"]["state"] for f in result["findings"]
    }
    assert states == {
        "dl-1_smt": "not-satisfied",
        "dl-2_smt": "satisfied",
        "dl-3_smt": "not-satisfied",
        "dl-4_smt": "not-satisfied",
        "dl-5_smt": "satisfied",
        "dl-6_smt": "not-satisfied",
        "dl-7_smt": "satisfied",
    }
    # observations: one per anomaly + one per experiment
    assert len(result["observations"]) == len(cycle.anomalies) + len(cycle.experiments)
    # not-satisfied findings link to their observations
    dl3 = next(f for f in result["findings"] if f["target"]["target-id"] == "dl-3_smt")
    assert len(dl3["related-observations"]) == 2  # anomaly + its experiment
    # deterministic evidence uuids
    doc2 = build_assessment_results(cycle, loan_policy)
    assert doc2["assessment-results"]["uuid"] == doc["assessment-results"]["uuid"]


def test_clean_cycle_attests_all_satisfied(tmp_path, settings, loan_policy):
    cycle, _ = _cycle(tmp_path, settings, trace="loan-officer-clean.jsonl")
    doc = build_assessment_results(cycle, loan_policy)
    result = doc["assessment-results"]["results"][0]
    assert all(f["target"]["status"]["state"] == "satisfied" for f in result["findings"])
    assert result["observations"] == []  # nothing to observe, everything to attest


def test_artifacts_written_and_json_valid(tmp_path, settings):
    cycle, service = _cycle(tmp_path, settings)
    base = service.settings.artifacts_dir / "loan-officer" / cycle.cycle_id
    for name in ("ledger.json", "assessment-plan.json", "assessment-results.json"):
        json.loads((base / name).read_text(encoding="utf-8"))
    assert (base / "report.md").read_text(encoding="utf-8").startswith("# DriftLab cycle report")


def test_catalog_control_index(settings):
    seed = settings.registry_path.parent
    catalog = load_oscal_json(seed / "baselines" / "driftlab-catalog.json")
    index = catalog_control_index(catalog)
    assert set(index) == {"dl-1", "dl-2", "dl-3", "dl-4", "dl-5", "dl-6", "dl-7"}
    assert "CA-7" in index["dl-6"]["sp800_53"]
    assert index["dl-3"]["prose"].startswith("When a certified trigger")
