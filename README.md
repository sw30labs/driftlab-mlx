# DriftLab

**Continuous, machine-readable compliance observer for running agentic systems.**

DriftLab watches a live agent's *actual decision traces* — tool calls, routing
choices, escalations, refusals — and diffs observed behavior against a
**certified OSCAL baseline**. When observed behavior deviates, DriftLab doesn't
just alert: it runs a **micro-experiment** that *proves* or *refutes* the
suspected drift with controlled evidence, then emits OSCAL + human-readable
artifacts suitable for SOC 2 / EU AI Act / ISO 42001 evidence.

It is **local-first, private, deterministic in its compliance path, and works
without any LLM**.

---

## Why it exists

Current AI governance is design-time (canvases, policy docs, one-shot audits)
or static (graph diff at build time). Nobody continuously observes *what an
agent actually does at runtime* and proves behavioral drift against a
machine-readable compliance baseline. DriftLab is the missing "control monitor"
layer for the agentic economy.

---

## Design principles (non-negotiable)

1. **Deterministic compliance path.** The diff, anomaly, and scoring engines are
   pure deterministic Python (Pydantic + a small NetworkX path analysis). The LLM
   is *advisory only* — it may write narratives; it never decides a severity or
   verdict. A `CRITICAL` fires because the diff engine found a structural
   deviation on a critical-sink node, not because a model "thought" something
   looked wrong.
2. **Local-first / private.** Everything runs on your machine. No agent traces
   leave the host. The LLM (OMLX or any OpenAI-compatible endpoint you control)
   is optional.
3. **Provenance is load-bearing.** Every anomaly traces to source trace events +
   a baseline control. Every experiment verdict cites the probe evidence.
4. **Idempotent by construction.** Re-running a cycle on the same inputs yields
   byte-identical artifacts (content-derived UUIDs / hashing).
5. **Bounded autonomy for the proof engine.** The micro-experiment loop probes
   only a *replay* of the agent's trace held in memory. It never calls the live
   system or any network endpoint. Isolation is enforced and tested.

---

## Quickstart

One command from a fresh checkout — creates the venv, installs, runs the test
suite, seeds a first estate cycle, and opens the command deck:

```bash
./setup_and_run.sh                     # use a local OMLX server if one is up
./setup_and_run.sh --provider none     # deterministic path only, no narratives
./setup_and_run.sh --help              # flags and environment overrides
```

It detects OMLX by asking the endpoint what it serves and pins the first chat
model it offers, skipping speech and embedding models. No server running is not
an error: narratives switch off and every compliance feature still works.

Or step by step:

```bash
cd /Users/spider/Desktop/driftlabv2
uv venv --python 3.13
uv pip install .                 # installs the wheel (non-editable; see NOTES)
uv run driftlab demo             # full E2E on the bundled seed estate
```

Expected output:

```
DriftLab demo — full estate cycle
  loan-officer: score 0/100       <- 5 drift families detected + proven
  support-triage: score 100/100   <- clean
```

Run a single agent now:

```bash
uv run driftlab check --agent loan-officer
uv run driftlab monitor run --force      # staleness-weighted estate cycle
uv run driftlab serve --port 8321        # web command deck at http://127.0.0.1:8321
```

The command deck is a single-page operations console: estate posture, the
anomaly ledger, the DL-1..8 control family, proof-engine verdicts, DL-8
resource budgets, OSCAL evidence, and a run button that drives a cycle live.
It is stdlib-only (no server framework, no CDN, no build step), binds loopback,
and refuses non-loopback API clients — compliance evidence never leaves the host.

---

## CLI reference

| Command | Purpose |
|---|---|
| `driftlab agents` | Show the monitored estate + staleness priorities |
| `driftlab check --agent NAME` | One compliance cycle, now (with experiments) |
| `driftlab check --agent NAME --no-experiments` | Diff + anomalies only, skip the proof loop |
| `driftlab monitor run [--force] [--no-email]` | Staleness-weighted estate cycle over the registry |
| `driftlab monitor --status` | Recent runs from the store |
| `driftlab report <cycle_id>` | Print a cycle's markdown report |
| `driftlab serve [--host --port --no-browser --view]` | Serve the web command deck (air-gapped, loopback-only, no CDN) |
| `driftlab demo` | Full E2E on the bundled seed estate |

---

## Architecture

```
Agent runtime (LangGraph/LangChain/any)
   │  emits decision traces (tool calls, routing, escalations, refusals)
   │  + resource telemetry via driftlab.sensor (separate stream; ADR-001)
   ▼
[Trace Ingestor] ──► [Trace Normalizer] ──► canonical DecisionEvent model
[Resource Stream Loader] ──► ResourceRecord replay (DL-8 telemetry plane)
[OSCAL Baseline Loader] ──► [Baseline Compiler] ──► canonical Control model (DL-1..8)
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
    [Behavioral Diff] (observed vs baseline)  [Anomaly Engine] (severity, waivers, score)
              │                               │
              ├──────────────► [Compliance Score + Anomaly Ledger]
              │
    [Drift Hypothesis Generator] ──► [Micro-Experiment Loop]
    (suspected drift → probe)         (LangGraph: design→execute→evaluate→reflect)
              │
              ├─► [OSCAL Evidence Emitter]  (assessment-plan / assessment-results)
              ├─► [Web Command Deck]        (estate, ledger, controls, proofs, evidence)
              └─► [Monitor / Scheduler]     (staleness-weighted; cron/launchd)
```

### Module layout

```
driftlab/
├── src/driftlab/
│   ├── domain/        canonical DecisionEvent + BaselinePolicy models
│   ├── identity.py    content-derived, deterministic ids + digests
│   ├── ingest/        normalizer (fail-closed), JSONL replay, LangGraph hook
│   ├── sensor/        resource-budget ledger + meter + telemetry stream (ADR-001)
│   ├── baseline/      OSCAL profile loader + fail-closed compiler (DL-1..8)
│   ├── diff/          behavioral diff engine (7 deterministic control checks)
│   ├── anomaly/       severity resolution, waivers, scoring, DL-5 escalation
│   ├── experiment/    hypothesis generator + sandboxed replay + loop (LangGraph)
│   ├── cycle.py       one full compliance cycle (ties the above together)
│   ├── emit/          OSCAL 1.1.2-shaped plan/results + markdown report
│   ├── store/         SQLAlchemy + SQLite (local, idempotent upsert)
│   ├── monitor/       staleness-weighted policy + runner + SMTP notifier
│   ├── web/           command deck: stdlib HTTP server, job runner, SPA (air-gapped)
│   ├── llm.py         optional OMLX client (non-streaming, stdlib), advisory-only
│   └── cli.py         Typer + Rich CLI
├── seed/              baselines, agents.yaml, recorded traces
├── ops/               launchd plist + crontab templates
├── tests/             63 tests (unit, integration, determinism, sandbox-safety, LLM-optional, sensor + DL-8, deck)
└── docs/              RUNBOOK, CERTIFICATION-GUIDE, PITCH, deck, ROADMAP
```

---

## The eight behavioral controls (DL-1..8)

| ID | Control | NIST 800-53 | What it checks |
|---|---|---|---|
| DL-1 | Decision Rights | AC-3 / CM-6 | Every tool call is on the node's certified allowlist |
| DL-2 | Routing Integrity | CM-6 | Every transition is on the certified route allowlist |
| DL-3 | Human Oversight | AC-6(1) / PM-12 | Conditions requiring human-in-the-loop actually route there |
| DL-4 | Fallback Protocol | SI-13 / CP-2 | Error/exception events trigger the certified recovery |
| DL-5 | Critical Sink | AC-6 / SC-2 | Findings reaching irreversible actions are escalated to CRITICAL |
| DL-6 | Autonomy Budget | AC-5 / PM-12 | Autonomous disposition rate stays under the certified ceiling |
| DL-7 | Required Steps | CM-6 | Mandatory process steps (e.g. intake→assess) are present |
| DL-8 | Resource Budget | SC-6 / CA-7 | Cumulative resource spend (tokens, iterations, CPU, wall) stays under certified ceilings |

All eight are evaluated **deterministically**; none depend on an LLM. DL-8
audits the sensor's recorded telemetry stream (see `docs/ADR-001-RESOURCE-BUDGET.md`);
certified ceilings with no observed telemetry fail closed as a finding.

---

## Testing

```bash
uv run pytest
```

Targets: unit (normalizer fail-closed, baseline fail-closed), integration
(mocked-free, synthetic fixtures), **determinism** (byte-identical ledger on
re-run), **sandbox safety** (experiment loop runs with sockets booby-trapped —
any outbound call fails the test), and **LLM-optional** (full compliance run
succeeds with no OMLX reachable). Target: a green suite before any "done" claim.

---

## Configuration

All keys are environment variables prefixed `DRIFTLAB_`:

| Variable | Default | Purpose |
|---|---|---|
| `DRIFTLAB_DATA_DIR` | `~/.driftlab` | SQLite DB + artifacts root |
| `DRIFTLAB_REGISTRY` | `seed/agents.yaml` | monitored agent registry |
| `DRIFTLAB_LLM_PROVIDER` | `none` | `none` disables the LLM entirely; `omlx` (alias `mlx`) enables advisory narratives |
| `DRIFTLAB_OMLX_BASE_URL` | `http://127.0.0.1:8000/v1` | local inference server |
| `DRIFTLAB_OMLX_API_KEY` | `test` | falls back to `OMLX_API_KEY` when unset |
| `DRIFTLAB_OMLX_MODEL` | `DeepSeek-V4-Flash-0731-MLX` | model id the endpoint serves |
| `DRIFTLAB_OMLX_TIMEOUT` | `180` | seconds; large MLX models narrate slowly |
| `DRIFTLAB_ALLOW_REMOTE_LLM` | `false` | required to accept a non-loopback LLM endpoint |
| `DRIFTLAB_EMAIL__ENABLED` | `false` | enable SMTP digest |

### Advisory LLM (OMLX)

The compliance path never calls a model. When `DRIFTLAB_LLM_PROVIDER=omlx`, the
deck can additionally ask a local OMLX server to *narrate* a finished cycle —
the same backend contract as the sibling projects on this workstation: an
OpenAI-compatible endpoint on `127.0.0.1:8000/v1`, an explicit model id, and
never streaming (streaming hangs OMLX on large models). The client is stdlib
`urllib`, so enabling it installs nothing. A narrative is never persisted into
a ledger and can never change a score, a severity, or a verdict; if the
endpoint is down the deck says so and everything else keeps working.

---

## License

Apache-2.0. See `LICENSE`.