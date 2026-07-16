# ADR-001 — Resource budgets as a certified control (DL-8)

**Status:** Accepted · 2026-07-15 · branch `feat/dl8-resource-budget`

---

## Context

DriftLab already certifies and audits an *autonomy* budget (DL-6): a ceiling
bound in the OSCAL baseline, a deterministic meter over observed events, a
finding when the meter exceeds the ceiling. The estates DriftLab watches are
increasingly deepagents driven in ralph loops against a local OMLX inference
server — workloads whose runaway mode is *cumulative* (iterations, tokens,
wall-clock) rather than instantaneous CPU. The question this ADR answers:
where does resource-budget monitoring live — in every agentic app, or in
DriftLab?

## Decision

Resource budgets become **DL-8 "Resource Budget"**, a sibling of DL-6 — a
certified control, **not** an APM feature. The work splits into four layers,
and only two of them are DriftLab code:

| Layer | What | Where | Mechanism |
|---|---|---|---|
| **Certify** | Ceilings per agent: `cpu_seconds`, `tokens`, `iterations`, `wall_seconds` | OSCAL baseline (`dl:` vocabulary) | Fail-closed compile into `BaselinePolicy.resource_ceilings` |
| **Enforce** | The hard cap | Platform, never Python | cgroup v2 `cpu.max` via systemd slice (Linux deploys); OMLX gateway token quotas per agent identity |
| **Adapt** | Metering + circuit breaker + (later) fidelity shedding | `driftlab.sensor` — one thin import in each app | Stdlib meter (`os.times`), cumulative multi-currency ledger, `BudgetExceeded` breaker |
| **Audit** | Did the agent honor its certified budget? Did the certified degradation protocol execute? | DriftLab diff engine | DL-8 ledger-vs-ceiling check; DL-4-style pressure→shedding protocol check |

Apps carry ~2 lines:

```python
sensor = Sensor(agent="loan-officer", ceilings={"iterations": 50, "tokens": 200_000})
for task in work_queue:
    with sensor.iteration():   # meters CPU + wall, counts the iteration,
        ...                    # raises BudgetExceeded once a ceiling is spent
```

## The two-planes rule

**Compliance events are lossless; resource telemetry is a separate, lossy-permitted plane.**

Resource records are written to their own JSONL stream
(`<data_dir>/resource/<agent>.jsonl`), never into a decision-trace file, because:

1. The normalizer fails closed — an unknown `kind` aborts replay
   (`ingest.normalize_record`), by design. Resource records in a trace file
   would break ingestion of the evidence around them.
2. `DecisionEvent.is_autonomous` counts every non-HITL/refusal/escalation
   event; resource samples in the decision stream would silently inflate the
   DL-6 autonomy rate.
3. The determinism principle ("byte-identical artifacts on re-run") is
   load-bearing for the compliance path. Resource telemetry is inherently
   wall-clock-bearing; it therefore never enters cycle artifacts. The DL-8
   *audit* is still deterministic: replaying the same recorded resource
   stream against the same baseline yields identical findings.

DL-1..7 inputs are never sampled — a single off-allowlist event is the whole
point. Resource telemetry may be downsampled/sketched later without touching
the compliance plane.

## Why co-location in DriftLab is correct

Fidelity shedding **confounds behavioral drift**: an agent that downgrades
its model or skips subagents under resource pressure changes its tool-call
and routing patterns, firing DL-1/2/7 findings that look like compliance
drift. The sensor therefore reports its fidelity level in every resource
record (and, in phase 4, emits `fidelity_shed` transitions as decision
events) so findings can be annotated with the fidelity state active at the
time. Separating budget monitoring from drift monitoring would make certified
degradation indistinguishable from real drift.

## Semantics

* A ceiling is **exhausted once `spent >= ceiling`** — a budget of 50
  iterations admits exactly 50. The breaker gates at *iteration entry*; the
  blocked attempt still emits a final record naming the tripped currency
  (the stream must show why the loop stopped).
* CPU/wall accrue across the sensor's lifetime, sliced at iteration
  boundaries — a loop that is cheap per tick but runs all day still trips.
* Per-process CPU (`os.times`, self + reaped children) cannot see burn inside
  the OMLX server. Tokens are the currency that captures inference cost;
  gateway-side attribution is the phase-3 metering point for it.

## Platform notes

* cgroup v2 `cpu.max` (backstop) and PSI `cpu.pressure` (shedding signal) are
  **Linux-only**. Templates land in `ops/` for deploys; macOS dev boxes run
  the sensor observe-only. The sensor itself is pure POSIX stdlib.
* The sensor is metered discipline for the monitor too: no LLM anywhere in
  the sampling path; sensor overhead must stay negligible (open-per-write
  append, no background threads).

## Packaging

`driftlab.sensor` lives in-tree for now but must not import
FastAPI/SQLAlchemy/LangGraph/NetworkX (guarded by a test). When the first
external app consumes it, it graduates to a standalone dependency-light
`driftlab-sensor` wheel.

## Phasing

1. **(this branch)** Multi-currency ledger + observe-only sensor + JSONL
   resource stream + tests. macOS-friendly, zero new dependencies.
2. DL-8 in the baseline compiler (fail-closed `resource_ceilings`) + diff
   engine check over replayed resource streams; fidelity annotation on
   existing findings. Dogfood: meter DriftLab's own `experiment/loop.py`.
3. OMLX gateway quota middleware (per-agent token attribution) + cgroup
   slice templates in `ops/`.
4. Fidelity-shedding ladder (PSI-driven on Linux) + `fidelity_shed` decision
   events + DL-4-style verification that the certified protocol executed.

## Non-goals

* No CPU dashboards, fleet heatmaps, or general APM — that lane is
  Datadog/LangSmith. DriftLab answers a binary, evidence-backed question and
  emits OSCAL.
* No enforcement in Python — the kernel and the gateway enforce; the sensor
  adapts; DriftLab proves.
* No fleet/edge aggregation until the estate actually spans hosts
  (local-first stands).
