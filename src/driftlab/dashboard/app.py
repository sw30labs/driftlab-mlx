"""FastAPI + Jinja dashboard — estate view, agent detail, cycle detail,
anomaly browser, evidence downloads. Server-rendered, zero CDN dependencies
(local-first: the dashboard must work air-gapped), glass-graph palette.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from driftlab.config import Settings, get_settings
from driftlab.domain.rendering import score_class
from driftlab.store.artifacts import LocalArtifactStore
from driftlab.store.db import AgentRow, AnomalyRow, CycleRow, Database, ExperimentRow, MonitorRunRow

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()
    database = database or Database(settings.db_path)
    store = LocalArtifactStore(settings.artifacts_dir)
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.globals["score_class"] = score_class

    app = FastAPI(title="DriftLab", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.database = database

    # -- helpers -------------------------------------------------------------
    def latest_cycles(session) -> dict[str, CycleRow]:
        latest: dict[str, CycleRow] = {}
        for row in session.query(CycleRow).order_by(CycleRow.finished_at.asc()).all():
            latest[row.agent_id] = row
        return latest

    # -- html ------------------------------------------------------------------
    @app.get("/")
    def dashboard(request: Request):
        with database.session() as session:
            agents = session.query(AgentRow).order_by(AgentRow.priority, AgentRow.id).all()
            latest = latest_cycles(session)
            runs = (
                session.query(MonitorRunRow).order_by(MonitorRunRow.started_at.desc()).limit(10).all()
            )
        estate = []
        for agent in agents:
            cycle = latest.get(agent.id)
            estate.append(
                {
                    "agent": agent,
                    "cycle": cycle,
                    "counts": json.loads(cycle.severity_counts) if cycle else {},
                }
            )
        return templates.TemplateResponse(
            request, "dashboard.html", {"estate": estate, "runs": runs}
        )

    @app.get("/agents/{agent_id}")
    def agent_detail(request: Request, agent_id: str):
        with database.session() as session:
            agent = session.get(AgentRow, agent_id)
            if agent is None:
                raise HTTPException(404, f"unknown agent {agent_id}")
            cycles = (
                session.query(CycleRow)
                .filter(CycleRow.agent_id == agent_id)
                .order_by(CycleRow.finished_at.desc())
                .limit(50)
                .all()
            )
        return templates.TemplateResponse(request, "agent.html", {"agent": agent, "cycles": cycles})

    @app.get("/cycles/{cycle_id}")
    def cycle_detail(request: Request, cycle_id: str):
        with database.session() as session:
            cycle = session.get(CycleRow, cycle_id)
            if cycle is None:
                raise HTTPException(404, f"unknown cycle {cycle_id}")
            anomalies = (
                session.query(AnomalyRow)
                .filter(AnomalyRow.cycle_id == cycle_id)
                .order_by(AnomalyRow.severity, AnomalyRow.fingerprint)
                .all()
            )
            experiments = (
                session.query(ExperimentRow)
                .filter(ExperimentRow.cycle_id == cycle_id)
                .order_by(ExperimentRow.anomaly_fingerprint)
                .all()
            )
        artifacts = store.list_dir(Path(cycle.agent_id) / cycle_id)
        experiments_payload = [
            {"row": row, "record": json.loads(row.payload or "{}")} for row in experiments
        ]
        return templates.TemplateResponse(
            request,
            "cycle.html",
            {
                "cycle": cycle,
                "counts": json.loads(cycle.severity_counts or "{}"),
                "anomalies": anomalies,
                "experiments": experiments_payload,
                "artifacts": artifacts,
            },
        )

    @app.get("/anomalies")
    def anomalies(request: Request, severity: str | None = None, agent: str | None = None):
        with database.session() as session:
            latest = latest_cycles(session)
            latest_ids = {c.cycle_id for c in latest.values()}
            query = session.query(AnomalyRow).filter(AnomalyRow.cycle_id.in_(latest_ids))
            if severity:
                query = query.filter(AnomalyRow.severity == severity)
            if agent:
                query = query.filter(AnomalyRow.agent_id == agent)
            rows = query.order_by(AnomalyRow.agent_id, AnomalyRow.fingerprint).all()
        return templates.TemplateResponse(
            request, "anomalies.html", {"anomalies": rows, "severity": severity, "agent": agent}
        )

    @app.get("/cycles/{cycle_id}/artifacts/{name}")
    def artifact(cycle_id: str, name: str):
        with database.session() as session:
            cycle = session.get(CycleRow, cycle_id)
        if cycle is None:
            raise HTTPException(404, "unknown cycle")
        relative = Path(cycle.agent_id) / cycle_id / name
        if not store.exists(relative):
            raise HTTPException(404, "unknown artifact")
        return FileResponse(store.root / relative)

    # -- json api ------------------------------------------------------------
    @app.get("/health")
    def health():
        return {"status": "ok", "service": "driftlab"}

    @app.get("/api/estate")
    def api_estate():
        with database.session() as session:
            agents = session.query(AgentRow).all()
            latest = latest_cycles(session)
        return JSONResponse(
            [
                {
                    "agent_id": a.id,
                    "name": a.name,
                    "priority": a.priority,
                    "last_checked_at": a.last_checked_at.isoformat() if a.last_checked_at else None,
                    "compliance_score": latest[a.id].compliance_score if a.id in latest else None,
                    "latest_cycle": latest[a.id].cycle_id if a.id in latest else None,
                }
                for a in sorted(agents, key=lambda a: a.id)
            ]
        )

    @app.get("/api/cycles/{cycle_id}/ledger")
    def api_ledger(cycle_id: str):
        with database.session() as session:
            cycle = session.get(CycleRow, cycle_id)
        if cycle is None:
            raise HTTPException(404, "unknown cycle")
        return JSONResponse(store.read_json(Path(cycle.agent_id) / cycle_id / "ledger.json"))

    return app
