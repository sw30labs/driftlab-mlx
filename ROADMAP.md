# DriftLab Roadmap

Owner: Nicolas Cravino (sw30labs). Status date: 2026-07-09.

## Delivered — v0.1 (Phases 0–6 of the build brief)

| Phase | Scope | Definition of done | Status |
|---|---|---|---|
| 0 | Scaffold: uv project, Typer CLI, pytest harness | `uv sync` + green suite | ✅ |
| 1 | Trace ingestion: canonical `DecisionEvent`, JSONL replay, LangGraph callback hook, loud-failure normalizer | seed traces load; unknown event types raise | ✅ |
| 2 | OSCAL baseline: DL-1..7 catalog (800-53 crosswalk, CA-7 anchor), `dl:` profile vocabulary, fail-closed compiler | loan-officer + support-triage baselines compile; typos fatal | ✅ |
| 3 | Behavioral diff + anomaly engine: 7 control checks, deterministic fingerprints, severity table w/ critical-sink reachability, waivers, 35/20/8/3/1 score | drifted trace → 4 findings incl. 1 CRITICAL; clean trace → 0; byte-identical ledger | ✅ |
| 4 | Drift hypothesis + micro-experiment loop: LangGraph design→execute→evaluate→reflect, existence + windowed-rate probes, replay sandbox with enforced isolation, DeepAgents advisory pass | all 4 seeded drifts CONFIRMED with probe evidence; clean-trace re-test REFUTES; socket-booby-trap test green | ✅ |
| 5 | Evidence + dashboard + monitor: OSCAL assessment-plan/results per cycle, markdown report, FastAPI estate UI, staleness-weighted runner, SMTP digest (never-raise), launchd/cron templates | `driftlab demo` E2E; dashboard renders air-gapped; email failure can't kill a cycle | ✅ |
| 6 | Docs + collateral: README, RUNBOOK, CERTIFICATION-GUIDE, pitch, deck, NOTES | this repo | ✅ |

Suite: 88 tests green (unit, integration, E2E replay, determinism, sandbox
safety, LLM-optional).

## v0.2 — Hardening for a first design partner (≈ 4–6 weeks)

* **Streaming/windowed ingestion** — incremental trace windows (since last
  cycle) instead of full-file replay; watermark per agent; retention policy.
  *DoD: 1M-event trace processes in <30s incremental.*
* **OpenTelemetry ingestor** — map OTel GenAI semantic-convention spans →
  `DecisionEvent`; unlocks agents already instrumented for Langfuse/LangSmith.
  *DoD: replay a Langfuse OTel export of a real agent.*
* **Strict OSCAL validation in CI** — run emitted catalog/profile/plan/results
  through NIST oscal-cli; fix the known pragmatic deviation by emitting a
  **component-definition + minimal SSP** per agent so assessment-plan's
  `import-ssp` is schema-true. *DoD: oscal-cli validates all artifacts.*
* **Anomaly lifecycle** — first-seen / still-open / resolved views over the
  deterministic anomaly ids (the uuid5 groundwork is already in). *DoD:
  dashboard shows drift age; digest reports "resolved since last run".*
* **Baseline certification CLI** — `driftlab certify init/lint/diff`:
  scaffold a profile from an observed trace (propose allowlists/routes),
  lint it, diff two baseline versions. *DoD: certify a new agent in <1h.*

## v0.3 — The proof engine grows teeth (≈ quarter)

* **Live clone sandbox** — probe a disposable agent instance (loopback-only
  policy already enforced): synthesize trigger contexts, run N controlled
  episodes, measure gate behavior directly instead of replay-only.
  *DoD: HITL-bypass probe against a live LangGraph clone in CI.*
* **Statistical rigor** — binomial confidence intervals on violation rates;
  CUSUM/changepoint detection for budget drift (when did it start?); power
  analysis feeding INCONCLUSIVE ("need ≥N more matching runs").
* **Declared-vs-baseline third way** — import glass-graph structural snapshots
  to complete the 3-way (certified / declared / observed) comparison.
* **Waiver governance** — expiry alerts in the digest; waiver audit trail in
  assessment-results.

## v2 — Estate intelligence

* **Multi-agent estate monitoring at depth**: cross-agent drift correlation
  (same tool acquired across agents; autonomy creep cohorts; shared-model
  regression after a provider upgrade).
* **Drift attribution**: join drift onset to change events (model version,
  prompt hash, config deploy) — "autonomy breach began with the 6/14 prompt
  change".
* **Evidence packs**: one-click assessment-window bundle (all cycles, all
  agents, cover memo) for an auditor; POA&M emission for open criticals.
* **Cowork/Claude scheduled-task wrapper** as an alternative to cron/launchd.

## v3 — Regulatory autopilot

* **Regulation → baseline auto-mapping**: EU AI Act Art. 9/12/14 and ISO
  42001 §8 text → suggested DL-control parameterizations per agent archetype
  (regitel's regulatory-intelligence graph is the natural engine here).
* **Continuous authorization**: OSCAL POA&M + ongoing-authorization workflow;
  drift SLOs with error budgets per control.
* **Marketplace of certified baselines**: reference baselines for common
  agent archetypes (credit decisioning, claims triage, support, procurement).

## Standing invariants (never traded away)

Deterministic compliance path · local-first, traces stay on host · provenance
load-bearing · idempotent by construction · probes never touch production.
