"""Lightweight SQLite persistence (local, no external DB).

Stores agent registry, cycle results, and run history. Content-derived ids make
writes idempotent — re-running a cycle upserts rather than duplicates.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Column, Float, Integer, String, Text, create_engine, select
)
from sqlalchemy.orm import Session, declarative_base

from ..config import get_settings

Base = declarative_base()


class CycleRecord(Base):
    __tablename__ = "cycles"
    id = Column(String, primary_key=True)            # cycle_id (content-derived)
    agent = Column(String, index=True)
    baseline_hash = Column(String)
    trace_hash = Column(String)
    score = Column(Integer)
    ledger = Column(Text)                            # JSON ledger
    created_at = Column(String)


class AgentRecord(Base):
    __tablename__ = "agents"
    id = Column(String, primary_key=True)
    name = Column(String)
    baseline = Column(String)
    trace = Column(String)
    priority = Column(Integer)
    owner = Column(String)
    last_cycle = Column(String, nullable=True)


def _engine():
    return create_engine(f"sqlite:///{get_settings().db_path}")


def init_db() -> None:
    get_settings().ensure_dirs()
    Base.metadata.create_all(_engine())


def upsert_cycle(rec: CycleRecord) -> None:
    with Session(_engine()) as s:
        existing = s.get(CycleRecord, rec.id)
        if existing:
            existing.score = rec.score
            existing.ledger = rec.ledger
            existing.created_at = rec.created_at
        else:
            s.add(rec)
        s.commit()


def latest_cycle(agent: str) -> CycleRecord | None:
    with Session(_engine()) as s:
        row = s.execute(
            select(CycleRecord).where(CycleRecord.agent == agent)
            .order_by(CycleRecord.created_at.desc())
        ).first()
        return row[0] if row else None


def record_agent_run(agent_id: str) -> None:
    with Session(_engine()) as s:
        rec = s.get(AgentRecord, agent_id)
        if rec:
            rec.last_cycle = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            s.commit()