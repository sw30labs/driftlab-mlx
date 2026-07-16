# DriftLab — Pitch Deck

> 12 slides. Markdown source; render to reveal.js / HTML or slides with any
> Markdown deck tool. Speaker notes inline as `> Note:`.

---

## Slide 1 — Title

# DriftLab
### Continuous, machine-readable compliance observer for running agentic systems

*Local-first · Deterministic · OSCAL-native · Experimentally proven*

> Note: One line that sticks — "We don't just alert you that your agent drifted.
> We prove it."

---

## Slide 2 — The problem

**Agentic systems are making real decisions. Governance is stuck in the past.**

- **Design-time only** — canvases, policy docs, one-shot audits. Nobody watches
  runtime behavior.
- **Static drift detection** exists for infrastructure (Terraform/cloud) — **not
  for agent behavior**.
- **Observability ≠ compliance** — LangSmith/Arize/Langfuse trace runs, but don't
  diff against a certified baseline, don't emit OSCAL, don't flag governance
  drift.

> Note: Regulated teams cannot *demonstrate* continuous control over shipped
> agents — exactly what EU AI Act / SOC 2 / ISO 42001 now require.

---

## Slide 3 — Why now (regulatory tailwinds)

Three forces converge in 2026:

1. **EU AI Act** — in force, phased obligations through 2026–2027: risk
   management, human oversight, technical documentation for high-risk AI.
2. **SOC 2 / ISO 42001** — push organizations to *demonstrate* continuous
   control, not just declare it.
3. **Agentic explosion** — LangGraph, DeepAgents, Claude Code — but governance
   tooling for *running* agents hasn't kept up.

> Note: The compliance obligation is becoming continuous and behavioral. The
> tooling to satisfy it doesn't exist yet.

---

## Slide 4 — Market gap

**Agent observability ≠ compliance.**

| | Observes live agent? | Diffs vs certified baseline? | Emits OSCAL? | Proves drift w/ experiment? |
|---|---|---|---|---|
| LangSmith / Arize / Helicone | ✅ | ❌ | ❌ | ❌ |
| AI governance platforms | ❌ | ❌ | ⚠️ docs | ❌ |
| Infra drift detection | n/a | (config) | ❌ | ❌ |
| **DriftLab** | ✅ | ✅ | ✅ | ✅ |

> Note: The bottom-right cell is empty for everyone except us.

---

## Slide 5 — How DriftLab works

```
Agent runtime → DecisionEvent stream ─┐
OSCAL baseline → Control model (DL-1..8) ─┤
                                        ▼
                        Behavioral Diff (deterministic)
                                        ▼
              Anomaly Engine → Compliance Score + Ledger
                                        ▼
              Hypothesis → Micro-Experiment Loop (prove/refute)
                                        ▼
        OSCAL Evidence + Dashboard + Staleness Monitor
```

> Note: Emphasize "deterministic" — the LLM is advisory only; it never sets a
> severity.

---

## Slide 6 — The differentiator: prove drift with experiment

When the diff flags a suspected drift, DriftLab doesn't just alert.

It runs a **micro-experiment**: a controlled replay of the agent's trace through
a LangGraph `design → execute → evaluate → reflect` loop that reproduces the
suspected drift and returns **confirmed / refuted / inconclusive** with evidence.

- **Existence claim** (e.g. "unauthorized tool used") → probe the replay for the
  predicate; confirm if the violation rate exceeds threshold.
- **Rate claim** (e.g. "autonomy over budget") → window the replay; confirm if a
  majority of windows exceed the ceiling.

**Isolation enforced and tested:** the loop only touches an in-memory replay.
Sockets are booby-trapped in tests — any outbound call fails the build.

> Note: This is the slide investors/auditors remember. "Proven, not presumed."

---

## Slide 7 — Demo flow

```bash
uv run driftlab demo
#   loan-officer:     score 0/100   (4 drift families detected + proven)
#   support-triage:   score 100/100 (clean)
```

- `loan-officer` trace carries 4 seeded drifts: unauthorized tool (DL-1), HITL
  bypass on high-value loans (DL-3), missing error fallback (DL-4), autonomy over
  budget (DL-6). The experiment loop **confirms** each.
- `support-triage` is fully compliant → score 100, zero criticals.

> Note: Live demo — run `check --agent loan-officer`, show the experiment
> verdicts.

---

## Slide 8 — Compliance evidence out of the box

Each cycle emits:

- `assessment-plan.json` — OSCAL 1.1.2-shaped plan (controls, CA-7 anchor)
- `assessment-results.json` — OSCAL 1.1.2-shaped results (satisfied /
  not-satisfied, observations with trace evidence + experiment verdicts)
- `report.md` — operator summary
- `ledger.json` — deterministic, byte-identical on re-run

> Note: These drop straight into SOC 2 / EU AI Act / ISO 42001 evidence packages.
> (v0.2 milestone: strict OSCAL conformance validation — see roadmap.)

---

## Slide 9 — Competitive map

- **vs agent observability** (LangSmith et al.): we add the certified baseline,
  the compliance score, the OSCAL evidence, and the proof loop. They don't.
- **vs AI governance platforms**: we observe *runtime behavior*, not just
  documents. They are design-time.
- **vs infra drift detection**: we operate on *agent decisions*, not cloud
  config. Different substrate, same continuous-monitoring philosophy.

> Note: We are complementary to observability (sit on top of its traces) and
> adjacent to governance (consume its baselines).

---

## Slide 10 — Go-to-market

**Beachhead:** Tier-1 financial services + EU-regulated operators running
high-risk, well-bounded agents (loan adjudication, claims, support triage) under
SOC 2 / ISO 42001.

**Motion:**
1. Self-host PoC on one agent (privacy-preserving, no data leaves the estate).
2. Certify the baseline with the customer's compliance team (CERTIFICATION-GUIDE).
3. Expand to the agent estate; package evidence for audit.

**Channel:** compliance/risk buyers, not ML platform teams.

---

## Slide 11 — Roadmap

- **v2.0 (now):** deterministic core, 7 controls, proof loop, OSCAL evidence,
  dashboard, monitor. *Green test suite.*
- **v0.2:** strict OSCAL 1.1.2 conformance validation; EU AI Act text → control
  auto-mapping; OpenTelemetry ingestor.
- **v3:** multi-agent estate correlation (cross-agent drift), replay-diff UI,
  waiver lifecycle + expiry enforcement in monitor.
- **v4:** regulator-ready evidence packaging + managed audit-as-a-service.

> Note: Each phase has a definition-of-done (see ROADMAP.md).

---

## Slide 12 — Ask

**We are raising to:**
- Harden the v0.2 OSCAL conformance + EU AI Act auto-mapping (the compliance
  moat).
- Ship the multi-agent estate correlation engine (the enterprise expansion).
- Land 3 design-partner deployments in Tier-1 financial services.

**DriftLab — prove your agents stay compliant. Continuously.**

> Note: Close on the one-liner. Leave the demo running on screen.