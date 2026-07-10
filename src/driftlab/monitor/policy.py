"""Staleness-weighted monitor policy.

Each agent carries a priority (1-7). Higher priority is checked more often.
The schedule maps priority -> maximum hours between checks:

    priority 7 -> 6h, 6 -> 12h, 5 -> 24h, 4 -> 48h, 3 -> 96h, 2 -> 168h, 1 -> 336h

A monitor cycle only runs agents whose last check has aged past their interval
(unless forced). This is the regitel-style staleness weighting, deterministic
and free of external schedulers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

_PRIORITY_INTERVAL_HOURS = {7: 6, 6: 12, 5: 24, 4: 48, 3: 96, 2: 168, 1: 336}


@dataclass
class StalenessPolicy:
    def interval_hours(self, priority: int) -> int:
        return _PRIORITY_INTERVAL_HOURS.get(priority, 48)

    def is_due(self, priority: int, last_checked_at: str | None, now: datetime | None = None) -> bool:
        if last_checked_at is None:
            return True
        now = now or datetime.now(timezone.utc)
        last = datetime.fromisoformat(last_checked_at.replace("Z", "+00:00"))
        age_h = (now - last).total_seconds() / 3600.0
        return age_h >= self.interval_hours(priority)