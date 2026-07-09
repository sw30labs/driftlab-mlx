"""Time helpers. Naive-UTC everywhere internally (regitel convention) —
mixing aware and naive datetimes in comparisons raises, so we pick one."""

from __future__ import annotations

from datetime import datetime, timezone


def naive_utcnow() -> datetime:
    """UTC now without tzinfo — safe to compare with DB-stored datetimes."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
