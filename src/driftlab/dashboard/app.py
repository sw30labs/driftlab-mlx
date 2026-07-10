"""FastAPI dashboard — estate + per-agent compliance views.

Renders air-gapped (inline CSS, no CDN). Reads cycle results from the store and
serves a summary list plus a per-agent detail page. No external network calls.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..config import get_settings
from ..store import CycleRecord, AgentRecord, init_db, latest_cycle
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from ..store import _engine

_TEMPLATES = Path(__file__).resolve().parent / "templates"

app = FastAPI(title="DriftLab", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(_TEMPLATES))


def _session() -> Session:
    init_db()
    return Session(_engine())


def _agents() -> list[AgentRecord]:
    with _session() as s:
        rows = s.execute(select(AgentRecord)).scalars().all()
        return list(rows)


def _latest(agent: str) -> CycleRecord | None:
    with _session() as s:
        row = s.execute(
            select(CycleRecord).where(CycleRecord.agent == agent)
            .order_by(CycleRecord.created_at.desc())
        ).first()
        return row[0] if row else None


def _score_color(score: int) -> str:
    if score >= 90:
        return "#1a7f37"
    if score >= 60:
        return "#bf8700"
    return "#cf222e"


@app.get("/", response_class=HTMLResponse)
def estate(request: Request):
    agents = _agents()
    rows = []
    for a in agents:
        c = _latest(a.id)
        rows.append({
            "id": a.id, "name": a.name, "priority": a.priority, "owner": a.owner,
            "score": c.score if c else None,
            "cycle_id": c.id if c else None,
            "last": a.last_cycle,
        })
    return HTMLResponse(templates.get_template("estate.html").render(
        request=request, agents=rows, color=_score_color))


@app.get("/agent/{agent_id}", response_class=HTMLResponse)
def agent_detail(request: Request, agent_id: str):
    c = _latest(agent_id)
    if not c:
        raise HTTPException(status_code=404, detail="no cycle yet")
    import json
    ledger = json.loads(c.ledger)
    return HTMLResponse(templates.get_template("agent.html").render(
        request=request, agent=agent_id, ledger=ledger,
        color=_score_color, score=c.score))