# DriftLab

**Continuous, machine-readable compliance observer for running agentic systems.**

DriftLab watches a live agent's *actual decision traces* — tool calls, routing
choices, escalations, refusals — and continuously diffs observed behavior
against a **certified OSCAL baseline**. When behavior deviates, it doesn't just
alert: it runs a **micro-experiment** against a sandboxed replay to *prove* the
drift with reproduced evidence. Output: a compliance score, a deterministic
anomaly ledger, and OSCAL 1.1.2-shaped assessment artifacts that can support
SOC 2 / EU AI Act / ISO 42001 evidence workflows.

Local-first. Deterministic in its compliance path. The LLM is optional and
advisory-only — it may write prose, never a severity or a verdict.

```
Agent runtime (LangGraph / LangChain / any)
   │  decision traces (tool calls, routing, escalations, refusals)
   ▼
[Trace Ingestor] ─► [Normalizer] ─► canonical DecisionEvent stream
                                          │
[OSCAL Baseline (catalog+profile)] ─► [Compiler] ─► executable BaselinePolicy
                                          │
                          ┌───────────────┴───────────────┐
                          ▼                               ▼
                [Behavioral Diff Engine]          [Anomaly Engine]
                (7 control checks, DL-1..7)       (severity ▸ waivers ▸ score)
                          │                               │
                          ├────────► [Compliance Score + Anomaly Ledger]
                          │
                [Hypothesis Generator] ─► [Micro-Experiment Loop]   ◄─ the differentiator
                (anomaly → testable claim)  (LangGraph: design→execute→evaluate→reflect,
                          │                  sandboxed replay, deterministic verdicts,
                          │                  optional DeepAgents advisory pass)
                          ├─► [OSCAL Evidence]  assessment-plan + assessment-results (CA-7)
                          ├─► [Dashboard]       FastAPI estate + per-agent views
                          └─► [Monitor]         staleness-weighted cron/launchd cycles
```

## Why

Existing AI governance is **design-time** (canvases, policy docs, one-shot
audits) or **static** (structural graph diff at build time). Agent
observability tools (LangSmith, Langfuse, Arize) are **telemetry** — they trace
runs but attest nothing. Nobody continuously observes what an agent *actually
does* and proves behavioral drift against a machine-readable compliance
baseline. DriftLab is that missing control-monitor layer: the runtime
counterpart glass-graph's own roadmap flags as unsolved ("how to compare
dynamic outputs consistently over time"), built as its resolution.

## Quickstart

```bash
cd driftlab
uv sync --all-extras           # or: pip install -e ".[llm,test]"

uv run driftlab demo           # full E2E on the bundled seed estate
uv run driftlab dashboard      # http://127.0.0.1:8321
uv run pytest                  # 92 tests, all offline, no LLM needed
```

The demo monitors two seed agents: `loan-officer` carries four known drifts
(a bypassed human-review gate on high-value loans, a 65% autonomy rate against
a certified 40% budget, an unvetted tool acquisition, and a skipped error
fallback) — DriftLab detects all four, scores the agent 5/100, and
**experimentally confirms each one** with reproduced probe evidence.
`support-triage` is compliant and scores 100 with zero findings (no false
positives).

## The control family (DL-1..7)

The certified baseline is an OSCAL **profile** importing the DriftLab
**catalog** (`src/driftlab/seed/baselines/driftlab-catalog.json`), which defines seven
behavioral controls, each crosswalked to SP 800-53r5:

| Control | Certifies | 800-53 anchors |
|---|---|---|
| DL-1 | Decision rights — per-node tool allowlists | AC-3, AC-6, CM-7(5) |
| DL-2 | Routing rules — certified transitions only | AC-4, CM-3 |
| DL-3 | HITL triggers — matching decisions reach the human gate | AC-3, CM-3(1) |
| DL-4 | Fallback protocols after errors | SI-4, IR-4 |
| DL-5 | Critical sinks — severity escalation near irreversible actions | AC-6(1), CM-5 |
| DL-6 | Autonomy budget — capped full-autonomy fraction | AC-6, **CA-7** |
| DL-7 | Required steps + continuous trace evidence | AU-2, AU-12, **CA-7** |

CA-7 (continuous monitoring) is the family's umbrella: every monitor cycle
emits an OSCAL 1.1.2-shaped **assessment-results** document attesting each control
`satisfied` / `not-satisfied`, with observations carrying trace evidence and
experiment verdicts. A generated **assessment-plan** derives from the baseline.

Concrete policy binds via `dl:` props in the profile (see
`docs/CERTIFICATION-GUIDE.md` for the full vocabulary and a worked example):

```json
{ "name": "dl:hitl-when",
  "value": "high-value|assess|amount>50000|hitl_review|Loans above 50,000 require human review" }
```

## Proving drift, not assuming it

Every MEDIUM+ anomaly becomes a falsifiable **hypothesis** with a concrete
probe spec. The experiment loop (LangGraph: design → execute → evaluate →
reflect, bounded iterations) re-tests the claim against a **sandboxed replay**
of the full matching population — independent of whichever events the anomaly
cited:

* **Existence claims** (unauthorized tool, route, HITL bypass, fallback break):
  one independently reproduced violation is proof; zero violations across
  sufficient samples is refutation.
* **Rate claims** (autonomy budget): decisions are split into ordered windows;
  drift confirms only when windows *sustain* the excess — a one-off burst stays
  inconclusive.

Verdicts (CONFIRMED / REFUTED / INCONCLUSIVE) are computed deterministically
from probe evidence. Sandboxes are replay-only in v1; the isolation contract is
enforced in code — probes assert isolation on every call, and any future live
clone target must pass a loopback-only endpoint policy or construction fails.
The test suite proves the whole experiment battery runs with sockets
booby-trapped.

Re-running last cycle's confirmed hypothesis against a later, clean trace
yields REFUTED — regression re-testing of remediations comes free.

## CLI

```
driftlab agents                        estate + staleness status
driftlab check --agent loan-officer    one compliance cycle, now
driftlab monitor run                   staleness-weighted estate cycle
driftlab monitor run --force --no-email
driftlab monitor run --scheduled       (for cron/launchd; stamps trigger)
driftlab monitor status                recent runs
driftlab report <cycle_id>             print a cycle's markdown report
driftlab dashboard                     serve the estate UI
driftlab demo                          E2E on the bundled seed estate
```

Scheduling templates live in `ops/` (launchd plist + crontab line). The monitor
is idempotent: any scheduler can fire it; the staleness policy (priority 1-7 →
check interval) decides which agents are actually due.

## Configuration

Environment (prefix `DRIFTLAB_`) or `.env`:

| Variable | Default | Meaning |
|---|---|---|
| `DRIFTLAB_DATA_DIR` | `./.driftlab` | workspace (SQLite + artifacts) |
| `DRIFTLAB_REGISTRY_PATH` | bundled demo registry | monitored-agent registry (`agents.yaml`) |
| `DRIFTLAB_LLM_PROVIDER` | `none` | `none` \| `omlx` |
| `DRIFTLAB_OMLX_BASE_URL` | `http://127.0.0.1:8000/v1` | local MLX server |
| `DRIFTLAB_EMAIL__ENABLED` | `false` | SMTP digest delivery |
| `SMTP_HOST/USER/PASSWORD`, `DRIFTLAB_EMAIL_TO/FROM` | — | notifier env fallbacks |

With `llm_provider=omlx`, DriftLab auto-discovers the model from `/models`,
always constructs the client with `streaming=False` (streaming hangs OMLX with
large models), and adds two advisory layers: an executive narrative in the
report and a DeepAgents analyst pass that decomposes confirmed drifts with
read-only probe tools. Neither can alter a finding. Everything works with no
LLM reachable — that invariant is tested. `ChatOpenAI` is used only as an
OpenAI-compatible protocol client pointed at the operator-controlled OMLX
endpoint; DriftLab has no OpenAI-service provider path.

## Evidence artifacts (per cycle)

```
.driftlab/artifacts/<agent>/<cycle_id>/
├── ledger.json              deterministic anomaly ledger — byte-identical on re-run
├── assessment-plan.json     OSCAL 1.1.2-shaped, generated from the baseline
├── assessment-results.json  OSCAL 1.1.2-shaped, observations + findings (CA-7 evidence)
└── report.md                human-readable report
```

### OSCAL compatibility in v0.1

The catalog, profiles, assessment plans, and assessment results follow OSCAL
1.1.2 structures, with one documented v0.1 deviation: because DriftLab does
not yet emit a per-agent system security plan (SSP), an assessment plan's
`import-ssp` points to the certified baseline profile. The artifacts are not
yet validated as strictly schema-conformant OSCAL and should be treated as
structured evidence inputs, not as proof of OSCAL conformance. The v0.2
hardening milestone adds a component definition, minimal SSP, and `oscal-cli`
validation in CI.

Identity is content-derived throughout: event ids hash decision content,
anomaly ids are uuid5 of the finding fingerprint (stable across cycles — dedup
and first-seen/still-open lifecycle come free), cycle ids hash
(agent, baseline_hash, trace_hash) so identical inputs upsert idempotently.

## Instrumenting your agent

Replay path (recommended to start): emit one JSON object per decision to a
JSONL file and point the registry at it. Live path: attach the bundled
LangGraph/LangChain callback handler:

```python
from driftlab.ingest.langgraph_hook import DriftLabTraceHandler

handler = DriftLabTraceHandler("my-agent", run_id, sink="traces/my-agent.jsonl")
graph.invoke(inputs, config={"callbacks": [handler]})
handler.commit()
```

## Project layout

```
src/driftlab/
├── ingest/        JSONL replay, LangGraph hook, normalizer (canonical DecisionEvent)
├── baseline/      OSCAL catalog/profile → executable BaselinePolicy
├── diff/          behavioral diff engine + NetworkX behavior graph
├── anomaly/       severity ▸ waivers ▸ 35/20/8/3/1 scoring
├── hypothesis/    anomaly → falsifiable claim + probe spec
├── experiment/    LangGraph loop, deterministic probes, sandboxes, DeepAgents pass
├── emit/          OSCAL assessment-plan/results + markdown report
├── monitor/       staleness policy, estate runner, digest, SMTP notifier
├── dashboard/     FastAPI + Jinja estate UI (air-gap friendly, no CDN)
├── store/         SQLAlchemy models + containment-guarded artifact store
├── seed/          bundled demo estate: OSCAL baselines + recorded traces + registry
├── cycle.py       one full compliance cycle, end to end
└── cli.py         Typer CLI
ops/               launchd/cron templates
docs/              RUNBOOK, CERTIFICATION-GUIDE, PITCH, deck, ROADMAP
```

## Design principles (v1, non-negotiable)

1. **Deterministic compliance path** — findings, severities, scores, verdicts
   are pure functions of (baseline, trace). The LLM is advisory only.
2. **Local-first / private** — traces stay on operator-controlled systems; the
   optional LLM path uses only an operator-controlled OMLX endpoint via its
   OpenAI-compatible protocol; the dashboard renders air-gapped.
3. **Provenance is load-bearing** — every anomaly cites trace evidence; every
   experiment cites its probes.
4. **Idempotent by construction** — content-derived IDs; byte-identical
   ledgers on identical inputs (tested).
5. **Bounded autonomy for the proof engine** — probes run against replay
   sandboxes only, isolation enforced in code (tested with booby-trapped
   sockets).

## Docs

* `docs/RUNBOOK.md` — operator runbook (install, schedule, triage, recover)
* `docs/CERTIFICATION-GUIDE.md` — how to certify an agent baseline (for
  compliance/security teams), with worked demo examples
* `docs/HOW-DRIFTLAB-WAS-INTEGRATED.md` — two real-world integrations:
  [`soc-ir-training-cli`](https://github.com/sw30labs/eco-digital-twins-ir-tabletop-training)
  (SOC/IR orchestration) and
  [`article-buddy-2026`](https://github.com/sw30labs/article-buddy-2026)
  (editorial automation), with code excerpts, effort numbers, and a reusable
  checklist
* `docs/PITCH.md`, `docs/deck/` — venture one-pager + Marp deck
* `ROADMAP.md` — phased plan and v2/v3 vision

> **Repository availability.** Some external repositories referenced here,
> including systems used as DriftLab evaluation candidates and case studies,
> are private. Those source repositories are not part of this release and are
> not required to run DriftLab or reproduce the bundled demo. Access is not
> included or guaranteed; the author may grant it only on an ad hoc,
> case-by-case basis. Private links may return 404 unless access has already
> been granted. The selected baselines, traces, and findings committed here are
> intentionally published as real-world DriftLab examples. Imported trace
> metadata is preserved as observed: a source-system model label such as
> `gpt-4o` records what that candidate emitted; it does not configure or prove
> a DriftLab network destination. DriftLab's optional analyst path remains
> OMLX-only.

The `soc-ir-training-cli` case study puts into practice a recommendation from
my book, *AI Agents in Cybersecurity: A Practitioner's Guide* (2025 Edition).
In Appendix C's "Operational Deployment Checklist," I write: **"Conduct
tabletop exercises with incident response team."** DriftLab extends that
exercise discipline to the agent itself by continuously checking its certified
human-review gates, routing, and reporting behavior for drift.

The broader agentic-automation pattern appears in Chapter 2, Section 2.5, as a
specialized-agent "Dream Team," and in Chapter 12's "Workflow Automation":
**"Automation agents eliminate repetitive tasks, enabling analysts to focus on
high-value strategic work."** It also shaped the book itself: a nine-agent
editorial workflow handled revision, fact-checking, copyright review, and QA,
as documented in
[Palimpsest](https://github.com/sw30labs/palimpsest) and generalized as
[Scriptorium](https://github.com/sw30labs/scriptorium). DriftLab's second
real-world integration, `article-buddy-2026`, applies that model to six-role
editorial automation. Its certified baseline requires QA and fact-checking
before publication, remediation of non-PASS verdicts, and web access only from
the fact-checker.

## License

DriftLab is licensed under the [Apache License 2.0](LICENSE).
