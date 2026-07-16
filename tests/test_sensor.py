"""Sensor tests (ADR-001 phase 1): ledger accounting + breaker semantics,
process metering, resource-stream round-trip, facade flow, and the
import-lightness guarantee that keeps `driftlab.sensor` extractable."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from driftlab.sensor import (
    BudgetExceeded,
    BudgetLedger,
    Currency,
    ProcessMeter,
    ResourceRecord,
    Sensor,
    load_resource_jsonl,
)

SRC = Path(__file__).resolve().parent.parent / "src"


class FakeClock:
    """Manually advanced monotonic clock for deterministic wall metering."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


# -- ledger ---------------------------------------------------------------


def test_ledger_charges_accumulate():
    ledger = BudgetLedger({"tokens": 100})
    assert ledger.charge("tokens", 30) == 30
    assert ledger.charge(Currency.TOKENS, 20) == 50
    assert ledger.spent("tokens") == 50
    assert ledger.remaining("tokens") == 50
    assert ledger.remaining("cpu_seconds") is None  # uncapped
    assert ledger.tripped() is None


def test_ledger_fails_closed():
    with pytest.raises(ValueError):
        BudgetLedger({"parsecs": 12})  # unknown currency
    with pytest.raises(ValueError):
        BudgetLedger({"tokens": 0})  # unusable ceiling
    ledger = BudgetLedger()
    with pytest.raises(ValueError):
        ledger.charge("tokens", -1)  # charges are monotone
    with pytest.raises(ValueError):
        ledger.charge("parsecs", 1)


def test_ledger_trips_at_ceiling_inclusive():
    ledger = BudgetLedger({"iterations": 2})
    ledger.charge("iterations", 1)
    ledger.checkpoint()  # 1 < 2: fine
    ledger.charge("iterations", 1)
    assert ledger.tripped() is Currency.ITERATIONS  # spent >= ceiling exhausts
    assert ledger.remaining("iterations") == 0.0
    with pytest.raises(BudgetExceeded) as excinfo:
        ledger.checkpoint()
    assert excinfo.value.currency is Currency.ITERATIONS
    assert excinfo.value.spent == 2
    assert excinfo.value.ceiling == 2


def test_ledger_snapshot_shape():
    ledger = BudgetLedger({"tokens": 10, "iterations": 5})
    ledger.charge("tokens", 10)
    snap = ledger.snapshot()
    assert set(snap["spent"]) == {c.value for c in Currency}
    assert snap["ceilings"] == {"iterations": 5.0, "tokens": 10.0}
    assert snap["tripped"] == "tokens"


# -- metering -------------------------------------------------------------


def test_process_meter_deltas():
    clock = FakeClock()
    meter = ProcessMeter(wall_clock=clock)
    clock.t = 2.5
    cpu, wall = meter.delta()
    assert wall == 2.5
    assert cpu >= 0.0
    cpu2, wall2 = meter.delta()
    assert wall2 == 0.0  # no wall progress between samples
    assert cpu2 >= 0.0


# -- telemetry stream -----------------------------------------------------


def test_resource_record_id_is_content_derived():
    kwargs = dict(agent="a", seq=0, ts=1.0, spent={"tokens": 5.0})
    assert ResourceRecord(**kwargs).id == ResourceRecord(**kwargs).id
    assert ResourceRecord(**kwargs).id != ResourceRecord(**{**kwargs, "ts": 2.0}).id


def test_resource_stream_round_trip(tmp_path):
    path = tmp_path / "resource.jsonl"
    sensor = Sensor("demo", stream_path=path, wall_clock=FakeClock(), timestamp=lambda: 1.0)
    with sensor.iteration():
        pass
    with sensor.iteration():
        pass
    records = load_resource_jsonl(path)
    assert [r.seq for r in records] == [0, 1]
    assert all(isinstance(r, ResourceRecord) and r.id for r in records)
    with path.open() as fh:  # one valid JSON object per line
        assert all(json.loads(line) for line in fh)


def test_load_resource_jsonl_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_resource_jsonl(tmp_path / "nope.jsonl")


# -- facade ---------------------------------------------------------------


def test_sensor_iteration_flow_and_breaker(tmp_path):
    path = tmp_path / "resource.jsonl"
    ticker = iter(range(100))
    sensor = Sensor(
        "demo",
        ceilings={"iterations": 2},
        stream_path=path,
        wall_clock=FakeClock(),
        timestamp=lambda: float(next(ticker)),
    )
    with sensor.iteration():
        pass
    sensor.charge_tokens(120)
    with sensor.iteration():
        pass
    with pytest.raises(BudgetExceeded) as excinfo:
        with sensor.iteration():
            pytest.fail("body must not run once the budget is exhausted")
    assert excinfo.value.currency is Currency.ITERATIONS

    records = load_resource_jsonl(path)
    assert len(records) == 3
    assert records[0].payload == {"event": "iteration"}
    assert records[1].spent["tokens"] == 120.0
    assert records[2].payload == {"event": "budget_exceeded", "currency": "iterations"}
    assert records[2].tripped == "iterations"


def test_sensor_wall_budget_accrues_across_iterations(tmp_path):
    clock = FakeClock()
    sensor = Sensor(
        "demo",
        ceilings={"wall_seconds": 8},
        stream_path=tmp_path / "r.jsonl",
        wall_clock=clock,
        timestamp=lambda: 0.0,
    )
    with sensor.iteration():
        clock.t += 5.0
    assert sensor.ledger.spent("wall_seconds") == 5.0
    with sensor.iteration():
        clock.t += 5.0
    with pytest.raises(BudgetExceeded) as excinfo:
        with sensor.iteration():
            pass
    assert excinfo.value.currency is Currency.WALL_SECONDS


def test_iteration_payload_attribution(tmp_path):
    path = tmp_path / "r.jsonl"
    sensor = Sensor("demo", stream_path=path, wall_clock=FakeClock(), timestamp=lambda: 0.0)
    with sensor.iteration(control="DL-8", anomaly="a1"):
        pass
    record = load_resource_jsonl(path)[0]
    assert record.payload == {"event": "iteration", "control": "DL-8", "anomaly": "a1"}


def test_sensor_records_survive_body_crash(tmp_path):
    path = tmp_path / "r.jsonl"
    sensor = Sensor("demo", stream_path=path, wall_clock=FakeClock(), timestamp=lambda: 0.0)
    with pytest.raises(RuntimeError, match="boom"):
        with sensor.iteration():
            raise RuntimeError("boom")
    records = load_resource_jsonl(path)
    assert len(records) == 1
    assert records[0].spent["iterations"] == 1.0


def test_sensor_default_stream_under_data_dir():
    sensor = Sensor("agent-x", wall_clock=FakeClock(), timestamp=lambda: 0.0)
    expected = Path(os.environ["DRIFTLAB_DATA_DIR"]) / "resource" / "agent-x.jsonl"
    assert sensor.stream_path == expected
    assert sensor.stream_path.parent.is_dir()


# -- packaging guarantee --------------------------------------------------


def test_sensor_import_stays_light():
    """`import driftlab.sensor` must not pull the heavy service deps — the
    module is destined to graduate into a standalone `driftlab-sensor` wheel
    (ADR-001 Packaging)."""
    code = (
        "import sys, json; import driftlab.sensor; "
        "roots = {m.split('.')[0] for m in sys.modules}; "
        "heavy = roots & {'fastapi', 'sqlalchemy', 'langgraph', 'uvicorn', "
        "'networkx', 'jinja2', 'typer', 'rich', 'yaml'}; "
        "print(json.dumps(sorted(heavy)))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(SRC)},
        check=True,
    )
    assert json.loads(proc.stdout) == []
