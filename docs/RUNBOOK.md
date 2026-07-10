# DriftLab Operator Runbook

This runbook covers day-to-day operation of a DriftLab deployment: installing,
registering agents, running cycles, reading results, and responding to findings.

---

## 1. Install

```bash
cd /Users/spider/Desktop/driftlabv2
uv venv --python 3.13
uv pip install .
```

> Install as a wheel (`uv pip install .`), not editable. The editable install's
> `.pth` is not honored by this uv/venv combination; see `NOTES.md`.

## 2. Register a monitored agent

Edit `src/driftlab/seed/agents.yaml`:

```yaml
agents:
  - id: my-agent
    name: "My Agent"
    baseline: baselines/my-agent-baseline.json   # relative to seed root
    trace: traces/my-agent-trace.jsonl
    priority: 7          # 1-7, higher = checked more often (staleness weighting)
    owner: "Team Name"
```

Then drop the baseline (see CERTIFICATION-GUIDE.md) and a recorded trace
(JSONL, one DecisionEvent per line) into `seed/baselines/` and `seed/traces/`.

## 3. Run a cycle

```bash
uv run driftlab check --agent my-agent          # once, now
uv run driftlab monitor run --force             # whole estate, ignoring staleness
uv run driftlab monitor run                     # only agents whose interval elapsed
```

## 4. Read the results

- **Score** (`0–100`): starts at 100, minus `severity_weight × count` per active
  anomaly. Weights: critical 35, high 15, medium 8, low 3, info 1. Floored at 0.
- **Findings table**: control (DL-x), severity, title.
- **Experiment verdicts**: `confirmed` / `refuted` / `inconclusive` — the proof
  engine's independent reproduction of each suspected drift.

A `confirmed` drift on a critical-sink node (DL-5 escalation) is the highest
signal: it means an irreversible action was taken outside the certified path,
and a controlled replay reproduced it.

## 5. Respond to a finding

1. Open the dashboard (`uv run driftlab dashboard`) → agent detail → see the
   evidence events and the experiment rationale.
2. If the drift is expected (e.g. an approved temporary change), issue a
   **waiver** and record the rationale + expiry in the baseline's `props`
   (see CERTIFICATION-GUIDE §4). Re-run; the waived control no longer scores.
3. If the drift is real, route to the agent owner for remediation, then re-certify
   the baseline once the agent is fixed (new baseline hash → new cycle).

## 6. Schedule continuous monitoring

Two templates ship in `ops/`:

- **launchd** (macOS): copy `ops/com.driftlab.monitor.plist` to
  `~/Library/LaunchAgents/`, fix the paths, `launchctl load` it. Runs hourly;
  staleness policy decides what actually executes.
- **cron**: `crontab ops/crontab.txt` (hourly; `--scheduled` flag).

The monitor writes artifacts to `DRIFTLAB_DATA_DIR/artifacts/<agent>/<cycle_id>/`
and (optionally) emails a digest if `DRIFTLAB_EMAIL__ENABLED=true`.

## 7. Audit / evidence export

Each cycle writes, per agent:

- `assessment-plan.json` — OSCAL 1.1.2-shaped plan (controls assessed, CA-7 anchor)
- `assessment-results.json` — OSCAL 1.1.2-shaped results (satisfied / not-satisfied
  per control, observations with trace evidence + experiment verdicts)
- `report.md` — operator-facing summary
- `ledger.json` — the deterministic anomaly ledger (byte-identical on re-run)

These are the audit artifacts for SOC 2 / EU AI Act / ISO 42001 evidence.

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: driftlab` | Re-run `uv pip install .` (wheel, not editable) |
| `score 0` unexpectedly | Check the trace actually matches the baseline's vocabulary; run `check --no-experiments` to isolate diff vs experiment |
| Experiments `inconclusive` | The replay sample is too small for the window size; increase trace volume or lower `window_size` in `experiment/loop.py` |
| SMTP digest not sent | Confirm `DRIFTLAB_EMAIL__ENABLED=true` and SMTP vars; failures are non-fatal (logged) |