"""Monitor runner — one estate-wide cycle (regitel monitor/runner.py, adapted).

Five phases: decide what to check -> run per-agent cycles (batch isolation:
one agent's failure never kills the run) -> collect deltas -> deliver digest
(email failures are recorded, never raised) -> record the run. Idempotent:
re-running within the staleness interval checks nothing.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from driftlab.clock import naive_utcnow
from driftlab.config import Settings
from driftlab.cycle import CycleService
from driftlab.domain.models import Severity, Verdict
from driftlab.monitor.digest import MonitorDigest, render_html, render_text
from driftlab.monitor.notifier import NotifierError, send_digest_email
from driftlab.monitor.policy import select_due_agents
from driftlab.monitor.registry import AgentSpec, load_registry, sync_registry
from driftlab.store.db import AgentRow, CycleRow, Database, MonitorRunRow

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return naive_utcnow()


def run_monitor(
    settings: Settings,
    database: Database | None = None,
    *,
    agents: list[str] | None = None,
    limit: int | None = None,
    force: bool = False,
    send_email: bool = True,
    trigger: str = "manual",
    llm: Any | None = None,
) -> tuple[MonitorDigest, dict[str, Any]]:
    settings.ensure_dirs()
    database = database or Database(settings.db_path)
    run_id = str(uuid.uuid4())[:8]
    started = _now()
    digest = MonitorDigest(run_id=run_id, started_at=started.strftime("%Y-%m-%dT%H:%M:%SZ"))

    # Phase 1 — registry sync + due selection
    specs = load_registry(settings.registry_path)
    sync_registry(database, specs)
    spec_by_id = {s.id: s for s in specs}

    if agents:
        selected_ids = [a for a in agents if a in spec_by_id]
        for missing in sorted(set(agents) - set(selected_ids)):
            digest.errors.append({"agent_id": missing, "error": "not in registry"})
    else:
        due = select_due_agents(
            database,
            settings.intervals_days,
            settings.default_interval_days,
            max_count=limit or settings.max_agents_per_run,
            include_all=force,
        )
        selected_ids = [d.id for d in due]

    # Phase 2 — per-agent cycles, isolated
    service = CycleService(settings, database=database, llm=llm)
    previous_scores = _latest_scores(database)
    for agent_id in selected_ids:
        spec: AgentSpec = spec_by_id[agent_id]
        try:
            cycle = service.run_cycle(
                agent_id=agent_id,
                baseline_path=spec.baseline,
                traces_path=spec.traces,
                trigger=trigger,
            )
        except Exception as exc:  # batch isolation — record, continue
            logger.error("monitor %s: cycle for %s failed: %s", run_id, agent_id, exc)
            digest.errors.append({"agent_id": agent_id, "error": f"{type(exc).__name__}: {exc}"})
            continue

        confirmed = [e for e in cycle.experiments if e.verdict is Verdict.CONFIRMED]
        refuted = [e for e in cycle.experiments if e.verdict is Verdict.REFUTED]
        digest.agents_checked.append(
            {
                "id": agent_id,
                "score": cycle.compliance_score,
                "anomalies": len(cycle.anomalies),
                "confirmed": len(confirmed),
                "cycle_id": cycle.cycle_id,
            }
        )
        for anomaly in cycle.anomalies:
            if anomaly.severity is Severity.CRITICAL and anomaly.waiver_status == "none":
                digest.new_critical.append({"agent_id": agent_id, "title": anomaly.title})
        for record in confirmed:
            digest.confirmed_drifts.append(
                {
                    "agent_id": agent_id,
                    "kind": record.hypothesis.kind.value,
                    "validity": record.validity_score,
                    "statement": record.hypothesis.statement,
                }
            )
        for record in refuted:
            digest.refuted_drifts.append({"agent_id": agent_id, "kind": record.hypothesis.kind.value})
        prev = previous_scores.get(agent_id)
        if prev is not None and cycle.compliance_score < prev:
            digest.score_drops.append({"id": agent_id, "previous": prev, "current": cycle.compliance_score})

        with database.session() as session:
            row = session.get(AgentRow, agent_id)
            if row is not None:
                row.last_checked_at = _now()  # closes the staleness loop

    digest.finished_at = _now().strftime("%Y-%m-%dT%H:%M:%SZ")

    # Phase 3 — deliver (never raises)
    email_sent, email_error = False, None
    should_send = send_email and settings.email.enabled and (digest.has_alerts or settings.email.send_empty)
    if should_send:
        try:
            recipient = send_digest_email(
                settings.email,
                subject=digest.subject,
                text_body=render_text(digest),
                html_body=render_html(digest),
            )
            email_sent = True
            logger.info("monitor %s: digest sent to %s", run_id, recipient)
        except NotifierError as exc:
            email_error = str(exc)
            logger.error("monitor %s: %s", run_id, email_error)
    email_skipped_reason = None
    if not should_send:
        if not send_email:
            email_skipped_reason = "--no-email"
        elif not settings.email.enabled:
            email_skipped_reason = "disabled in config"
        else:
            email_skipped_reason = "nothing to report"

    # Phase 4 — record the run
    with database.session() as session:
        session.add(
            MonitorRunRow(
                id=run_id,
                started_at=started,
                finished_at=_now(),
                agents_scanned=json.dumps(selected_ids),
                trigger=trigger,
                cycles_run=len(digest.agents_checked),
                new_critical=len(digest.new_critical),
                confirmed_drifts=len(digest.confirmed_drifts),
                email_sent=email_sent,
                status="completed",
                error_log=json.dumps(digest.errors) if digest.errors else None,
            )
        )

    meta = {
        "run_id": run_id,
        "selected": selected_ids,
        "email_sent": email_sent,
        "email_error": email_error,
        "email_skipped_reason": email_skipped_reason,
    }
    return digest, meta


def _latest_scores(database: Database) -> dict[str, float]:
    """agent_id -> most recent compliance score (for score-drop alerts)."""
    with database.session() as session:
        rows = (
            session.query(CycleRow.agent_id, CycleRow.compliance_score, CycleRow.finished_at)
            .order_by(CycleRow.agent_id, CycleRow.finished_at.asc())
            .all()
        )
    scores: dict[str, float] = {}
    for agent_id, score, _finished in rows:
        scores[agent_id] = score  # last write wins = latest finished_at
    return scores
