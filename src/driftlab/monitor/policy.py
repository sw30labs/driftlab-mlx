"""Staleness-weighted scheduling — regitel monitor/policy.py, ported.

due  <=>  now - last_checked_at > interval(priority)
order:    (priority ASC, days_overdue DESC); never-checked sorts first
cap:      max_count guards the cycle budget.
Naive-UTC datetimes throughout (regitel convention — don't mix aware/naive).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from driftlab.clock import naive_utcnow
from driftlab.store.db import AgentRow, Database

NEVER_CHECKED = float("inf")


@dataclass
class DueAgent:
    id: str
    name: str
    priority: int
    last_checked_at: Optional[datetime]
    interval_days: int
    days_since_check: float
    days_overdue: float


def get_interval_days(priority: int, intervals: dict[int, int], default_interval: int) -> int:
    return intervals.get(priority, default_interval)


def evaluate_agent(row: AgentRow, intervals: dict[int, int], default_interval: int, now: datetime) -> DueAgent:
    priority = row.priority or 5
    interval = get_interval_days(priority, intervals, default_interval)
    if row.last_checked_at is None:
        since = NEVER_CHECKED
        overdue = NEVER_CHECKED
    else:
        since = (now - row.last_checked_at).total_seconds() / 86400.0
        overdue = since - interval
    return DueAgent(
        id=row.id,
        name=row.name,
        priority=priority,
        last_checked_at=row.last_checked_at,
        interval_days=interval,
        days_since_check=since,
        days_overdue=overdue,
    )


def select_due_agents(
    database: Database,
    intervals: dict[int, int],
    default_interval: int,
    *,
    max_count: int | None = None,
    now: datetime | None = None,
    include_all: bool = False,
) -> list[DueAgent]:
    now = now or naive_utcnow()
    with database.session() as session:
        rows = session.query(AgentRow).filter(AgentRow.status == "active").all()
    evaluated = [evaluate_agent(row, intervals, default_interval, now) for row in rows]
    if not include_all:
        evaluated = [e for e in evaluated if e.days_overdue > 0]
    evaluated.sort(key=lambda e: (e.priority, -e.days_overdue))
    if max_count is not None and max_count > 0:
        evaluated = evaluated[:max_count]
    return evaluated
