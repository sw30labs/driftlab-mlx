# DriftLab Roadmap

Phased plan with milestones, owner, and definition-of-done per phase. Owner:
Nicolas Cravino (sw30labs). Vision extends to v3/v4.

---

## Phase 0 — Scaffold ✅ (done in v2.0)
- uv project, `pyproject.toml`, Typer CLI skeleton, pytest harness, config.
- Ported the deterministic diff + anomaly philosophy into a behavioral engine.
- **DoD:** project imports; CLI skeleton runs; pytest harness green on first
  unit tests.

## Phase 1 — Trace ingestion + normalization ✅
- `normalize_record` (fail-closed), JSONL replay ingestor, LangGraph callback
  hook, canonical `DecisionEvent` Pydantic model + stable hashing.
- **DoD:** malformed records raise `NormalizationError`; JSONL replay yields
  deterministic event ids; LangGraph hook captures tool/routing/HITL/refusal.

## Phase 2 — OSCAL baseline ✅
- DL-1..7 catalog, `dl:` profile vocabulary, fail-closed `BaselineCompiler`,
  two shipped baselines (loan-officer, support-triage) + registry.
- **DoD:** compiler rejects unknown props / bad budgets (`CompileError`);
  both baselines compile; `agents.yaml` drives the estate.

## Phase 3 — Behavioral diff + anomaly + score ✅
- `BehavioralDiff` (7 deterministic control checks), `AnomalyEngine`
  (severity, waivers, scoring, DL-5 escalation), compliance score 0–100.
- **DoD:** loan-officer trace → multiple active anomalies + score 0;
  support-triage → score 100, zero criticals.

## Phase 4 — Drift hypothesis + micro-experiment ✅
- `hypothesis.generate` (existence + rate claims), `ReplaySandbox`
  (read-only), LangGraph loop (design→execute→evaluate→reflect), deterministic
  verdicts.
- **DoD:** loop confirms all 4 seeded drifts on the drifted trace and refutes
  them on the clean trace; sandbox-safety test (sockets booby-trapped) passes.

## Phase 5 — OSCAL evidence + dashboard + monitor ✅
- `emit` (OSCAL 1.1.2-shaped plan/results + markdown), FastAPI dashboard
  (air-gapped inline CSS), staleness-weighted monitor (policy/runner/SMTP),
  SQLite store (idempotent).
- **DoD:** `monitor run --force` scores both agents; dashboard serves estate +
  per-agent; artifacts written per cycle.

## Phase 6 — Docs + training + pitch ✅ (this document set)
- `README.md`, `docs/RUNBOOK.md`, `docs/CERTIFICATION-GUIDE.md`, `docs/PITCH.md`,
  `docs/DECK.md`, `ROADMAP.md`, `NOTES.md`.
- **DoD:** an operator can install, certify a baseline, run a cycle, and export
  evidence from the docs alone.

---

## v0.2 — Conformance + expansion (next)
- **Strict OSCAL 1.1.2 validation** of emitted artifacts (schema-conformant
  plan/results, proper `import-ssp` / `assessment-results` structure) instead of
  the current pragmatic "OSCAL-shaped" approximation.
- **EU AI Act text → control auto-mapping**: parse regulatory text into DL
  control drafts.
- **OpenTelemetry ingestor**: tap live spans, not just JSONL replay.
- **Owner:** Nicolas Cravino. **DoD:** artifacts validate against an OSCAL 1.1.2
  schema; at least one EU AI Act article maps to a DL control automatically.

## v3 — Multi-agent estate (vision)
- **Cross-agent drift correlation**: detect drifts that only appear when agents
  interact (handoffs, shared tools).
- **Replay-diff UI**: visual diff of two cycles / two baselines in the dashboard.
- **Waiver lifecycle**: expiry enforcement surfaced in the monitor; waiver
  review queue.
- **DoD:** estate of ≥5 agents with at least one cross-agent correlation finding;
  dashboard shows replay diff.

## v4 — Regulator-ready + managed service (vision)
- **Evidence packaging**: bundle cycles into audit-ready submissions.
- **Audit-as-a-service**: managed baseline certification + reporting on top of
  the self-host core.
- **DoD:** a customer can export a complete, schema-valid evidence package for a
  SOC 2 / EU AI Act review without manual assembly.