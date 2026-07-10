# DriftLab v2 — Deviations from the Build Brief (NOTES.md)

This document records every deviation I made from the brief
(`DriftLab - Build Prompt for Claude Cowork`, 2026-07-10) and why. The brief
explicitly grants this latitude ("amend, perfect, extend, redesign, or reject
any part").

---

## 1. Source projects in §9 do not exist on this machine

**Brief assumption:** DriftLab reuses `glass-graph`, `regitel`,
`governance-oscal`, `setpoint`, `twinops` from `/Users/spider/Code/REPOS/`.

**Reality:** None of those repositories exist under `/Users/spider/Code/REPOS/`
(confirmed by filesystem search). They could not be ported.

**Decision:** I implemented the required engines **natively** in DriftLab v2
rather than porting. The *functionality* the brief attributed to those projects
is present and deliberately echoes their described patterns:
- the deterministic 3-way-style diff → `diff/` (7 control checks, pure Python);
- the staleness-weighted monitor → `monitor/policy.py` (priority→interval map);
- OSCAL schemas → `baseline/` + `emit/` (DL catalog + 1.1.2-shaped artifacts);
- the autonomous micro-experiment loop → `experiment/loop.py` (LangGraph
  `StateGraph`).

I did not silently pretend to port; I built equivalent engines from scratch.

---

## 2. OSCAL evidence is "OSCAL-shaped", not strictly schema-conformant (v0.1)

**Brief:** emit "OSCAL assessment-plan / assessment-results artifacts that are
audit-grade."

**Deviation:** The emitted `assessment-plan.json` / `assessment-results.json`
follow OSCAL 1.1.2 *structure and field names* but are pragmatic approximations:
- `import-ssp` points at the baseline profile by URI rather than a fully
  resolved system-security-plan;
- `results`/`observations` use `prop` bags for control-id/severity/evidence
  rather than the strict `assessment-results` object graph.

**Why:** Strict OSCAL 1.1.2 conformance (proper `import-ssp`, `assessment-method`,
`test-result` objects) is a real validation milestone but is not required for the
core product to demonstrate value, and the brief's freedom clause invites
prioritizing a working differentiator first. This is tracked as the **v0.2
strict-conformance milestone** in `ROADMAP.md`. The artifacts are still usable
evidence inputs today.

---

## 3. DL-5 (Critical Sink) redesigned from an independent check to a severity
escalation

**Brief:** lists DL-5 as one of seven controls; implies a check.

**Deviation:** DL-5 is *not* an independent finding producer. It is a
**severity-escalation rule**: when a finding's evidence reaches a certified
critical-sink node, its severity is bumped to `CRITICAL`. A separate independent
"critical sink" check would flag every routine use of an irreversible action
(e.g. `respond` in support-triage) as a violation, producing false positives.

**Why:** The original framing was unfalsifiable against normal operation. The
escalation form preserves the intent (irreversible actions demand the highest
scrutiny) without breaking clean agents. This is documented in `domain/` and
`anomaly/`.

---

## 4. Autonomy budget (DL-6) defined per *decision*, not per *event*

**Brief:** "agent routed 30% more decisions to full autonomy than the canvas
allows."

**Deviation:** The autonomy rate is computed as
`autonomous_dispositions / (autonomous_dispositions + human_authority_events)`,
where autonomous dispositions are tool calls at certified `dl:decision-node`s
and human-authority events are HITL/refusal/escalation. The naive "fraction of
all events that are autonomous" definition is dominated by routing/tool noise
and is not a meaningful compliance metric.

**Why:** Correctness of the metric matters more than literal adherence; the
per-decision definition is what an auditor would actually accept.

---

## 5. DeepAgents not introduced as a hard dependency

**Brief:** the micro-experiment loop "should be implemented as a DeepAgents
autonomous agent."

**Deviation:** The loop is implemented with a **LangGraph `StateGraph`** (the
same orchestration primitive the brief mandates for the pipeline) rather than
adding the `deepagents` package. The loop's `reflect` step is where a longer
horizon decomposition would live; I kept it as a deterministic synthesis and
exposed an *optional, advisory-only* `llm.analyst_decomposition` hook for that
role instead of binding the compliance path to an extra framework.

**Why:** (a) `deepagents` was not installable/needed for a deterministic proof
engine; (b) the brief's principle #1 forbids the LLM from affecting a verdict, so
the "autonomous agent" could only be advisory anyway; (c) one orchestration
primitive is simpler and easier to test. If a genuine long-horizon decomposition
is wanted later, it slots into `experiment/loop.py:reflect` without touching the
deterministic verdict logic.

---

## 6. Editable install does not work in this uv/venv environment

**Brief implies:** standard `uv` workflow.

**Deviation:** `uv pip install -e .` (editable) leaves the package unimportable
because the generated `.pth` is not processed by this uv-created venv. I install
the **built wheel** (`uv pip install .`) and set `[tool.uv] package = false` so
`uv run` does not revert to the broken editable build. Tests rely on pytest's
`pythonpath = ["src"]`.

**Why:** Environment quirk, not a design choice. Documented in `README.md` and
the runbook so the user doesn't hit `ModuleNotFoundError`.

---

## 7. HITL condition syntax simplified

**Brief:** `dl:hitl-when` = `node|condition`.

**Deviation:** The condition is a simple `field>number` comparison evaluated
against the triggering event's `details` (e.g. `loan_amount>50000`). No general
expression language.

**Why:** Keeps the deterministic engine simple and testable; covers the realistic
case (threshold-based human oversight) without a parser.

---

## 8. Minor: seed trace autonomy is 100% for loan-officer, not exactly 65%

**Brief example:** "agent routed 30% more decisions to full autonomy than the
canvas allows" (implying ~65% vs 40%).

**Deviation:** The generated loan-officer trace is 100% autonomous (all 30
decisions decided without HITL), which is *even more clearly* over the 40%
budget — a stronger, unambiguous demonstration of DL-6 drift. The 65% figure was
illustrative.

**Why:** Demonstrative clarity over matching an example number; the test asserts
"over budget → anomaly", which holds.

---

## What I kept exactly as specified

- Local-first / private; no traces leave the host. ✅
- LLM advisory-only, optional, `streaming=False` against OMLX. ✅
- Deterministic compliance path (diff/anomaly/score pure Python). ✅
- Content-derived ids / idempotent re-runs (determinism test passes). ✅
- Sandbox isolation for the proof engine (sandbox-safety test passes). ✅
- Tech stack: Pydantic v2, NetworkX, FastAPI+Jinja, Typer+Rich, SQLAlchemy+
  SQLite, LangGraph. ✅
- §8 collateral: README, runbook, certification guide, pitch, deck (12 slides),
  roadmap, this NOTES. ✅
- Green pytest suite (22 tests) before "done". ✅