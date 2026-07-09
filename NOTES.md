# NOTES — deviations from the build brief, and why

Per §10 of the brief, every place the build diverges from the letter of the
spec, with reasoning. Anything not listed here follows the brief.

## Architecture & scope

1. **The 3-way diff ships as 2-way (observed vs certified), with the third way
   staged for v0.3.** glass-graph's 3-way compares Baseline/Source/PROD
   *structural* snapshots. DriftLab's core comparison is behavioral:
   certified-baseline vs observed-trace. A "declared" third leg (the agent's
   static graph, via glass-graph extraction) adds real value but is orthogonal
   to the runtime thesis and would have diluted v1. The `ComparisonType` enum
   already carries `declared_vs_baseline` / `observed_vs_declared` so the
   model and fingerprint grammar are ready. (ROADMAP v0.3.)

2. **The micro-experiment loop is a plain LangGraph StateGraph with
   deterministic verdicts; DeepAgents runs as an advisory pass on top, not as
   the loop itself.** The brief asked for the loop to *be* a DeepAgents agent.
   Two reasons to deviate: (a) §4.1 (deterministic compliance path) and §7
   (LLM-optional test) jointly require verdicts with no LLM reachable — a
   DeepAgents-driven loop cannot satisfy that; (b) setpoint's experiment fleet
   turned out to be design-only (ULTRAPLAN prose, empty stubs), so there was
   no proven autonomous-loop code to port. The genuinely long-horizon,
   open-ended part — decomposing "characterize this drift" into sub-probes —
   is exactly where DeepAgents sits (`experiment/deep_agent.py`), with
   read-only probe tools against the same sandbox, annotating but never
   deciding. This honors both the "DeepAgents is necessary" instruction and
   the determinism principle; if you want DeepAgents deeper in the loop, the
   seam is `loop.py::design_node`.

3. **Probes are replay-based in v1; the "sandboxed clone" is a stub with the
   isolation contract enforced.** Proving drift by replaying the full matching
   population (independent of the events the anomaly cited) is a real
   controlled re-test and is what recorded traces support honestly. Live clone
   probing needs an agent-execution harness per framework — v0.3. The
   loopback-only endpoint policy and `assert_isolated()` are in the public API
   *now* so the safety contract doesn't get retrofitted later.

4. **Baselines are OSCAL profiles + a DriftLab catalog, not raw
   `governance-oscal` schemas.** Audit of your five OSCAL repos showed the
   strongest pattern is OSCAL-skills-guardrails (custom control family in a
   catalog, concrete policy via namespaced props in a profile, evidence as
   assessment-results) — and showed two gaps worth fixing: fabricated control
   ids with no 800-53 crosswalk (the agent-guardrails anti-pattern, avoided),
   and CA-7 never used anywhere (adopted as the family's umbrella control).
   One deliberate OSCAL deviation remains: assessment-plan's `import-ssp`
   points at the profile because no per-agent SSP exists yet; the remarks
   field declares this and v0.2 closes it with component-definition + SSP.

5. **Module layout is close to §5.2 but not literal.** `llm.py` at package
   root (as specced); `store/` combines db + artifacts (glass-graph split
   them); `cycle.py` is a root-level service the brief didn't name — CLI
   `check`, monitor runner, and tests all needed the same
   ingest→diff→prove→emit path, so it got one owner. `normalizer.py` lives in
   `ingest/` per the brief.

## Determinism upgrades beyond the brief

6. **Deterministic anomaly/experiment/cycle IDs.** glass-graph uses random
   `uuid4()` for anomaly ids; the scout flagged it as its one idempotency gap.
   DriftLab uses `uuid5(namespace, fingerprint)` throughout, which is what
   makes byte-identical ledgers (§7 determinism test) and cross-cycle drift
   lifecycle possible. Cycle ids hash (agent, baseline_hash, trace_hash), so
   identical inputs upsert the same row (regitel merge semantics).

7. **Timestamps are provenance, not identity.** Event ids exclude `ts`;
   ledgers exclude wall-clock entirely; OSCAL evidence keeps real assessment
   times (auditors need them) but all its UUIDs are content-derived.

## Stack & environment

8. **Tailwind dropped from the dashboard.** glass-graph's templates use
   Tailwind via CDN; a compliance dashboard for banks must render air-gapped
   (§4.2 local-first), so the UI is ~60 lines of hand CSS carrying the exact
   glass-graph hex palette.

9. **`streaming=False` is passed explicitly** on every `ChatOpenAI`
   construction (brief/memory note), plus OMLX model auto-discovery from
   `/models` (article-buddy pattern) and a 600s timeout for on-demand model
   loads. The OMLX server was not reachable from the build sandbox, so live
   OMLX behavior was exercised only through mocks — first local run on your
   Mac with `DRIFTLAB_LLM_PROVIDER=omlx` is worth a smoke test.

10. **Python `>=3.11`, hatchling, standard src-layout** (`src/driftlab`, not
    glass-graph's package-named-`src` quirk). deepagents requires ≥3.11
    anyway; built and tested on 3.12.

11. **langchain-openai + deepagents are an optional extra** (`[llm]`), not
    core dependencies. The compliance path imports neither; `pip install
    driftlab` stays lean and the LLM-optional invariant is structural, not
    just configured. LangGraph *is* core (the experiment loop uses it, per the
    required stack).

## Product judgment calls

12. **Demo agents chosen over the brief's freedom clause**: `loan-officer`
    (credit decisioning = the canonical EU AI Act Annex III high-risk case —
    also the strongest pitch demo) with four seeded drifts spanning all
    behavioral kinds, and `support-triage` as the zero-false-positive control.

13. **Severity for unauthorized tools is graded** (touches critical sink →
    CRITICAL, reaches sink → HIGH, isolated → MEDIUM) rather than flat-critical:
    an all-critical demo ledger would have hidden the scoring model's shape.
    The HITL-bypass CRITICAL comes from sink *reachability* (NetworkX), which
    is the brief's critical-sink idea doing real work.

14. **Autonomy drift is proven with ordered-window sustainment**, not simple
    rate re-computation: confirming requires the budget breach to hold across
    consecutive windows, which distinguishes systematic drift from a burst —
    closer to what "prove it" should mean for a statistical claim. Existence
    claims (tools/routes/HITL/fallback) confirm on any independently
    reproduced violation and refute only with sufficient samples.

15. **Registry paths resolve relative to the registry file**, so an estate is
    a relocatable folder you can check into a repo.

15b. **The seed estate lives inside the package** (`src/driftlab/seed/`), not
    at repo root as §5.2 sketched. Final verification caught the reason: with
    a wheel install (not editable), a repo-root `seed/` doesn't ship, and
    `driftlab demo` ran against an empty estate. Bundling the seed makes the
    wheel self-contained; real estates point `DRIFTLAB_REGISTRY_PATH`
    elsewhere.

16. **Monitor stamps `--scheduled` into run history** (regitel never threaded
    its `trigger` param from the CLI — small fix the scout suggested).

17. **Pitch numbers were re-grounded against July 2026 reality**: the brief's
    "EU AI Act phased obligations through 2026–2027" became "Digital Omnibus
    (June 2026) fixed Annex III high-risk obligations at 2 Dec 2027" — a
    *better* wedge (defined runway, and credit scoring is named Annex III),
    sourced in docs/PITCH.md.

18. **`dl:decision-node` prop added after the first real-agent integration.**
    Monitoring soc-ir-training-cli exposed a DL-6 modeling gap: when a HITL
    gate's exit routes to the same node as the autonomous path (hitl_gate ->
    respond), the inferred decision population counted human-answered exits
    as autonomous decisions (30/40 = 75% instead of the true 22/30 = 73%).
    Baselines can now pin the decision population explicitly; the inference
    remains as fallback. Regression-tested.

## Known limitations (v1, honest list)

* Trace replay is whole-file per cycle; fine to ~10⁵ events, incremental
  windows are v0.2.
* Emitted OSCAL is 1.1.2-shaped but not yet CI-validated against NIST
  schemas (your repos' validator silently degrades, so I didn't reuse it;
  oscal-cli lands in v0.2).
* The LangGraph callback hook covers node/tool/route/error/interrupt; exotic
  streaming topologies (Send/parallel fan-out) untested against real apps.
* `deepagents` API pinned loosely (`>=0.6,<1.0`); its surface moves fast.
* HITL trigger satisfaction is per-run ("escalated after match, before
  commit") — sub-run scoping (per-decision-item) is future work.
