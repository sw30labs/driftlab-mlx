"""Deck snapshot builders — read-only projections of the compliance store.

Everything the command deck renders is derived here from the same artifacts the
CLI produces: the agent registry, the persisted cycle ledgers, and the emitted
OSCAL evidence on disk. Nothing in this module computes a severity, a verdict,
or a score — it only reshapes what the deterministic engine already decided.

Every builder is total: a clean agent with no anomalies, an agent that has
never been checked, and a missing artifacts directory all produce a valid
payload rather than an error.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..baseline import CONTROL_FAMILY
from ..config import get_settings
from ..monitor.policy import StalenessPolicy
from ..monitor.registry import AgentSpec, load_registry
from ..store import AgentRecord, CycleRecord, _engine, init_db

SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]
_SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITY_ORDER)}

# Mirrors driftlab.anomaly.SEVERITY_WEIGHT — shown in the UI to explain a score.
SEVERITY_WEIGHT = {"critical": 35, "high": 20, "medium": 8, "low": 3, "info": 1}

_ARTIFACT_FILES = ("assessment-plan.json", "assessment-results.json",
                   "report.md", "ledger.json")


def registry_path() -> Path:
    s = get_settings()
    return Path(s.registry_path) if s.registry_path else seed_root() / "agents.yaml"


def seed_root() -> Path:
    return Path(__file__).resolve().parent.parent / "seed"


def load_agents() -> list[AgentSpec]:
    """The monitored roster. A broken registry yields an empty estate, not a
    crashed deck — but the reason still reaches the operator via the API's
    error response rather than being swallowed here."""
    try:
        return load_registry(registry_path())
    except FileNotFoundError:
        return []


# -- store access ---------------------------------------------------------

_DB_READY: set[str] = set()
_DB_LOCK = threading.Lock()


def _ensure_db() -> None:
    """Create the schema once per database, not once per HTTP request.

    ``init_db`` issues CREATE TABLE with checkfirst=True, which is a probe
    followed by a separate statement — two deck threads hitting a fresh store
    concurrently can both pass the probe. Keyed by db path so a test that
    repoints DRIFTLAB_DATA_DIR still gets its schema.
    """
    path = str(get_settings().db_path)
    if path in _DB_READY:
        return
    with _DB_LOCK:
        if path not in _DB_READY:
            init_db()
            _DB_READY.add(path)


def _cycles_by_agent() -> dict[str, list[CycleRecord]]:
    """Every persisted cycle, newest first, grouped by agent."""
    _ensure_db()
    with Session(_engine()) as s:
        rows = s.execute(
            select(CycleRecord).order_by(CycleRecord.created_at.desc())
        ).scalars().all()
        out: dict[str, list[CycleRecord]] = {}
        for row in rows:
            out.setdefault(row.agent, []).append(row)
        return out


def _agent_rows() -> dict[str, AgentRecord]:
    _ensure_db()
    with Session(_engine()) as s:
        return {r.id: r for r in s.execute(select(AgentRecord)).scalars().all()}


def _ledger_of(record: CycleRecord | None) -> dict[str, Any]:
    if record is None or not record.ledger:
        return {}
    try:
        return json.loads(record.ledger)
    except json.JSONDecodeError:
        return {}


# -- derived helpers ------------------------------------------------------


def score_band(score: int | None) -> str:
    if score is None:
        return "unknown"
    if score >= 90:
        return "ok"
    if score >= 60:
        return "warn"
    return "bad"


def _age_hours(last_cycle: str | None, now: datetime) -> float | None:
    if not last_cycle:
        return None
    try:
        last = datetime.fromisoformat(last_cycle.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (now - last).total_seconds() / 3600.0)


def _active(anomalies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [a for a in anomalies if not a.get("waived")]


def _sev_counts(anomalies: list[dict[str, Any]]) -> dict[str, int]:
    counts = {s: 0 for s in SEVERITY_ORDER}
    for a in anomalies:
        sev = str(a.get("severity", "info"))
        if sev in counts:
            counts[sev] += 1
    return counts


def artifact_dir(agent: str, cycle_id: str) -> Path:
    return get_settings().artifacts_dir / agent / cycle_id


def _artifacts_for(agent: str, cycle_id: str) -> list[dict[str, Any]]:
    """Evidence files emitted for a cycle, with size and relative path."""
    base = artifact_dir(agent, cycle_id)
    out: list[dict[str, Any]] = []
    for name in _ARTIFACT_FILES:
        path = base / name
        try:
            size = path.stat().st_size
        except OSError:
            continue
        out.append({
            "name": name,
            "size": size,
            "rel": f"{agent}/{cycle_id}/{name}",
        })
    return out


# -- per-agent projection -------------------------------------------------


def agent_snapshot(
    spec: AgentSpec,
    record: CycleRecord | None,
    history: list[CycleRecord],
    row: AgentRecord | None,
    now: datetime,
    policy: StalenessPolicy,
) -> dict[str, Any]:
    ledger = _ledger_of(record)
    anomalies = list(ledger.get("anomalies") or [])
    experiments = list(ledger.get("experiments") or [])
    active = _active(anomalies)
    last_cycle = (row.last_cycle if row else None) or (record.created_at if record else None)
    age = _age_hours(last_cycle, now)
    interval = policy.interval_hours(spec.priority)
    resource = ledger.get("resource")

    return {
        "id": spec.id,
        "name": spec.name,
        "owner": spec.owner,
        "priority": spec.priority,
        "baseline": spec.baseline,
        "trace": spec.trace,
        "resource_stream": spec.resource,
        "score": ledger.get("score") if ledger else (record.score if record else None),
        "band": score_band(ledger.get("score") if ledger else None),
        "cycle_id": ledger.get("cycle_id") or (record.id if record else None),
        "baseline_hash": ledger.get("baseline_hash", ""),
        "trace_hash": ledger.get("trace_hash", ""),
        "resource_hash": ledger.get("resource_hash", ""),
        "last_cycle": last_cycle,
        "age_hours": age,
        "interval_hours": interval,
        "due": policy.is_due(spec.priority, last_cycle, now=now),
        "staleness": None if age is None else min(1.0, age / interval),
        "anomalies_total": len(anomalies),
        "anomalies_active": len(active),
        "waived": len(anomalies) - len(active),
        "severities": _sev_counts(active),
        "controls_violated": sorted({a["control"] for a in active if a.get("control")}),
        "experiments": len(experiments),
        "confirmed": sum(1 for e in experiments if e.get("verdict") == "confirmed"),
        "resource": resource,
        "cycles": len(history),
        "history": [
            {"cycle_id": c.id, "score": c.score, "created_at": c.created_at}
            for c in history[:30]
        ],
        "artifacts": _artifacts_for(spec.id, record.id) if record else [],
    }


# -- estate-wide flattening ----------------------------------------------


def _flatten_findings(agents: list[dict[str, Any]], ledgers: dict[str, dict]) -> list[dict[str, Any]]:
    """Every anomaly across the estate, joined to its experiment verdict."""
    out: list[dict[str, Any]] = []
    for a in agents:
        ledger = ledgers.get(a["id"]) or {}
        exp_by_anomaly = {
            e.get("anomaly_id"): e for e in (ledger.get("experiments") or [])
        }
        for anomaly in ledger.get("anomalies") or []:
            experiment = exp_by_anomaly.get(anomaly.get("id"))
            out.append({
                **anomaly,
                "agent": a["id"],
                "agent_name": a["name"],
                "cycle_id": ledger.get("cycle_id"),
                "weight": SEVERITY_WEIGHT.get(str(anomaly.get("severity")), 0),
                "verdict": (experiment or {}).get("verdict", "not-run"),
                "rationale": (experiment or {}).get("rationale", ""),
                "probe": (experiment or {}).get("probe"),
            })
    out.sort(key=lambda f: (
        _SEVERITY_RANK.get(str(f.get("severity")), 99),
        bool(f.get("waived")),
        str(f.get("agent")),
        str(f.get("control")),
    ))
    return out


def _flatten_experiments(agents: list[dict[str, Any]], ledgers: dict[str, dict]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for a in agents:
        ledger = ledgers.get(a["id"]) or {}
        by_id = {an.get("id"): an for an in (ledger.get("anomalies") or [])}
        for e in ledger.get("experiments") or []:
            anomaly = by_id.get(e.get("anomaly_id")) or {}
            probe = e.get("probe") or {}
            out.append({
                "agent": a["id"],
                "agent_name": a["name"],
                "cycle_id": ledger.get("cycle_id"),
                "anomaly_id": e.get("anomaly_id"),
                "control": e.get("control"),
                "verdict": e.get("verdict"),
                "rationale": e.get("rationale", ""),
                "title": anomaly.get("title", ""),
                "severity": anomaly.get("severity", ""),
                "kind": probe.get("kind", ""),
                "samples": probe.get("samples", 0),
                "violations": probe.get("violations", 0),
                "detail": probe.get("detail", ""),
            })
    order = {"confirmed": 0, "inconclusive": 1, "refuted": 2}
    out.sort(key=lambda e: (order.get(str(e["verdict"]), 9), str(e["agent"]), str(e["control"])))
    return out


def _control_rollup(agents: list[dict[str, Any]], findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """DL-1..8 estate-wide posture: who violates what, and with what proof."""
    checked = [a for a in agents if a["cycle_id"]]
    out: list[dict[str, Any]] = []
    for control in CONTROL_FAMILY:
        hits = [f for f in findings if f.get("control") == control.id and not f.get("waived")]
        offenders = sorted({f["agent"] for f in hits})
        out.append({
            "id": control.id,
            "title": control.title,
            "description": control.description,
            "nist_800_53": list(control.nist_800_53),
            "is_ca7": control.is_ca7,
            "findings": len(hits),
            "confirmed": sum(1 for f in hits if f.get("verdict") == "confirmed"),
            "agents_violating": offenders,
            "agents_checked": len(checked),
            "severities": _sev_counts(hits),
            "status": "not-satisfied" if hits else ("satisfied" if checked else "unassessed"),
        })
    return out


def _resource_rollup(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """DL-8 spend vs certified ceilings, per agent, per currency."""
    out: list[dict[str, Any]] = []
    for a in agents:
        resource = a.get("resource")
        if not resource:
            continue
        ceilings = resource.get("ceilings") or {}
        spent = resource.get("spent") or {}
        currencies = []
        for currency in sorted(set(ceilings) | set(spent)):
            ceiling = ceilings.get(currency)
            used = float(spent.get(currency, 0.0))
            currencies.append({
                "currency": currency,
                "spent": used,
                "ceiling": ceiling,
                "ratio": (used / ceiling) if ceiling else None,
                "exceeded": bool(ceiling is not None and used > ceiling),
            })
        out.append({
            "agent": a["id"],
            "agent_name": a["name"],
            "records": resource.get("records", 0),
            "breaker_fired": bool(resource.get("breaker_fired")),
            "fidelity_observed": resource.get("fidelity_observed") or [],
            "currencies": currencies,
            "exceeded": any(c["exceeded"] for c in currencies),
        })
    return out


def _kpis(agents: list[dict[str, Any]], findings: list[dict[str, Any]],
          experiments: list[dict[str, Any]], controls: list[dict[str, Any]],
          resources: list[dict[str, Any]]) -> dict[str, Any]:
    checked = [a for a in agents if a["score"] is not None]
    scores = [a["score"] for a in checked]
    active = [f for f in findings if not f.get("waived")]
    return {
        "agents": len(agents),
        "agents_checked": len(checked),
        "agents_due": sum(1 for a in agents if a["due"]),
        "estate_score": round(sum(scores) / len(scores)) if scores else None,
        "worst_score": min(scores) if scores else None,
        "worst_agent": min(checked, key=lambda a: a["score"])["id"] if checked else None,
        "anomalies_active": len(active),
        "waived": len(findings) - len(active),
        "critical": sum(1 for f in active if f.get("severity") == "critical"),
        "high": sum(1 for f in active if f.get("severity") == "high"),
        "confirmed": sum(1 for e in experiments if e.get("verdict") == "confirmed"),
        "refuted": sum(1 for e in experiments if e.get("verdict") == "refuted"),
        "inconclusive": sum(1 for e in experiments if e.get("verdict") == "inconclusive"),
        "controls_violated": sum(1 for c in controls if c["status"] == "not-satisfied"),
        "controls_total": len(controls),
        "resource_breaches": sum(1 for r in resources if r["exceeded"]),
        "breaker_fired": sum(1 for r in resources if r["breaker_fired"]),
    }


# -- public entry ---------------------------------------------------------


def build_snapshot() -> dict[str, Any]:
    """The full deck payload. Total: an empty store yields an empty estate."""
    now = datetime.now(timezone.utc)
    policy = StalenessPolicy()
    specs = load_agents()
    history = _cycles_by_agent()
    rows = _agent_rows()

    agents: list[dict[str, Any]] = []
    ledgers: dict[str, dict[str, Any]] = {}
    for spec in specs:
        agent_history = history.get(spec.id, [])
        latest = agent_history[0] if agent_history else None
        ledgers[spec.id] = _ledger_of(latest)
        agents.append(agent_snapshot(spec, latest, agent_history, rows.get(spec.id), now, policy))
    agents.sort(key=lambda a: (a["score"] if a["score"] is not None else 101, a["id"]))

    findings = _flatten_findings(agents, ledgers)
    experiments = _flatten_experiments(agents, ledgers)
    controls = _control_rollup(agents, findings)
    resources = _resource_rollup(agents)

    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "registry": str(registry_path()),
        "data_dir": str(get_settings().data_dir),
        "kpis": _kpis(agents, findings, experiments, controls, resources),
        "agents": agents,
        "findings": findings,
        "experiments": experiments,
        "controls": controls,
        "resources": resources,
        "severity_weights": SEVERITY_WEIGHT,
    }


def agent_detail(agent_id: str) -> dict[str, Any] | None:
    """One agent with its full latest ledger attached."""
    now = datetime.now(timezone.utc)
    policy = StalenessPolicy()
    spec = next((s for s in load_agents() if s.id == agent_id), None)
    if spec is None:
        return None
    agent_history = _cycles_by_agent().get(agent_id, [])
    latest = agent_history[0] if agent_history else None
    snap = agent_snapshot(spec, latest, agent_history, _agent_rows().get(agent_id), now, policy)
    snap["ledger"] = _ledger_of(latest)
    return snap


def read_artifact(rel: str) -> tuple[bytes, str] | None:
    """Read an emitted evidence file. Returns ``(body, content_type)``.

    ``rel`` is ``agent/cycle_id/filename``. The resolved path must stay inside
    the artifacts directory and name a known artifact — evidence is served
    read-only, and the deck must never become a file browser.
    """
    parts = Path(rel).parts
    if len(parts) != 3 or parts[2] not in _ARTIFACT_FILES:
        return None
    root = get_settings().artifacts_dir.resolve()
    try:
        path = (root / rel).resolve()
        path.relative_to(root)
        body = path.read_bytes()
    except (OSError, ValueError):
        return None
    content_type = ("application/json" if path.suffix == ".json"
                    else "text/markdown; charset=utf-8")
    return body, content_type
