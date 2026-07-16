"""Monitor runner — one estate cycle over the registry.

Runs each due agent's compliance cycle, persists results, writes artifacts,
and (optionally) sends a digest. Never raises on a single agent's failure: a
failed agent is recorded as an error and the rest of the estate continues.
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..cycle import run_cycle
from ..emit import emit_assessment_plan, emit_assessment_results, emit_report
from ..ingest import load_jsonl
from ..store import AgentRecord, CycleRecord, init_db, record_agent_run, upsert_cycle
from .notifier import send_digest
from .policy import StalenessPolicy
from .registry import AgentSpec, load_registry


def run_estate(
    registry_path: str | Path | None = None,
    force: bool = False,
    no_email: bool = False,
    scheduled: bool = False,
    run_experiments: bool = True,
) -> dict[str, Any]:
    settings = get_settings()
    settings.ensure_dirs()
    init_db()
    registry_path = registry_path or settings.registry_path or (
        Path(__file__).resolve().parent.parent / "seed" / "agents.yaml"
    )
    agents = load_registry(registry_path)
    policy = StalenessPolicy()

    # Upsert agent rows.
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from ..store import Base, _engine
    Base.metadata.create_all(_engine())
    with Session(_engine()) as s:
        for a in agents:
            rec = s.get(AgentRecord, a.id)
            if not rec:
                s.add(AgentRecord(id=a.id, name=a.name, baseline=a.baseline,
                                  trace=a.trace, priority=a.priority, owner=a.owner))
        s.commit()

    summary: dict[str, Any] = {"ran": [], "skipped": [], "errors": []}
    for a in agents:
        due = force or policy.is_due(a.priority, _last_cycle(a.id))
        if not due:
            summary["skipped"].append(a.id)
            continue
        try:
            result = _run_one(a, settings, run_experiments)
            summary["ran"].append({
                "agent": a.id, "score": result["score"], "cycle_id": result["cycle_id"],
            })
        except Exception as exc:  # never kill the whole estate
            summary["errors"].append({"agent": a.id, "error": str(exc)})
            traceback.print_exc()

    if not no_email and settings.email__enabled:
        send_digest(summary)

    return summary


def _last_cycle(agent_id: str) -> str | None:
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from ..store import AgentRecord, _engine
    with Session(_engine()) as s:
        rec = s.get(AgentRecord, agent_id)
        return rec.last_cycle if rec else None


def load_agent_resources(a: AgentSpec, seed_root: Path, settings) -> list | None:
    """Resolve an agent's recorded resource stream (DL-8 telemetry plane).

    Registry-declared streams must exist — a declared-but-missing stream
    raises (fail closed, evidence must never silently vanish). Without a
    registry entry, the live sensor default path is picked up when present.
    """
    from ..sensor import load_resource_jsonl

    if a.resource:
        return load_resource_jsonl(_resolve(a.resource, seed_root))
    live = settings.data_dir / "resource" / f"{a.id}.jsonl"
    if live.exists():
        return load_resource_jsonl(live)
    return None


def _run_one(a: AgentSpec, settings, run_experiments: bool) -> dict[str, Any]:
    seed_root = Path(__file__).resolve().parent.parent / "seed"
    baseline_path = _resolve(a.baseline, seed_root)
    trace_path = _resolve(a.trace, seed_root)
    events = load_jsonl(trace_path, a.id)
    resource_records = load_agent_resources(a, seed_root, settings)
    result = run_cycle(a.id, str(baseline_path), events, run_experiments=run_experiments,
                       resource_records=resource_records)

    out_dir = settings.artifacts_dir / a.id / result.cycle_id
    emit_assessment_plan(a.id, _policy_for(baseline_path), out_dir)
    emit_assessment_results(a.id, _policy_for(baseline_path), result, out_dir)
    emit_report(a.id, result, out_dir)

    ledger_json = json.dumps(result.to_ledger(), indent=2, sort_keys=True)
    (out_dir / "ledger.json").write_text(ledger_json)

    upsert_cycle(CycleRecord(
        id=result.cycle_id, agent=a.id, baseline_hash=result.baseline_hash,
        trace_hash=result.trace_hash, score=result.score, ledger=ledger_json,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
    record_agent_run(a.id)
    return {"score": result.score, "cycle_id": result.cycle_id}


def _resolve(p: str, seed_root: Path) -> Path:
    pp = Path(p)
    return pp if pp.is_absolute() else (seed_root / pp)


def _policy_for(baseline_path: Path):
    from ..baseline import BaselineCompiler, load_profile
    return BaselineCompiler().compile(load_profile(baseline_path))