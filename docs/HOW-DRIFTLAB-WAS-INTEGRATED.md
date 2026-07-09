# How DriftLab Was Integrated: the soc-ir-training-cli Case Study

The first real-agent integration, documented as a reusable playbook. Follow it
to hook the next agent; the checklist at the end is the part to copy.

**The subject:** `REPOS/soc-ir-training-cli` — a LangGraph SOC/IR training
platform whose tabletop test executor makes per-inject decisions: select a
playbook, check for incident reclassification, decide whether a human must
answer, respond, QA.

**The result, in numbers:**

| Metric | Value |
|---|---|
| New code in the agent repo | 1 module (~100 lines) + 6 hook sites (67-line diff in 2 files) |
| Baseline | ~90 lines of OSCAL profile (5 controls) |
| Registry entry | 4 lines of YAML |
| Wall-clock effort | ~half a day, most of it reading the agent's code |
| Agent behavior change when tracing is off | zero (env-gated no-op; proven by its own test suite: 121 passed before and after) |
| First real cycle | score **72/100** — HITL bypass (HIGH, CONFIRMED 2/6 runs) + autonomy 73% vs 70% budget (MEDIUM, CONFIRMED sustained) |
| Bonus | integration exposed a DriftLab modeling gap → new `dl:decision-node` prop |

---

## Step 1 — Find the decision seams (the actual work)

Read the agent's orchestration code looking for four things:

1. **Routing functions** — where control flow branches on data
   (`route_after_select`, `should_continue_testing`, `route_next_phase`).
2. **The HITL decision** — the function that decides whether a human sees it
   (`should_ask_human`: reclassification > gap > overlap > weak >
   `difficulty == "high"` > every).
3. **Tool/capability call sites** — LLM sub-agents, external calls
   (`playbook_selection`, `cyber_agent`, `qa_agent`).
4. **The decision context** — the variables the rules will condition on
   (inject `difficulty`, `selection_status`, `reclassified`). These must end
   up in the trace or the baseline can't check them.

In soc-ir all of this lived in `src/services/tabletop/test_graph.py` and
`src/services/orchestration/master_workflow.py`. Well-structured LangGraph
apps put decisions in conditional-edge functions and node seams — that's what
makes them cheap to instrument. If decisions are buried in free-text prompts,
surface them into code first (that's an agent-quality problem, not a DriftLab
one).

## Step 2 — Drop in the adapter module

One self-contained file, no dependencies, copy-paste per project:
`src/services/observability/driftlab_trace.py`. Its contract:

```python
_ENV_PATH = "SOC_IR_DRIFTLAB_TRACE"          # unset => everything is a no-op

def is_enabled() -> bool: ...
def set_run(run_id: str) -> None: ...        # resets the per-run seq counter
def emit(event_type, node, *, tool=None, target=None, autonomy=None,
         decision_context=None, attrs=None) -> None:
    """Append one canonical decision event. Never raises."""
```

Three design rules, all non-negotiable:

* **Opt-in via env var.** Unset = immediate return. Production behavior is
  untouched by default.
* **Never raises.** One warning on the first write failure, then silence —
  observability must never break an exercise.
* **Strings in `decision_context`.** DriftLab conditions compare strings and
  numbers; booleans are emitted as `"true"`/`"false"` so `reclassified==true`
  matches predictably.

## Step 3 — Hook the seams (6 sites)

Every hook is guarded and 1–15 lines. The one that matters most — the routing
decision that DL-3 and DL-6 judge (verbatim from `select_and_ask_node`):

```python
# DriftLab observability (opt-in, no-op unless SOC_IR_DRIFTLAB_TRACE is set)
if driftlab_trace.is_enabled():
    driftlab_trace.emit(
        "route", "select_and_ask",
        target="hitl_gate" if pending else "respond",
        autonomy="human" if pending else "auto",
        decision_context={
            "inject_id": inject.get("inject_id", ""),
            "difficulty": str(inject.get("difficulty", "")).lower(),
            "selection_status": str((selection_outcome or {}).get("status") or "NONE"),
            "reclassified": "true" if reclassification else "false",
            "trigger": trigger.value if trigger else "none",
        },
    )
```

All six sites:

| Site | File | Emits |
|---|---|---|
| `select_and_ask_node` | test_graph.py | selection `tool_call` + the HITL/route decision above |
| `route_after_gate` | test_graph.py | clarification-loop routing (`hitl_gate->hitl_gate`) |
| `hitl_gate_node` | test_graph.py | `hitl` event: trigger, facilitator action, rounds |
| `respond_node` | test_graph.py | `tool_call` cyber_agent |
| `should_continue_testing` | test_graph.py | inject-loop / QA routing |
| `qa_review_node` | test_graph.py | `tool_call` qa_agent + terminal `output_commit` |
| `route_next_phase` | master_workflow.py | master phase routing incl. skip cascades |

## Step 4 — Wire the run id (easy to forget)

One `set_run(...)` call per entry point, or every exercise merges into one
run: `execute_complete_exercise` uses its existing `run_id`;
`execute_test_graph` generates a timestamp id. **This was a gap found only
when documenting the server run-path — check your entry points explicitly.**

## Step 5 — Write the baseline (the thinking)

`driftlab/estate/baselines/soc-ir-tabletop-profile.json` certifies exactly
what Step 1 found. The key rule — `should_ask_human`'s CRITICAL branch,
translated almost verbatim into OSCAL:

```json
{ "name": "dl:hitl-when",
  "value": "critical-inject|select_and_ask|difficulty==high|hitl_gate|High-difficulty injects are critical decision points and must reach the human gate" }
```

And the autonomy budget — including the lesson this integration taught:

```json
{ "name": "dl:auto-target",    "value": "respond" },
{ "name": "dl:decision-node",  "value": "select_and_ask" }
```

Without `dl:decision-node`, the inferred decision population also counted the
HITL gate's *exit* (`hitl_gate->respond`, a human-answered decision) as
autonomous — 30/40 = 75% instead of the true 22/30 = 73%. **When a human gate
routes to the same node as the autonomous path, pin the decision population
explicitly.** Deliberate scoping decisions, documented in the profile remarks:
no DL-4 (this agent's certified error posture is catch-record-continue, not a
fallback route) and no DL-5 (a training simulator has no irreversible external
action → HITL bypasses rate HIGH, not CRITICAL).

## Step 6 — Register and run

Four lines in `driftlab/estate/agents.yaml`, then:

```bash
uv run driftlab check --agent soc-ir-tabletop --registry estate/agents.yaml
```

Expect the first check to disagree with your expectations — that's the
dry-run loop working. Iterate node names / conditions / budgets until findings
reflect true intent, then mark the profile `certified`.

## Step 7 — Prove non-invasiveness before shipping

* Agent's own test suite, tracing env unset: **identical results** (121
  passed; the one failure was pre-existing, confirmed by re-running against
  the stashed tree).
* Explicit no-op check: `emit()` with env unset touches nothing.
* `git diff --stat` review: 2 files modified, 2 added — all additive.

---

## The integration checklist (copy for the next agent)

```
Plumbing
[ ] Decision seams identified (routing fns, HITL decision, tool calls, context vars)
[ ] Adapter module copied in (env-gated, never-raises, strings-only context)
[ ] Hooks at each seam (guarded, 1-line where possible)
[ ] decision_context carries every variable the baseline will condition on
[ ] set_run() wired at EVERY entry point (server, CLI, batch)
[ ] Trace path documented in the agent's README (+ export-before-server rule)

Baseline
[ ] DL-1 tools: allowlist per node
[ ] DL-2 routes: certified transitions (include self-loops like clarification)
[ ] DL-3 triggers: conditions exist verbatim in decision_context
[ ] DL-6: auto-target + dl:decision-node if any human gate routes to the auto target
[ ] DL-7 required steps; DL-4/DL-5 scoped consciously (document omissions in remarks)
[ ] Profile status: draft until the dry-run loop converges

Verification
[ ] driftlab check runs; findings match a hand-count of the raw trace
[ ] Agent's own tests: identical results with tracing off
[ ] Registry entry added; monitor picks the agent up
[ ] Known-drift rehearsal if possible (e.g. run once with the gate misconfigured
    — the drift you detect on day one proves the drift you'll catch on day 300)

Effort budget (from this case): seams ~2h · adapter+hooks ~1h · baseline ~1h ·
verification ~1h. If it's taking much longer, the agent's decisions probably
aren't in code yet — fix that first.
```

## Gotchas index

1. Env var must be exported **before the server starts** — hooks live in the
   server process.
2. Booleans/numbers in `decision_context` → emit strings.
3. Human-gate exits vs autonomy counting → `dl:decision-node`.
4. `set_run()` per entry point or runs merge.
5. Port collisions produce plausible-looking 404s from the *wrong* service
   (here: OMLX on 8000 answering for the app) — make CLI base URLs
   env-overridable (`SOC_IR_API_BASE`).
6. v1 replays the whole trace file per cycle — rotate the file per assessment
   window.
7. **One process hosting two certified graphs → two agent ids.** soc-ir's
   first real server run proved this: master-workflow phase events landed
   under the tabletop agent and read as "skipped QA." Fix: the adapter's
   `emit(..., agent_id=...)` override tags each graph's events with its own
   agent (`soc-ir-exercise` vs `soc-ir-tabletop`); both share one trace file,
   and DriftLab judges each agent strictly on its own events (core-enforced,
   regression-tested). Split baselines = split verdicts: the tabletop keeps
   its findings, the real exercise scored a clean 100.

---

## Addendum: the checklist held on integration #2 (article-buddy)

Same playbook, second agent, same afternoon. What differed — and confirmed
the difficulty model:

* **article-buddy already had a typed event bus** (steps, permission checks,
  budget), so the adapter is a *subscriber*, not hooks: zero changes inside
  the pipeline. Only the fact-check → remediation branch in `main.py` needed
  explicit emits (3 helper calls), plus one behavior-preserving extraction of
  the remediation predicate into an importable function.
* **The permission registry narrated DL-1 for free**: real
  `PermissionChecked` events became per-node tool calls, so "web egress only
  at the fact-checker" is certified against events the app already publishes.
* **Result:** score 45/100 on the rehearsal estate — a CRITICAL
  (FAIL-verdict article published unremediated when the report content went
  missing: the *real predicate* behaving as coded, violating certified
  intent) and a HIGH (fact-check skipped entirely in 2 of 8 runs), both
  experimentally CONFIRMED. Their suite: 401 passed with tracing off, both
  pre-existing failures unchanged.
* **Lesson to add to the gotchas:** when a pipeline has an event bus,
  integrate *there* — one subscriber beats N hooks, and the app's own audit
  events (permissions, budget) are richer than anything you'd bolt on.

*Companion docs: CERTIFICATION-GUIDE.md (baseline authoring in depth),
RUNBOOK.md (operations), soc-ir-training-cli/README.md and
article-buddy-2026/README.md § "DriftLab Behavioral Compliance Tracing"
(the agent-side views).*
