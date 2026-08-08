"""Web command deck — snapshot projection, HTTP surface, and its guardrails.

The deck is stdlib-only, so these tests drive a real ``ThreadingHTTPServer``
over a real socket rather than a framework test client.
"""

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

SEED = Path(__file__).resolve().parent.parent / "src" / "driftlab" / "seed"


@pytest.fixture
def estate(tmp_path, monkeypatch):
    """A checked estate in an isolated data dir."""
    monkeypatch.setenv("DRIFTLAB_DATA_DIR", str(tmp_path / ".driftlab"))
    monkeypatch.setenv("DRIFTLAB_LLM_PROVIDER", "none")
    from driftlab.config import get_settings
    get_settings.cache_clear()
    from driftlab.monitor.runner import run_estate
    run_estate(force=True, no_email=True)
    yield
    get_settings.cache_clear()


@pytest.fixture
def deck(estate):
    """A live deck server; yields its base URL."""
    from driftlab.web.server import DeckHandler
    server = ThreadingHTTPServer(("127.0.0.1", 0), DeckHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get(url, decode_json=True, host=None):
    req = urllib.request.Request(url)
    if host is not None:  # "" is a real case — an absent Host must be rejected
        req.add_header("Host", host)
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode("utf-8")
        return (json.loads(body) if decode_json else body), resp.status, dict(resp.headers)


def _post(url, payload, content_type="application/json"):
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode()), resp.status
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read().decode() or "{}"), exc.code


# -- snapshot projection --------------------------------------------------


def test_snapshot_projects_both_agents(estate):
    from driftlab.web.state import build_snapshot
    snap = build_snapshot()

    by_id = {a["id"]: a for a in snap["agents"]}
    assert by_id["support-triage"]["score"] == 100
    assert by_id["loan-officer"]["score"] < 50
    # Worst agent sorts first so the deck leads with the problem.
    assert snap["agents"][0]["id"] == "loan-officer"

    # A clean agent must project as a valid, empty shape — not a hole.
    clean = by_id["support-triage"]
    assert clean["anomalies_active"] == 0
    assert clean["controls_violated"] == []
    assert clean["band"] == "ok"

    k = snap["kpis"]
    assert k["agents_checked"] == 2
    assert k["estate_score"] == round((0 + 100) / 2)
    assert k["controls_violated"] > 0
    assert len(snap["controls"]) == 8


def test_snapshot_is_total_on_an_empty_store(tmp_path, monkeypatch):
    """Never-checked agents must render, not raise."""
    monkeypatch.setenv("DRIFTLAB_DATA_DIR", str(tmp_path / "empty"))
    from driftlab.config import get_settings
    get_settings.cache_clear()
    from driftlab.web.state import build_snapshot

    snap = build_snapshot()
    assert snap["kpis"]["agents_checked"] == 0
    assert snap["kpis"]["estate_score"] is None
    assert snap["findings"] == [] and snap["experiments"] == []
    assert all(a["score"] is None and a["due"] for a in snap["agents"])
    assert all(c["status"] == "unassessed" for c in snap["controls"])
    get_settings.cache_clear()


def test_findings_join_their_experiment_verdicts(estate):
    from driftlab.web.state import build_snapshot
    snap = build_snapshot()

    findings = [f for f in snap["findings"] if f["agent"] == "loan-officer"]
    assert findings, "the dirty agent must produce findings"
    # Severity-ordered: criticals lead.
    assert findings[0]["severity"] == "critical"
    proven = [f for f in findings if f["verdict"] == "confirmed"]
    assert proven and all(f["probe"]["samples"] > 0 for f in proven)
    # Score arithmetic stays traceable in the UI.
    penalty = sum(f["weight"] for f in findings if not f["waived"])
    assert 100 - penalty <= 0


def test_resource_rollup_reports_the_dl8_breach(estate):
    from driftlab.web.state import build_snapshot
    rollup = {r["agent"]: r for r in build_snapshot()["resources"]}

    loan = rollup["loan-officer"]
    assert loan["records"] > 0
    breached = [c for c in loan["currencies"] if c["exceeded"]]
    assert breached, "the seed stream overshoots a certified ceiling"
    assert all(c["spent"] > c["ceiling"] for c in breached)


# -- HTTP surface ---------------------------------------------------------


def test_deck_serves_the_shell_and_state(deck):
    html, status, headers = _get(deck + "/", decode_json=False)
    assert status == 200
    assert "DRIFTLAB" in html
    # Air-gapped: no external origins may be referenced at all.
    assert "http://" not in html.replace("http://127.0.0.1", "").replace(
        "http://www.w3.org", "")
    assert headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in headers["Content-Security-Policy"]

    state, status, _ = _get(deck + "/api/state")
    assert status == 200 and len(state["agents"]) == 2

    health, _, _ = _get(deck + "/api/health")
    assert health["ok"] is True and health["busy"] is False


def test_agent_detail_carries_the_ledger(deck):
    detail, status, _ = _get(deck + "/api/agent?id=loan-officer")
    assert status == 200
    assert detail["ledger"]["cycle_id"] == detail["cycle_id"]
    assert detail["ledger"]["anomalies"]

    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(deck + "/api/agent?id=ghost")
    assert exc.value.code == 404


def test_run_endpoint_validates_its_input(deck):
    body, status = _post(deck + "/api/run", {"scope": "agent", "agent": "ghost"})
    assert status == 400 and "unknown agent" in body["error"]

    body, status = _post(deck + "/api/run", {"scope": "sideways"})
    assert status == 400

    body, status = _post(deck + "/api/run", b"{}", content_type="text/plain")
    assert status == 415

    body, status = _post(deck + "/api/run", b"not json")
    assert status == 400

    body, status = _post(deck + "/api/run", b'["a"]')
    assert status == 400 and "object" in body["error"]

    body, status = _post(deck + "/api/run", b'{"pad":"' + b"x" * 70_000 + b'"}')
    assert status == 413


def test_evidence_is_served_but_scoped_to_known_artifacts(deck):
    state, _, _ = _get(deck + "/api/state")
    loan = next(a for a in state["agents"] if a["id"] == "loan-officer")
    names = {f["name"] for f in loan["artifacts"]}
    assert {"assessment-plan.json", "assessment-results.json",
            "report.md", "ledger.json"} <= names

    rel = next(f["rel"] for f in loan["artifacts"] if f["name"] == "report.md")
    report, status, _ = _get(deck + "/api/evidence?rel=" + rel, decode_json=False)
    assert status == 200 and "DriftLab Compliance Report" in report

    for escape in ("../../../../etc/passwd",
                   "loan-officer/../../../../etc/passwd",
                   "loan-officer/abc/../../../secrets.txt"):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(deck + "/api/evidence?rel=" + urllib.parse.quote(escape))
        assert exc.value.code == 404


def test_narrative_is_refused_while_the_llm_is_off(deck):
    body, status = _post(deck + "/api/narrative", {"agent": "loan-officer"})
    assert status == 400 and "disabled" in body["error"]

    status_payload, _, _ = _get(deck + "/api/llm")
    assert status_payload["enabled"] is False
    assert status_payload["reachable"] is False


def test_a_cycle_runs_through_the_api(deck):
    body, status = _post(deck + "/api/run", {"scope": "agent", "agent": "support-triage"})
    assert status == 202 and body["job_id"]

    job = _wait_for_job(deck, body["job_id"])
    assert job["status"] == "done", job
    assert [r["agent"] for r in job["result"]["ran"]] == ["support-triage"]

    events, _, _ = _get(deck + "/api/events?limit=200")
    kinds = [e["kind"] for e in events["events"]]
    assert "cycle.scored" in kinds and "agent.finished" in kinds


def _wait_for_job(deck, job_id, timeout=60.0):
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job, _, _ = _get(f"{deck}/api/jobs/{job_id}")
        if job.get("status") != "running":
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} never finished")


def test_bind_host_must_be_loopback():
    from driftlab.web.server import serve
    with pytest.raises(SystemExit, match="loopback"):
        serve(host="0.0.0.0", open_browser=False)


def test_foreign_host_header_is_rejected(deck):
    """The peer-address check alone does not stop DNS rebinding: under a rebind
    the browser *is* the loopback peer. Host must be pinned to this listener."""
    port = deck.rsplit(":", 1)[1]
    for good in (f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"):
        _, status, _ = _get(deck + "/api/health", host=good)
        assert status == 200, good

    for evil in ("evil.example", f"evil.example:{port}", "127.0.0.1",
                 f"127.0.0.1:{int(port) + 1}", ""):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(deck + "/api/state", host=evil)
        assert exc.value.code == 421, evil

    # The rebinding path targets writes too, not just reads.
    req = urllib.request.Request(deck + "/api/run", data=b'{"scope":"estate"}',
                                 method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Host": "evil.example"})
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=10)
    assert exc.value.code == 421


def test_a_broken_registry_answers_500_rather_than_dropping_the_connection(deck, tmp_path):
    from driftlab.config import get_settings
    bad = tmp_path / "broken.yaml"
    bad.write_text("agents: [ this: is: not: valid\n")
    get_settings().registry_path = bad
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(deck + "/api/state")
        assert exc.value.code == 500
        assert "error" in json.loads(exc.value.read().decode())
    finally:
        get_settings().registry_path = None


def test_artifact_containment_guard_blocks_a_symlink_escape(estate, tmp_path):
    """A 3-part path that passes the allow-list can still escape via a symlink;
    the resolve()-then-relative_to guard is what stops it."""
    from driftlab.config import get_settings
    from driftlab.web.state import read_artifact

    secret = tmp_path / "outside-secret.md"
    secret.write_text("classified")
    escape = get_settings().artifacts_dir / "loan-officer" / "escape"
    escape.mkdir(parents=True, exist_ok=True)
    link = escape / "report.md"
    link.unlink(missing_ok=True)
    link.symlink_to(secret)

    # The allow-list passes this (3 parts, known filename) — containment must not.
    assert read_artifact("loan-officer/escape/report.md") is None
