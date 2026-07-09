"""§7 E2E suite: known drift detected AND proven; clean traces produce zero
findings; byte-identical determinism; full run with no LLM reachable."""

from pathlib import Path

from driftlab.config import Settings
from driftlab.cycle import CycleService
from driftlab.domain.models import DriftKind, Severity, Verdict


def _service(tmp_path: Path, name: str) -> CycleService:
    return CycleService(Settings(data_dir=tmp_path / name, llm_provider="none"))


def _seed(settings_fixture) -> Path:
    return settings_fixture.registry_path.parent


def test_known_drift_is_detected_and_proven(tmp_path, settings):
    seed = _seed(settings)
    service = _service(tmp_path, "w1")
    cycle = service.run_cycle(
        agent_id="loan-officer",
        baseline_path=seed / "baselines" / "loan-officer-profile.json",
        traces_path=seed / "traces" / "loan-officer-drifted.jsonl",
    )
    assert cycle.compliance_score == 5.0
    assert cycle.severity_counts == {"critical": 1, "high": 3}
    kinds = {a.kind for a in cycle.anomalies}
    assert kinds == {
        DriftKind.MISSING_HITL,
        DriftKind.AUTONOMY_BUDGET_EXCEEDED,
        DriftKind.FALLBACK_VIOLATION,
        DriftKind.UNEXPECTED_TOOL_CALL,
    }
    hitl = next(a for a in cycle.anomalies if a.kind is DriftKind.MISSING_HITL)
    assert hitl.severity is Severity.CRITICAL
    assert hitl.measurement["violating_runs"] == 5 and hitl.measurement["matched_runs"] == 8
    # every anomaly traces to evidence (provenance is load-bearing)
    for anomaly in cycle.anomalies:
        assert anomaly.evidence.event_ids or anomaly.evidence.run_ids
    # ...and every suspected drift was experimentally proven, not assumed
    assert len(cycle.experiments) == 4
    assert all(e.verdict is Verdict.CONFIRMED for e in cycle.experiments)


def test_clean_trace_zero_false_positives(tmp_path, settings):
    seed = _seed(settings)
    service = _service(tmp_path, "w2")
    cycle = service.run_cycle(
        agent_id="loan-officer",
        baseline_path=seed / "baselines" / "loan-officer-profile.json",
        traces_path=seed / "traces" / "loan-officer-clean.jsonl",
    )
    assert cycle.compliance_score == 100.0
    assert cycle.anomalies == [] and cycle.experiments == []

    triage = service.run_cycle(
        agent_id="support-triage",
        baseline_path=seed / "baselines" / "support-triage-profile.json",
        traces_path=seed / "traces" / "support-triage-clean.jsonl",
    )
    assert triage.compliance_score == 100.0 and triage.anomalies == []


def test_ledger_is_byte_identical_across_reruns(tmp_path, settings):
    """Design principle #4: same inputs -> byte-identical anomaly ledger,
    across two fully independent service instances and workspaces."""
    seed = _seed(settings)
    ledgers: list[bytes] = []
    for name in ("run-a", "run-b"):
        service = _service(tmp_path, name)
        cycle = service.run_cycle(
            agent_id="loan-officer",
            baseline_path=seed / "baselines" / "loan-officer-profile.json",
            traces_path=seed / "traces" / "loan-officer-drifted.jsonl",
        )
        ledger_path = (
            Path(service.settings.artifacts_dir) / "loan-officer" / cycle.cycle_id / "ledger.json"
        )
        ledgers.append(ledger_path.read_bytes())
    assert ledgers[0] == ledgers[1]


def test_cycle_id_is_deterministic_and_idempotent(tmp_path, settings):
    seed = _seed(settings)
    service = _service(tmp_path, "w3")
    kwargs = dict(
        agent_id="loan-officer",
        baseline_path=seed / "baselines" / "loan-officer-profile.json",
        traces_path=seed / "traces" / "loan-officer-drifted.jsonl",
    )
    c1 = service.run_cycle(**kwargs)
    c2 = service.run_cycle(**kwargs)  # same inputs -> same cycle, upserted
    assert c1.cycle_id == c2.cycle_id
    from driftlab.store.db import AnomalyRow, CycleRow

    with service.database.session() as session:
        assert session.query(CycleRow).count() == 1
        assert session.query(AnomalyRow).filter(AnomalyRow.cycle_id == c1.cycle_id).count() == 4


def test_full_run_succeeds_with_no_llm_reachable(tmp_path, settings, monkeypatch):
    """§7 LLM-optional: point provider at OMLX with nothing listening —
    the compliance run must be unaffected and produce no narrative."""
    seed = _seed(settings)
    omlx_settings = Settings(
        data_dir=tmp_path / "w4",
        llm_provider="omlx",
        omlx_base_url="http://127.0.0.1:1",  # guaranteed dead port
    )
    from driftlab.llm import build_chat_model

    llm = build_chat_model(omlx_settings)  # discovery fails -> None
    assert llm is None
    service = CycleService(omlx_settings, llm=llm)
    cycle = service.run_cycle(
        agent_id="loan-officer",
        baseline_path=seed / "baselines" / "loan-officer-profile.json",
        traces_path=seed / "traces" / "loan-officer-drifted.jsonl",
    )
    assert cycle.compliance_score == 5.0
    report = (
        Path(service.settings.artifacts_dir) / "loan-officer" / cycle.cycle_id / "report.md"
    ).read_text(encoding="utf-8")
    assert "Narrative (LLM" not in report  # no narrative section without a model
    assert "Compliance score: 5.0" in report


def test_shared_trace_file_judges_only_own_events(tmp_path, settings):
    """Two agents may share one trace file (one process, two graphs — the
    soc-ir split). A cycle must ignore the other agent's events entirely."""
    import json

    seed = _seed(settings)
    mixed = tmp_path / "mixed.jsonl"
    own = (seed / "traces" / "loan-officer-clean.jsonl").read_text().splitlines()
    foreign = []
    for i in range(3):
        foreign.append(json.dumps({
            "agent_id": "someone-else", "run_id": f"x{i}", "seq": 0,
            "event_type": "tool_call", "node": "assess", "tool": "external_data_broker",
        }))
    mixed.write_text("\n".join(own + foreign) + "\n")

    service = _service(tmp_path, "w6")
    cycle = service.run_cycle(
        agent_id="loan-officer",
        baseline_path=seed / "baselines" / "loan-officer-profile.json",
        traces_path=mixed,
    )
    # the foreign rogue-tool events must not contaminate loan-officer's cycle
    assert cycle.compliance_score == 100.0
    assert cycle.anomalies == []
    assert cycle.runs_observed == 12  # only its own runs counted


def test_wrong_agent_baseline_pairing_is_fatal(tmp_path, settings):
    seed = _seed(settings)
    service = _service(tmp_path, "w5")
    import pytest

    with pytest.raises(ValueError, match="certifies agent"):
        service.run_cycle(
            agent_id="support-triage",
            baseline_path=seed / "baselines" / "loan-officer-profile.json",
            traces_path=seed / "traces" / "support-triage-clean.jsonl",
        )
