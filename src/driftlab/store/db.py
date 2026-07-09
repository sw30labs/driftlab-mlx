"""SQLite persistence — SQLAlchemy 2.0 typed models (glass-graph/regitel pattern).

No migrations: ``create_all`` on init (local-first, single-user). Cycle rows
carry a unique ``idempotency_key`` = agent:baseline_hash:trace_hash, so
re-running the same cycle upserts instead of duplicating (merge semantics).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class AgentRow(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, default="")
    priority: Mapped[int] = mapped_column(Integer, default=5)
    baseline_path: Mapped[str] = mapped_column(String, default="")
    traces_path: Mapped[str] = mapped_column(String, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="active")  # active | paused
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CycleRow(Base):
    __tablename__ = "cycles"

    cycle_id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True, index=True)
    agent_id: Mapped[str] = mapped_column(String, index=True)
    baseline_id: Mapped[str] = mapped_column(String, default="")
    baseline_hash: Mapped[str] = mapped_column(String, default="")
    trace_hash: Mapped[str] = mapped_column(String, default="")
    compliance_score: Mapped[float] = mapped_column(Float, default=100.0)
    severity_counts: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    runs_observed: Mapped[int] = mapped_column(Integer, default=0)
    events_observed: Mapped[int] = mapped_column(Integer, default=0)
    anomaly_count: Mapped[int] = mapped_column(Integer, default=0)
    experiment_count: Mapped[int] = mapped_column(Integer, default=0)
    confirmed_drifts: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="completed")  # completed | failed
    trigger: Mapped[str] = mapped_column(String, default="manual")  # manual | scheduled
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AnomalyRow(Base):
    __tablename__ = "anomalies"

    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    anomaly_id: Mapped[str] = mapped_column(String, index=True)  # deterministic uuid5(fingerprint)
    cycle_id: Mapped[str] = mapped_column(String, index=True)
    agent_id: Mapped[str] = mapped_column(String, index=True)
    fingerprint: Mapped[str] = mapped_column(String, index=True)
    control_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String, index=True)
    severity: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    waiver_status: Mapped[str] = mapped_column(String, default="none")
    payload: Mapped[str] = mapped_column(Text, default="{}")  # full AnomalyRecord JSON


class ExperimentRow(Base):
    __tablename__ = "experiments"

    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(String, index=True)
    cycle_id: Mapped[str] = mapped_column(String, index=True)
    agent_id: Mapped[str] = mapped_column(String, index=True)
    anomaly_fingerprint: Mapped[str] = mapped_column(String, index=True)
    verdict: Mapped[str] = mapped_column(String, index=True)
    validity_score: Mapped[float] = mapped_column(Float, default=0.0)
    iterations: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[str] = mapped_column(Text, default="{}")  # full ExperimentRecord JSON


class MonitorRunRow(Base):
    __tablename__ = "monitor_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    agents_scanned: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    trigger: Mapped[str] = mapped_column(String, default="manual")
    cycles_run: Mapped[int] = mapped_column(Integer, default=0)
    new_critical: Mapped[int] = mapped_column(Integer, default=0)
    confirmed_drifts: Mapped[int] = mapped_column(Integer, default=0)
    email_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String, default="running")  # running | completed | failed
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)


class Database:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.db_path}", echo=False)
        self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self):
        session: Session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
