import pytest
from fastapi.testclient import TestClient

from driftlab.dashboard.app import create_app
from driftlab.monitor.runner import run_monitor


@pytest.fixture()
def client(settings):
    run_monitor(settings, force=True, send_email=False)
    return TestClient(create_app(settings))


def test_estate_and_health(client):
    assert client.get("/health").json()["status"] == "ok"
    page = client.get("/")
    assert page.status_code == 200
    assert "loan-officer" in page.text and "support-triage" in page.text


def test_agent_and_cycle_pages(client):
    estate = client.get("/api/estate").json()
    loan = next(e for e in estate if e["agent_id"] == "loan-officer")
    assert loan["compliance_score"] == 5.0
    assert client.get("/agents/loan-officer").status_code == 200
    cycle_page = client.get(f"/cycles/{loan['latest_cycle']}")
    assert cycle_page.status_code == 200
    assert "missing_hitl" in cycle_page.text or "HITL" in cycle_page.text
    assert "confirmed" in cycle_page.text


def test_anomaly_browser_filters(client):
    page = client.get("/anomalies?severity=critical")
    assert page.status_code == 200
    assert "high-value" in page.text
    empty = client.get("/anomalies?severity=critical&agent=support-triage")
    assert "estate clean" in empty.text


def test_artifact_download_and_ledger_api(client):
    estate = client.get("/api/estate").json()
    loan = next(e for e in estate if e["agent_id"] == "loan-officer")
    ledger = client.get(f"/api/cycles/{loan['latest_cycle']}/ledger").json()
    assert ledger["agent_id"] == "loan-officer" and len(ledger["anomalies"]) == 4
    report = client.get(f"/cycles/{loan['latest_cycle']}/artifacts/report.md")
    assert report.status_code == 200
    oscal = client.get(f"/cycles/{loan['latest_cycle']}/artifacts/assessment-results.json")
    assert oscal.status_code == 200


def test_404s(client):
    assert client.get("/agents/ghost").status_code == 404
    assert client.get("/cycles/ghost").status_code == 404
    estate = client.get("/api/estate").json()
    loan = next(e for e in estate if e["agent_id"] == "loan-officer")
    assert client.get(f"/cycles/{loan['latest_cycle']}/artifacts/../../secrets").status_code in (404, 422)


def test_store_containment(settings, tmp_path):
    from driftlab.store.artifacts import ArtifactPathError, LocalArtifactStore

    store = LocalArtifactStore(tmp_path / "arts")
    with pytest.raises(ArtifactPathError):
        store.save_json("../escape.json", {})
