# DriftLab — One-Pager

## The problem

Agentic systems (LangGraph, DeepAgents, Claude Code, and friends) are now making
real decisions — approving loans, triaging tickets, executing trades. But the
governance tooling around them is stuck in the past:

- **Design-time only.** Today's "AI governance" is canvases, policy docs, and
  one-shot audits. Nobody watches what an agent *actually does at runtime*.
- **Static drift detection exists for infrastructure** (Terraform/cloud config)
  but **not for agent behavior**. The agent-equivalent is absent.
- **Agent observability ≠ compliance.** LangSmith, Arize, Helicone, Langfuse
  trace and visualize runs — but they are telemetry/debugging, not compliance
  diffing against a certified baseline, and none emit OSCAL or flag governance
  drift.

The result: regulated teams cannot *demonstrate* continuous control over the
agents they ship — which is exactly what EU AI Act, SOC 2, and ISO 42001 now
demand.

## White-space proof

A targeted audit of the market (and the author's own portfolio) shows **no
shipping product** combines all four of:

1. observing *live agent decision traces*,
2. diffing them against a *certified OSCAL baseline*,
3. emitting *OSCAL audit artifacts*, and
4. *proving* drift via a *controlled experiment* rather than merely flagging it.

Agent observability tools don't do (2)/(3)/(4). AI governance platforms don't do
(1). Continuous-compliance tools don't do (1)/(4). The intersection is empty.

## The solution

DriftLab is a **continuous, machine-readable compliance observer for running
agentic systems**. It:

- taps an agent's runtime decision traces (tool calls, routing, escalations,
  refusals) and normalizes them into a canonical `DecisionEvent` model;
- diffs them, deterministically, against a certified OSCAL baseline across
  **eight behavioral controls** (decision rights, routing, human oversight,
  fallback, critical sinks, autonomy budget, required steps);
- scores compliance (0–100) and emits an anomaly ledger with full provenance;
- and — uniquely — runs a **micro-experiment loop** that *proves or refutes*
  each suspected drift with a controlled replay, so a confirmed finding is
  evidence, not an alarm.

It is **local-first, private, deterministic, and works without any LLM**.

## Moat

- **Local-first + private** — no agent traces leave the host; deployable inside
  a regulated estate.
- **Deterministic compliance path** — severities come from the diff engine, not
  a model. Auditable and reproducible.
- **OSCAL-native evidence** — outputs drop straight into SOC 2 / EU AI Act / ISO
  42001 artifact packages.
- **Experimental proof** — the differentiator. "We proved the drift on a
  controlled replay" beats "we think it drifted" in front of an auditor.

## Beachhead

Tier-1 financial services, EU-regulated operators, and any org under SOC 2 /
ISO 42001 running autonomous agents in production. Start with high-risk,
well-bounded agents (loan adjudication, claims, support triage) where the
baseline is easy to certify and the audit pressure is highest.

## Business model

- **Self-host license** — DriftLab runs on the customer's infrastructure
  (privacy-preserving by design); annual per-estate license.
- **Enterprise audit-as-a-service** — managed baseline certification, evidence
  packaging, and regulator-ready reporting on top of the self-host core.

## Status

Working v2 prototype: green test suite (22 tests), full CLI, dashboard, OSCAL
evidence emitter, staleness-weighted monitor, and a proven micro-experiment loop
that confirms seeded drifts and refutes them on a clean trace. See `README.md`
and `docs/`.