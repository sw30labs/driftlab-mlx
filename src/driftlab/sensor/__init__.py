"""Resource-budget sensor — the "adapt" layer of ADR-001 (DL-8).

A dependency-light, observe-only meter that any agentic app (or DriftLab's
own experiment loop) wraps around its work loop:

    sensor = Sensor(agent="loan-officer",
                    ceilings={"iterations": 50, "tokens": 200_000})
    for task in work_queue:
        with sensor.iteration():      # meters CPU + wall, counts the iteration
            ...                       # raises BudgetExceeded once a ceiling is spent
        sensor.charge_tokens(usage)   # from the app's LLM usage callback

Design constraints (see ``docs/ADR-001-RESOURCE-BUDGET.md``):

* **Separate plane.** Resource records are telemetry, not compliance
  evidence. They go to their own JSONL stream — never into a decision-trace
  file, where the fail-closed normalizer would reject them and where they
  would inflate the DL-6 autonomy rate.
* **Stdlib metering.** CPU via ``os.times()`` (self + reaped children), wall
  via a monotonic clock. Works on macOS and Linux; no psutil, no cgroups.
  Kernel enforcement (cgroup v2) is a deployment concern, not Python's.
* **Import-light.** This module must not pull FastAPI/SQLAlchemy/LangGraph —
  it is destined to graduate into a standalone ``driftlab-sensor`` wheel.
  Guarded by ``tests/test_sensor.py``.
* **Non-deterministic by nature.** Timestamps and CPU deltas vary run to
  run; resource records therefore never enter byte-identical cycle
  artifacts. The DL-8 *audit* over a recorded stream stays deterministic.
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from pydantic import BaseModel, Field

from ..identity import event_id


class Currency(str, Enum):
    """Budget currencies the ledger meters.

    Ralph-loop runaway shows up in ITERATIONS/TOKENS long before
    instantaneous CPU looks alarming, so all four accrue together and any
    one of them may trip the breaker.
    """

    CPU_SECONDS = "cpu_seconds"
    WALL_SECONDS = "wall_seconds"
    TOKENS = "tokens"
    ITERATIONS = "iterations"


class BudgetExceeded(RuntimeError):
    """Circuit breaker: a certified ceiling is spent. Carries the evidence."""

    def __init__(self, currency: Currency, spent: float, ceiling: float) -> None:
        self.currency = currency
        self.spent = spent
        self.ceiling = ceiling
        super().__init__(
            f"budget exceeded: {currency.value} spent {spent:g} >= ceiling {ceiling:g}"
        )


def _as_currency(value: Currency | str) -> Currency:
    try:
        return Currency(value)
    except ValueError as exc:
        known = ", ".join(c.value for c in Currency)
        raise ValueError(f"unknown budget currency {value!r}; known: {known}") from exc


# -- ledger ---------------------------------------------------------------


class BudgetLedger:
    """Cumulative, multi-currency spend ledger with a hard-stop gate.

    A ceiling is *exhausted* once ``spent >= ceiling`` — a budget of 50
    iterations admits exactly 50. ``checkpoint()`` is the circuit breaker:
    call it before starting new work. Charges are monotone and thread-safe.
    """

    def __init__(self, ceilings: Mapping[Currency | str, float] | None = None) -> None:
        self._ceilings: dict[Currency, float] = {}
        for cur, ceiling in (ceilings or {}).items():
            c = _as_currency(cur)
            if not ceiling > 0:  # fail closed on unusable ceilings
                raise ValueError(f"ceiling for {c.value} must be > 0, got {ceiling!r}")
            self._ceilings[c] = float(ceiling)
        self._spent: dict[Currency, float] = {c: 0.0 for c in Currency}
        self._lock = threading.Lock()

    def charge(self, currency: Currency | str, amount: float) -> float:
        """Add ``amount`` to a currency's cumulative spend; returns the new total."""
        c = _as_currency(currency)
        if amount < 0:
            raise ValueError(f"charge amount must be >= 0, got {amount!r}")
        with self._lock:
            self._spent[c] += float(amount)
            return self._spent[c]

    def spent(self, currency: Currency | str) -> float:
        return self._spent[_as_currency(currency)]

    def remaining(self, currency: Currency | str) -> float | None:
        """Headroom before the ceiling; ``None`` when uncapped."""
        c = _as_currency(currency)
        ceiling = self._ceilings.get(c)
        if ceiling is None:
            return None
        return max(0.0, ceiling - self._spent[c])

    def tripped(self) -> Currency | None:
        """First exhausted currency in canonical order, or ``None``."""
        for c in Currency:
            ceiling = self._ceilings.get(c)
            if ceiling is not None and self._spent[c] >= ceiling:
                return c
        return None

    def checkpoint(self) -> None:
        """Raise :class:`BudgetExceeded` if any ceiling is exhausted."""
        c = self.tripped()
        if c is not None:
            raise BudgetExceeded(c, self._spent[c], self._ceilings[c])

    def snapshot(self) -> dict[str, Any]:
        """Deterministically ordered dump for records and reports."""
        tripped = self.tripped()
        return {
            "spent": {c.value: self._spent[c] for c in Currency},
            "ceilings": {
                c.value: v
                for c, v in sorted(self._ceilings.items(), key=lambda kv: kv[0].value)
            },
            "tripped": tripped.value if tripped else None,
        }


# -- metering -------------------------------------------------------------


class ProcessMeter:
    """Own-process CPU (user + system, self + reaped children) and wall deltas.

    ``os.times()`` is POSIX stdlib and includes children the process has
    already waited on, so subprocess tool calls are counted once they finish.
    In-flight children and out-of-process burn (e.g. a local inference
    server) are invisible here — tokens capture inference cost, and the
    gateway/cgroup layers own attribution and enforcement (ADR-001).
    """

    def __init__(self, wall_clock: Callable[[], float] = time.monotonic) -> None:
        self._wall_clock = wall_clock
        self._last_cpu = self._cpu_now()
        self._last_wall = wall_clock()

    @staticmethod
    def _cpu_now() -> float:
        t = os.times()
        return t.user + t.system + t.children_user + t.children_system

    def delta(self) -> tuple[float, float]:
        """``(cpu_seconds, wall_seconds)`` consumed since the previous call."""
        cpu, wall = self._cpu_now(), self._wall_clock()
        out = (max(0.0, cpu - self._last_cpu), max(0.0, wall - self._last_wall))
        self._last_cpu, self._last_wall = cpu, wall
        return out


# -- telemetry stream -----------------------------------------------------


class ResourceRecord(BaseModel):
    """One telemetry sample: cumulative ledger state at a point in time.

    Telemetry plane only — never ingested as a :class:`DecisionEvent` and
    never part of byte-identical cycle artifacts. ``id`` is content-derived
    so replayed streams dedup exactly like decision traces.
    """

    agent: str
    seq: int
    ts: float  # epoch seconds; telemetry is explicitly wall-clock-bearing
    spent: dict[str, float]
    ceilings: dict[str, float] = Field(default_factory=dict)
    tripped: str | None = None
    fidelity: str = "full"  # the phase-4 shedding ladder reports its level here
    payload: dict[str, Any] = Field(default_factory=dict)
    id: str = ""

    def model_post_init(self, _info: Any) -> None:
        if not self.id:
            content = json.dumps(
                {"ts": self.ts, "spent": self.spent, "tripped": self.tripped},
                sort_keys=True,
            )
            self.id = event_id(self.agent, self.seq, "resource", self.fidelity, content)


class ResourceStreamWriter:
    """Append-only JSONL sink, opened per write (crash-safe, no handle to leak)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: ResourceRecord) -> None:
        line = json.dumps(record.model_dump(mode="json"), sort_keys=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def cumulative_spend(records: list[ResourceRecord]) -> dict[str, float]:
    """Final cumulative spend per currency over a recorded stream.

    Uses max, not last — cumulative spend is monotone, so this is robust to
    out-of-order or truncated streams.
    """
    final: dict[str, float] = {}
    for r in records:
        for cur, amt in r.spent.items():
            a = float(amt)
            if a > final.get(cur, 0.0):
                final[cur] = a
    return final


def load_resource_jsonl(path: str | Path) -> list[ResourceRecord]:
    """Replay a recorded resource stream (the phase-2 DL-8 audit input)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"resource stream not found: {p}")
    records: list[ResourceRecord] = []
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(ResourceRecord.model_validate(json.loads(line)))
    return records


# -- facade ---------------------------------------------------------------


class Sensor:
    """The two-line integration surface for agentic apps.

    Wrap each work-loop iteration in :meth:`iteration`; report LLM usage via
    :meth:`charge_tokens`. Observe-only in phase 1: the only intervention is
    the :class:`BudgetExceeded` breaker at iteration entry. CPU/wall accrue
    across the sensor's lifetime, sliced at iteration boundaries — a loop
    that is cheap per tick but runs all day still trips a wall ceiling.
    """

    def __init__(
        self,
        agent: str,
        ceilings: Mapping[Currency | str, float] | None = None,
        stream_path: str | Path | None = None,
        wall_clock: Callable[[], float] = time.monotonic,
        timestamp: Callable[[], float] = time.time,
    ) -> None:
        self.agent = agent
        self.ledger = BudgetLedger(ceilings)
        self._meter = ProcessMeter(wall_clock)
        self._timestamp = timestamp
        self._seq = 0
        if stream_path is None:
            from ..config import get_settings  # lazy: keeps module import light

            stream_path = get_settings().data_dir / "resource" / f"{agent}.jsonl"
        self._writer = ResourceStreamWriter(stream_path)

    @property
    def stream_path(self) -> Path:
        return self._writer.path

    def charge_tokens(self, count: float) -> float:
        return self.ledger.charge(Currency.TOKENS, count)

    def _emit(self, **payload: Any) -> ResourceRecord:
        snap = self.ledger.snapshot()
        record = ResourceRecord(
            agent=self.agent,
            seq=self._seq,
            ts=self._timestamp(),
            spent=snap["spent"],
            ceilings=snap["ceilings"],
            tripped=snap["tripped"],
            payload=payload,
        )
        self._seq += 1
        self._writer.write(record)
        return record

    @contextmanager
    def iteration(self, **payload: Any) -> Iterator[BudgetLedger]:
        """Meter one work-loop iteration; trip the breaker when a ceiling is spent.

        ``payload`` keys are merged into the emitted record for attribution
        (e.g. ``iteration(control="DL-8")``; ``event`` is reserved). A blocked
        attempt still emits a final record naming the tripped currency — the
        stream must show *why* the loop stopped — then raises. A crashing
        iteration body likewise gets its record before the exception
        propagates.
        """
        try:
            self.ledger.checkpoint()
        except BudgetExceeded as exc:
            self._emit(event="budget_exceeded", currency=exc.currency.value)
            raise
        self.ledger.charge(Currency.ITERATIONS, 1)
        try:
            yield self.ledger
        finally:
            cpu, wall = self._meter.delta()
            self.ledger.charge(Currency.CPU_SECONDS, cpu)
            self.ledger.charge(Currency.WALL_SECONDS, wall)
            self._emit(event="iteration", **payload)


__all__ = [
    "BudgetExceeded",
    "BudgetLedger",
    "Currency",
    "ProcessMeter",
    "ResourceRecord",
    "ResourceStreamWriter",
    "Sensor",
    "cumulative_spend",
    "load_resource_jsonl",
]
