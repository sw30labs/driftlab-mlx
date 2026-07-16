# How to Certify an Agent Baseline

A *certified baseline* is the machine-readable statement of an agent's intended,
compliant behavior. DriftLab diffs observed runtime traces against it. This guide
shows compliance/security teams how to author one.

---

## 1. Mental model

The baseline is an **OSCAL profile** that imports the DriftLab **catalog**
(`seed/baselines/driftlab-catalog.json`, controls DL-1..8) and *sets the
parameters* for the agent via `props` namespaced `dl:`.

You are not writing OSCAL control text — you are *configuring* the eight
behavioral controls for one agent. That is the whole job.

## 2. The eight controls and their parameters

| Control | `dl:` prop(s) | Meaning |
|---|---|---|
| **DL-1 Decision Rights** | `dl:tool-allow` = `node\|tool1,tool2` | Tools the agent may call at a node |
| **DL-2 Routing Integrity** | `dl:route-allow` = `from\|to` | Legal state transitions |
| **DL-3 Human Oversight** | `dl:hitl-when` = `node\|condition` | When a decision must route to a human |
| **DL-4 Fallback Protocol** | `dl:fallback-for` = `error-kind\|recovery` | Required recovery after an error |
| **DL-5 Critical Sink** | `dl:critical-sink` = `node` | Irreversible-action nodes (severity escalation) |
| **DL-6 Autonomy Budget** | `dl:autonomy-budget` = `0.0–1.0` | Max fraction of decisions that may be autonomous |
| **DL-7 Required Steps** | `dl:required-step` = `node` | Mandatory process steps |
| **DL-8 Resource Budget** | `dl:resource-budget` = `currency\|ceiling` | Cumulative spend ceiling per currency (`tokens`, `iterations`, `cpu_seconds`, `wall_seconds`); one prop per currency |

Plus: `dl:decision-node` = `node` marks the autonomous disposition nodes used to
compute the DL-6 rate.

DL-8 is audited against the agent's **recorded resource stream** (emitted by
`driftlab.sensor`, a separate JSONL telemetry plane — see
`docs/ADR-001-RESOURCE-BUDGET.md`). Fail-closed rule: if you certify ceilings
but no telemetry is observed, that is itself a MEDIUM finding — certify →
must observe.

## 3. Worked example — the shipped `loan-officer-baseline.json`

```json
{
  "agent": "loan-officer",
  "uuid": "baseline-loan-officer-v1",
  "metadata": { "title": "Loan Officer Agent — Certified Baseline", "version": "1.0.0" },
  "props": [
    {"name": "dl:tool-allow", "value": "assess|credit_check,income_verify"},
    {"name": "dl:tool-allow", "value": "decide|approve,decline"},
    {"name": "dl:tool-allow", "value": "disburse|wire_funds"},
    {"name": "dl:route-allow", "value": "intake|assess"},
    {"name": "dl:route-allow", "value": "assess|decide"},
    {"name": "dl:route-allow", "value": "assess|hitl_review"},
    {"name": "dl:route-allow", "value": "decide|disburse"},
    {"name": "dl:route-allow", "value": "decide|escalate_human"},
    {"name": "dl:hitl-when",   "value": "decide|loan_amount>50000"},
    {"name": "dl:fallback-for","value": "downstream_error|escalate_human"},
    {"name": "dl:critical-sink","value": "disburse"},
    {"name": "dl:autonomy-budget","value": "0.40"},
    {"name": "dl:decision-node","value": "decide"},
    {"name": "dl:required-step","value": "assess"}
  ]
}
```

Interpretation: at `decide`, the agent may only `approve` or `decline`; loans
over $50,000 must route to `hitl_review`; on a downstream error it must
`escalate_human`; `disburse` is a critical sink; no more than 40% of decisions
may be autonomous; and every case must pass through `assess`.

## 4. Waivers (temporary accepted risk)

If a deviation is intentional and time-boxed, record a waiver in `props`:

```json
{"name": "dl:waiver", "value": "DL-3|loan_amount>50000|approved temp limit raise|2026-08-01|risk-123"}
```

Format: `control|condition|rationale|expires|ticket`. While the waiver is active
and unexpired, that control's findings for the matching condition are marked
`waived` and excluded from the score. Expired waivers are ignored (fail-open is
not allowed; an expired waiver reverts to a live control).

## 5. Certification checklist

- [ ] Every tool the agent can call is enumerated per node (DL-1).
- [ ] Every legal transition is enumerated (DL-2); everything else is a violation.
- [ ] Human-oversight triggers match the agent's risk classification (DL-3).
- [ ] Error/fallback paths are specified (DL-4).
- [ ] Critical (irreversible) actions are marked (DL-5).
- [ ] Autonomy ceiling is set from policy, not guesswork (DL-6).
- [ ] Mandatory steps are listed (DL-7).
- [ ] Resource ceilings are set per currency and the agent ships the sensor (DL-8).
- [ ] The baseline is reviewed and signed off by the agent owner + compliance.
- [ ] `uuid` / `metadata.version` are bumped on every change (new hash = new cycle).

## 6. Validating a baseline before deployment

DriftLab **fails closed** on a malformed baseline:

```bash
uv run driftlab check --agent my-agent --no-experiments
```

The compiler rejects unknown `dl:` props, out-of-range budgets, and malformed
`node|value` syntax with a `CompileError` — it will not silently monitor against
a broken baseline.

## 7. Re-certification

When the agent changes behavior intentionally, update the baseline, bump
`metadata.version`, and re-run. The new baseline hash appears in every
subsequent cycle's artifacts, giving auditors a clean before/after lineage.