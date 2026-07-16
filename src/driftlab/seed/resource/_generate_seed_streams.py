"""Regenerate the seed resource streams (DL-8 telemetry plane).

Run from the repo root:

    PYTHONPATH=src python src/driftlab/seed/resource/_generate_seed_streams.py

The streams are produced by the real ``driftlab.sensor`` with deterministic
clocks, so re-running yields byte-identical files (ids are content-derived).

* ``loan-officer-resource.jsonl`` — a **token-budget breach**: the certified
  ceiling is 120,000 tokens; iteration 11 overshoots to 130,450 (the breaker
  fires at the next entry, after the ceiling is already crossed). Feeds the
  DL-8 "Resource budget exceeded" drift family in the demo estate.
* ``support-triage-resource.jsonl`` — a compliant run, comfortably under its
  ceilings; support-triage stays 100/100.
"""

from __future__ import annotations

from pathlib import Path

from driftlab.sensor import BudgetExceeded, ProcessMeter, Sensor

HERE = Path(__file__).resolve().parent


class Ticker:
    """Deterministic clock: starts at ``start``, advances ``step`` per call."""

    def __init__(self, start: float, step: float) -> None:
        self.t = start
        self.step = step

    def __call__(self) -> float:
        v = self.t
        self.t += self.step
        return v


def _write(agent: str, ceilings: dict[str, float], token_charges: list[float],
           ts_start: float, wall_step: float, cpu_step: float) -> None:
    # Deterministic CPU: replace the os.times() sampler for generation only.
    ProcessMeter._cpu_now = staticmethod(Ticker(0.0, cpu_step))  # type: ignore[method-assign]
    path = HERE / f"{agent}-resource.jsonl"
    path.unlink(missing_ok=True)
    sensor = Sensor(
        agent,
        ceilings=ceilings,
        stream_path=path,
        wall_clock=Ticker(0.0, wall_step),
        timestamp=Ticker(ts_start, 45.0),
    )
    try:
        for tokens in token_charges:
            with sensor.iteration():
                sensor.charge_tokens(tokens)
    except BudgetExceeded as exc:
        print(f"{agent}: breaker fired on {exc.currency.value} "
              f"(spent {exc.spent:g} >= ceiling {exc.ceiling:g})")
    print(f"{agent}: wrote {path.name}")


def main() -> None:
    # Breach: 10 x 11,800 = 118,000 (under), then +12,450 -> 130,450 > 120,000.
    # The 12th iteration attempt is blocked and emits the budget_exceeded record.
    _write(
        "loan-officer",
        ceilings={"tokens": 120000, "iterations": 40},
        token_charges=[11800.0] * 10 + [12450.0, 9000.0],
        ts_start=1751970000.0, wall_step=2.25, cpu_step=0.4,
    )
    # Clean: 8 x 5,150 = 41,200 tokens, 8 iterations — well under 150k / 60.
    _write(
        "support-triage",
        ceilings={"tokens": 150000, "iterations": 60},
        token_charges=[5150.0] * 8,
        ts_start=1751980000.0, wall_step=1.5, cpu_step=0.25,
    )


if __name__ == "__main__":
    main()
