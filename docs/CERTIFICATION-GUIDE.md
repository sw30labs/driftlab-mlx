# Certifying an Agent Baseline

Audience: compliance, security, and risk teams. This is the "design-time"
half of DriftLab: turning *intended* agent behavior into a certified,
machine-readable OSCAL baseline that the runtime monitor can enforce.

The worked example throughout is the bundled `loan-officer` agent
(`src/driftlab/seed/baselines/loan-officer-profile.json`).

## 1. What you are certifying

A baseline answers seven questions about the agent, one per DL control:

| # | Question | Control |
|---|---|---|
| 1 | Which tools may each node invoke? | DL-1 decision rights |
| 2 | Which routing transitions are allowed? | DL-2 routing |
| 3 | Which decisions must a human review? | DL-3 HITL triggers |
| 4 | What must happen after an error? | DL-4 fallback |
| 5 | Which nodes are irreversible/critical? | DL-5 critical sinks |
| 6 | How much full autonomy is acceptable? | DL-6 autonomy budget |
| 7 | Which steps must every run execute? | DL-7 required steps |

You do not have to certify everything at once: uncertified areas are simply
unmonitored (e.g. a from-node with no `dl:allow-route` entries is
unconstrained). Start with critical sinks and HITL, expand from there.

## 2. Artifact structure

Two OSCAL 1.1.2 documents:

* **Catalog** (`driftlab-catalog.json`) — ships with DriftLab; defines DL-1..7
  with prose statements and SP 800-53r5 crosswalks (CA-7 is the umbrella).
  You normally never edit it.
* **Profile** (one per agent) — imports the catalog and binds your concrete
  policy via `props` in the `dl:` namespace (`https://sw30labs.com/ns/dl`).
  This is the artifact your governance board signs off.

Minimal profile skeleton:

```json
{
  "profile": {
    "uuid": "<uuid>",
    "metadata": {
      "title": "Certified Baseline — my-agent",
      "version": "1.0.0",
      "oscal-version": "1.1.2",
      "props": [
        { "name": "dl:agent-id", "value": "my-agent", "ns": "https://sw30labs.com/ns/dl" },
        { "name": "dl:baseline-status", "value": "certified", "ns": "https://sw30labs.com/ns/dl" }
      ]
    },
    "imports": [{ "href": "driftlab-catalog.json",
                  "include-controls": [{ "with-ids": ["dl-1","dl-2","dl-3","dl-4","dl-5","dl-6","dl-7"] }] }],
    "modify": { "set-parameters": [], "controls": [] }
  }
}
```

`dl:agent-id` is mandatory and must match the registry id — a mismatched
pairing is rejected at cycle start (fail closed).

## 3. The prop vocabulary

All values are strings; repeat a prop to express a list.

| Prop | Format | Example |
|---|---|---|
| `dl:allow-tool` | `node:tool` (`*` = any node) | `assess:credit_check` |
| `dl:allow-route` | `from->to` | `assess->hitl_review` |
| `dl:hitl-when` | `id\|node\|cond1&cond2\|route_to[\|description]` | see §4 |
| `dl:fallback` | `node->fallback_node` (`*` = any node) | `*->escalate_human` |
| `dl:critical-sink` | `node` | `disburse_funds` |
| `dl:auto-target` | `node` (route target counting as full autonomy) | `auto_approve` |
| `dl:decision-node` | `node` — explicit DL-6 decision population. Set this whenever a human gate can also route to the auto target, or the gate's exits would be miscounted as autonomous decisions. | `select_and_ask` |
| `dl:max-auto-fraction` | `0.40` (or `set-parameters` param `dl-max-auto-fraction`) | |
| `dl:required-step` | `node` | `assess` |
| `dl:waiver` | `id\|cap\|fp1,fp2\|rationale[\|from_iso[\|to_iso]]` | see §5 |

Conditions support `> >= < <= == !=` over the decision context; numbers
coerce, everything else compares as strings; `&` conjoins. An absent context
field never fires a trigger (conservative by design).

Unknown `dl:` props are a **compile error**, not a warning — a typo must not
silently certify less than you intended.

## 4. Worked example: the loan-officer HITL gate

Policy intent: *loans above 50,000, and any high-risk applicant, must be
reviewed by a human before funds move.*

```json
{ "control-id": "dl-3", "props": [
  { "name": "dl:hitl-when", "ns": "https://sw30labs.com/ns/dl",
    "value": "high-value|assess|amount>50000|hitl_review|Loans above 50,000 require human review before approval" },
  { "name": "dl:hitl-when", "ns": "https://sw30labs.com/ns/dl",
    "value": "high-risk|assess|risk==high|hitl_review|High-risk applicants require human review" }
]}
```

Reading: at node `assess`, when the decision context satisfies the condition,
the run must subsequently route to (or reach) `hitl_review` before committing.

Runtime semantics you get for free:

* A run matching `amount>50000` that routes `assess -> auto_approve` is a
  DL-3 violation. Because `auto_approve` reaches the critical sink
  `disburse_funds` (DL-5), severity escalates to **CRITICAL**.
* The finding aggregates across runs — the bundled drifted trace yields
  "5 of 8 matching runs bypassed the gate (rate 0.625)" with the violating
  event ids as evidence.
* The micro-experiment loop independently replays *all* matching runs and
  confirms or refutes the bypass before anyone escalates.

Pair DL-3 with the autonomy budget (DL-6) to bound the aggregate, not just the
individual decision:

```json
"set-parameters": [{ "param-id": "dl-max-auto-fraction", "values": ["0.40"] }],
{ "control-id": "dl-6", "props": [
  { "name": "dl:auto-target", "value": "auto_approve", "ns": "https://sw30labs.com/ns/dl" }
]}
```

"At most 40% of routing decisions at the approval gate may take the
full-autonomy path." The drifted seed trace runs at 65%; DriftLab flags HIGH
(overshoot ≥ 10 points) and the experiment confirms the excess is *sustained
across ordered windows*, not a burst.

## 5. Waivers — accepting a known finding

A waiver is a fingerprint-scoped, time-boxed severity cap that lives **inside
the certified artifact** (so acceptance is itself governed and versioned):

```json
{ "name": "dl:waiver", "ns": "https://sw30labs.com/ns/dl",
  "value": "w-2026-07|low|observed_vs_baseline:missing_step:audit|Accepted until Q3 pipeline refactor|2026-07-01T00:00:00|2026-10-01T00:00:00" }
```

The finding stays on the ledger marked `waived` with capped severity — waivers
change scoring, never visibility. Fingerprints are printed on every finding
(report, dashboard, ledger), so copy them from there.

## 6. Certification workflow

1. **Draft** — write the profile with `dl:baseline-status: draft`. Sit with
   the agent team; the graph nodes/tools must use the same names the traces
   emit.
2. **Dry-run** — register the agent, collect a few days of traces, run
   `driftlab check --agent <id>`. Expect findings; tune the baseline (or fix
   the agent) until the diff reflects true intent. An `unknown dl: prop`
   error, or a score that seems wrong, is caught here.
3. **Certify** — set `dl:baseline-status: certified`, bump `version`, obtain
   sign-off. Record the compiled `baseline_hash` (printed by `check`; also on
   every ledger) in your change ticket — every future finding cites the exact
   hash it was judged against.
4. **Monitor** — set the registry priority (1 = daily) and let the scheduler
   own it. Evidence accumulates per cycle under
   `.driftlab/artifacts/<agent>/`.
5. **Evolve** — baseline changes follow the same path: edit → dry-run →
   re-certify → new hash. Old cycles remain attributable to old hashes.

## 7. Evidence you can hand an auditor

Per cycle, per agent: `assessment-plan.json` (what is continuously assessed
and how — derived from the certified baseline), `assessment-results.json`
(observations with trace evidence; per-control `satisfied`/`not-satisfied`
findings; experiment verdicts with reproduction counts), `ledger.json`
(deterministic, byte-stable finding record), `report.md` (human summary).
These map directly onto EU AI Act Art. 9 (risk management as a continuous
iterative process), Art. 14 (human oversight — DL-3/DL-6 attest it
*operationally*), Art. 12 (record-keeping/logging), ISO/IEC 42001 §8
(operational control) and SOC 2 monitoring criteria — with SP 800-53 CA-7 as
the anchoring control.
